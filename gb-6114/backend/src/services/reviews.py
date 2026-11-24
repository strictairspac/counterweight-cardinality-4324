from time import time

from fastapi import HTTPException
from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError

from src.constants.job_state import JobState
from src.models.reviews import reviews
from . import audit, runs


def get(db, run_id):
    row = db.execute(select(reviews).where(reviews.c.run_id == run_id)).mappings().first()
    return dict(row) if row else None


def sign(db, run_id, data, actor):
    run = runs.get(db, run_id)
    if run["status"] != JobState.DONE or not run.get("progress", {}).get("all_results"):
        done = run.get("progress", {}).get("checks_done", 0)
        total = run.get("progress", {}).get("checks_total", 0)
        raise HTTPException(
            409,
            f"批次执行成功后才能签核：全部复检号都有结果后才可签署容量证明（当前 {done}/{total}）",
        )
    try:
        db.execute(insert(reviews).values(run_id=run_id, note=data.note, actor=actor, created_at=int(time())))
    except IntegrityError as exc:
        raise HTTPException(409, "该批次已经签核") from exc
    audit.record(db, "review", actor, "run", run_id)
    return get(db, run_id)
