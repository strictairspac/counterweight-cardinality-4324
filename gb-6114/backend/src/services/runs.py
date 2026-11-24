from time import time

from fastapi import HTTPException
from sqlalchemy import insert, select

from src.constants.batch_state import BatchState
from src.constants.job_state import JobState
from src.domain.batches import plan_batches
from src.domain.inputs import parse as parse_payload
from src.domain.scenario import CONFIG
from src.models.batches import recheck_batches, recheck_items
from src.models.cases import cases
from src.models.measurements import measurements
from src.models.runs import runs
from . import audit, cases as case_service


def query():
    return select(runs, cases.c.title.label("case_title")).join(cases, cases.c.id == runs.c.case_id)


def get(db, run_id):
    run = db.execute(query().where(runs.c.id == run_id)).mappings().first()
    if run is None:
        raise HTTPException(404, "执行批次不存在")
    entry = dict(run)
    batch_rows = [dict(row) for row in db.execute(
        select(recheck_batches).where(recheck_batches.c.run_id == run_id).order_by(recheck_batches.c.batch_no)
    ).mappings()]
    item_rows = [dict(row) for row in db.execute(
        select(recheck_items).where(recheck_items.c.run_id == run_id).order_by(recheck_items.c.position)
    ).mappings()]
    ledger = [dict(row) for row in db.execute(
        select(measurements).where(measurements.c.case_id == entry["case_id"]).order_by(measurements.c.id)
    ).mappings()]

    codes_by_band = {}
    for item in item_rows:
        codes_by_band.setdefault((item["mass"], item["slot_band"]), []).append(item["code"])
    for record in ledger:
        record["codes"] = codes_by_band.get((record["mass"], record["slot_band"]), [])
        record["shared"] = len(record["codes"]) > 1

    finished_items = sum(item["status"] == BatchState.DONE for item in item_rows)
    done_batches = sum(batch["status"] == BatchState.DONE for batch in batch_rows)
    entry["batches"] = batch_rows
    entry["items"] = item_rows
    entry["measurements"] = ledger
    entry["progress"] = {
        "checks_total": len(item_rows),
        "checks_done": finished_items,
        "batches_total": len(batch_rows),
        "batches_done": done_batches,
        "measurements_total": len(ledger),
        "all_results": bool(item_rows) and finished_items == len(item_rows),
    }
    return entry


def list_entries(db):
    return [dict(row) for row in db.execute(query().order_by(runs.c.id.desc()).limit(100)).mappings()]


def enqueue(db, case_id, parameter, actor):
    if parameter > CONFIG["max_parameter"]:
        raise HTTPException(422, f"参数不能超过 {CONFIG['max_parameter']}")
    case = case_service.get(db, case_id)
    try:
        _calibration, _inspection, checks = parse_payload(case["payload"])
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    change = db.execute(insert(runs).values(
        case_id=case_id, status=JobState.QUEUED, parameter=parameter, actor=actor,
        created_at=int(time()), stop_requested=0,
    ))
    run_id = change.inserted_primary_key[0]

    # 原批次在提交时一次性落库，之后续跑、并发重跑都沿用同一批编号与顺序。
    position = 0
    for batch_no, group in enumerate(plan_batches(checks), start=1):
        batch_id = db.execute(insert(recheck_batches).values(
            run_id=run_id, batch_no=batch_no, title=f"第 {batch_no} 批",
            status=BatchState.PENDING, total=len(group), attempts=0,
        )).inserted_primary_key[0]
        for check in group:
            position += 1
            db.execute(insert(recheck_items).values(
                run_id=run_id, batch_id=batch_id, position=position,
                code=check.code, mass=check.mass, slot_band=check.slot,
                status=BatchState.PENDING,
            ))

    audit.record(db, "enqueue", actor, "run", run_id)
    return get(db, run_id)


def pause(db, run_id, actor):
    run = db.execute(select(runs).where(runs.c.id == run_id).with_for_update()).mappings().first()
    if run is None:
        raise HTTPException(404, "执行批次不存在")
    if run["status"] == JobState.DONE:
        raise HTTPException(409, "全部复检号已有结果，容量证明已可签核，无需中断")
    if run["status"] == JobState.PAUSED:
        return get(db, run_id)
    db.execute(runs.update().where(runs.c.id == run_id).values(
        status=JobState.PAUSED, stop_requested=1,
    ))
    audit.record(db, "pause", actor, "run", run_id)
    return get(db, run_id)
