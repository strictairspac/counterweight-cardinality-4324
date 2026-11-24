import logging
from time import time

from fastapi import HTTPException
from sqlalchemy import func, insert, select, text
from sqlalchemy.exc import IntegrityError

from src.config.resources import engine
from src.constants.batch_state import BatchState
from src.constants.job_state import JobState
from src.domain.lot_table import inspection_table
from src.domain.scenario import build_result
from src.models.batches import recheck_batches, recheck_items
from src.models.cases import cases
from src.models.measurements import measurements
from src.models.runs import runs
from src.services import audit
from src.utils.serial import content_digest

logger = logging.getLogger(__name__)

SETTLE_TIMEOUT_SECONDS = 30.0
SETTLE_POLL_SECONDS = 0.05


def _now():
    return int(time())


def _run_status(db, run_id):
    return db.scalar(select(runs.c.status).where(runs.c.id == run_id))


def _store_measurement(db, case_id, run_id, actor, mass, slot, actual):
    """返回 (measurement_id, 是否新测)。

    (case_id, mass, slot_band) 唯一约束是最终防线：两个执行者同时测同一档位时，
    后到者撞唯一键后改用行锁读取先入库的实测数，绝不产生重复实测。
    """
    existing = db.execute(
        select(measurements).where(
            measurements.c.case_id == case_id,
            measurements.c.mass == mass,
            measurements.c.slot_band == slot,
        )
    ).mappings().first()
    if existing is not None:
        return existing["id"], False

    try:
        with db.begin_nested():
            measurement_id = db.execute(insert(measurements).values(
                case_id=case_id, mass=mass, slot_band=slot, actual_count=actual,
                run_id=run_id, actor=actor, created_at=_now(), updated_at=_now(),
            )).inserted_primary_key[0]
        return measurement_id, True
    except IntegrityError:
        row = db.execute(
            select(measurements.c.id).where(
                measurements.c.case_id == case_id,
                measurements.c.mass == mass,
                measurements.c.slot_band == slot,
            ).with_for_update()
        ).one()
        return row[0], False


def _count_missing_bands(db, payload, calibration, inspection, missing_bands):
    counts = {}
    if not missing_bands:
        return counts
    with inspection_table(db, calibration, inspection) as table:
        for mass, slot in missing_bands:
            counts[(mass, slot)] = db.execute(text(f"""
                SELECT COUNT(*) FROM {table}
                WHERE phase = 1 AND mass = :mass AND slot_band = :slot
            """), {"mass": mass, "slot": slot}).scalar_one()
    return counts


def _finalize_if_complete(db, run_id, actor):
    remaining = db.scalar(
        select(func.count()).select_from(recheck_items).where(
            recheck_items.c.run_id == run_id,
            recheck_items.c.status != BatchState.DONE,
        )
    )
    if remaining:
        return False
    run = db.execute(
        select(runs).where(runs.c.id == run_id).with_for_update()
    ).mappings().first()
    if run is None or run["status"] == JobState.DONE:
        return run is not None

    payload = db.scalar(select(cases.c.payload).where(cases.c.id == run["case_id"]))
    stored = {
        (row["mass"], row["slot_band"]): row["actual_count"]
        for row in db.execute(
            select(measurements.c.mass, measurements.c.slot_band, measurements.c.actual_count)
            .where(measurements.c.case_id == run["case_id"])
        ).mappings()
    }
    result = build_result(payload, run["parameter"], db, stored)
    # 全部复检号都有结果的同一事务内出具结果与摘要，证明此时才可签核。
    db.execute(runs.update().where(runs.c.id == run_id).values(
        status=JobState.DONE, result=result, digest=content_digest(result),
        failure=None, stop_requested=0, finished_at=_now(),
    ))
    audit.record(db, JobState.DONE, actor, "run", run_id)
    return True


def process_batch(batch_id, actor, skip_locked=False, worker=False):
    """执行一个复检批次，幂等。

    返回 processed / done / locked / paused / missing。
    同批并发时，行锁把后来者阻塞到先到者提交，后来者看到 done 后直接沿用，
    因此同一批的实测数不会被重复写入。
    """
    with engine.begin() as db:
        statement = select(recheck_batches).where(recheck_batches.c.id == batch_id)
        if skip_locked:
            statement = statement.with_for_update(skip_locked=True)
        else:
            statement = statement.with_for_update()
        batch = db.execute(statement).mappings().first()
        if batch is None:
            return "missing"
        if batch["status"] == BatchState.DONE:
            return "done"

        run = db.execute(
            select(runs).where(runs.c.id == batch["run_id"]).with_for_update()
        ).mappings().first()
        if run is None:
            return "missing"
        if worker and run["status"] == JobState.PAUSED:
            return "paused"

        db.execute(recheck_batches.update().where(recheck_batches.c.id == batch_id).values(
            status=BatchState.RUNNING, claimed_by=actor,
            claimed_at=_now(), attempts=recheck_batches.c.attempts + 1,
        ))

        items = [dict(row) for row in db.execute(
            select(recheck_items).where(recheck_items.c.batch_id == batch_id)
            .order_by(recheck_items.c.position).with_for_update()
        ).mappings()]

        from src.domain.inputs import parse as parse_payload
        payload = db.scalar(select(cases.c.payload).where(cases.c.id == run["case_id"]))
        calibration, inspection, _checks = parse_payload(payload)

        known = {
            (row["mass"], row["slot_band"]): (row["id"], row["actual_count"])
            for row in db.execute(
                select(measurements.c.id, measurements.c.mass,
                       measurements.c.slot_band, measurements.c.actual_count)
                .where(measurements.c.case_id == run["case_id"])
            ).mappings()
        }
        missing_bands = []
        for item in items:
            band = (item["mass"], item["slot_band"])
            if band not in known and band not in missing_bands:
                missing_bands.append(band)

        counts = _count_missing_bands(db, payload, calibration, inspection, missing_bands)

        reused = 0
        newly_measured = 0
        for item in items:
            band = (item["mass"], item["slot_band"])
            if band in known:
                measurement_id, actual_count = known[band]
                reused += 1
            else:
                measurement_id, created = _store_measurement(
                    db, run["case_id"], run["id"], actor,
                    item["mass"], item["slot_band"], counts[band],
                )
                actual_count = counts[band]
                known[band] = (measurement_id, actual_count)
                if created:
                    newly_measured += 1
                else:
                    reused += 1
            db.execute(recheck_items.update().where(recheck_items.c.id == item["id"]).values(
                status=BatchState.DONE, measurement_id=measurement_id,
                actual_count=actual_count, measured_at=_now(),
            ))

        db.execute(recheck_batches.update().where(recheck_batches.c.id == batch_id).values(
            status=BatchState.DONE, finished_at=_now(),
        ))
        _finalize_if_complete(db, run["id"], actor)
        logger.info(
            "batch %s processed by %s (new=%s reused=%s)",
            batch_id, actor, newly_measured, reused,
        )
        return "processed"


def list_pending_batch_ids(db, run_id):
    return list(db.scalars(
        select(recheck_batches.c.id)
        .where(recheck_batches.c.run_id == run_id,
               recheck_batches.c.status != BatchState.DONE)
        .order_by(recheck_batches.c.batch_no)
    ))


def wait_until_settled(run_id, timeout=SETTLE_TIMEOUT_SECONDS):
    """等待其他并发执行者把剩余批次处理完，直到 run 到达稳定状态。

    done/failed 是终态；paused 是用户显式中断的稳定态，也应立即返回由调用方决定。
    """
    deadline = time() + timeout
    stable = (JobState.DONE, JobState.FAILED, JobState.PAUSED)
    while time() < deadline:
        with engine.connect() as db:
            status = _run_status(db, run_id)
        if status in stable:
            return status
        time.sleep(SETTLE_POLL_SECONDS)
    with engine.connect() as db:
        return _run_status(db, run_id)


def resume_run(run_id, actor):
    """续跑/重跑同一执行批次：已入库实测数直接沿用，剩余按原批次继续。

    并发安全：多个操作者同时续跑同一 run 时，SKIP LOCKED 让他们领取到不同批次；
    即便撞到同一批，process_batch 的行锁与实测唯一键也保证不重复测量。
    """
    with engine.begin() as db:
        run = db.execute(select(runs).where(runs.c.id == run_id).with_for_update()).mappings().first()
        if run is None:
            raise HTTPException(404, "执行批次不存在")
        if run["status"] != JobState.DONE:
            db.execute(runs.update().where(runs.c.id == run_id).values(
                status=JobState.QUEUED, stop_requested=0,
            ))
            audit.record(db, "resume", actor, "run", run_id)

    while True:
        with engine.connect() as db:
            status = _run_status(db, run_id)
        if status in (JobState.DONE, JobState.FAILED, JobState.PAUSED):
            break

        with engine.connect() as db:
            batch_ids = list_pending_batch_ids(db, run_id)
        if not batch_ids:
            # 没有未完成批次但 run 尚未完成（例如历史数据），尝试补一次收尾。
            with engine.begin() as db:
                _finalize_if_complete(db, run_id, actor)
            break

        made_progress = False
        last_outcome = None
        for batch_id in batch_ids:
            outcome = process_batch(batch_id, actor, skip_locked=True)
            last_outcome = outcome
            if outcome in ("processed", "done"):
                made_progress = True
                break  # 状态已变化，重新扫描，严格按批次顺序推进
            if outcome == "paused":
                break
            # locked：该批正被别人处理，转去处理别的批次
        if last_outcome == "paused":
            break
        if not made_progress:
            # 剩余批次都被其他执行者锁住：交给末尾的 settle 等待他们收尾。
            break

    wait_until_settled(run_id)
    from src.services.runs import get as get_run
    with engine.connect() as db:
        return get_run(db, run_id)


def run_batch(run_id, batch_id, actor):
    with engine.connect() as db:
        owned = db.scalar(select(recheck_batches.c.id).where(
            recheck_batches.c.id == batch_id,
            recheck_batches.c.run_id == run_id,
        ))
        if owned is None:
            raise HTTPException(404, "复检批次不存在")
    outcome = process_batch(batch_id, actor, skip_locked=False)
    if outcome == "missing":
        raise HTTPException(404, "复检批次不存在")
    from src.services.runs import get as get_run
    with engine.connect() as db:
        return get_run(db, run_id)


def claim_next():
    """在所有 queued run 中用 SKIP LOCKED 领取一个未完成批次，返回 (batch_id, run_id)。"""
    with engine.begin() as db:
        row = db.execute(
            select(recheck_batches.c.id, recheck_batches.c.run_id)
            .join(runs, runs.c.id == recheck_batches.c.run_id)
            .where(
                runs.c.status == JobState.QUEUED,
                recheck_batches.c.status != BatchState.DONE,
            )
            .order_by(recheck_batches.c.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        ).mappings().first()
    if row is None:
        return None
    return row["id"], row["run_id"]


def tick(actor="worker"):
    """worker 一次领取并处理一个跨 run 的待处理批次。"""
    claim = claim_next()
    if claim is None:
        return False
    batch_id, _run_id = claim
    outcome = process_batch(batch_id, actor=actor, skip_locked=True, worker=True)
    return outcome in ("processed", "done")
