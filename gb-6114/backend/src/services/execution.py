import logging
from time import time

from sqlalchemy import select, update

from src.config.resources import engine
from src.constants.job_state import JobState
from src.models.runs import runs
from src.services import inspection
from src.services.audit import record

logger = logging.getLogger(__name__)


def service_one():
    """领取并处理一个复检批次；处理异常归入对应 run 的 JobFailure。"""
    claim = inspection.claim_next()
    if claim is None:
        return False
    batch_id, run_id = claim
    try:
        outcome = inspection.process_batch(batch_id, actor="worker", skip_locked=True, worker=True)
    except Exception as exc:
        raise JobFailure(run_id, exc) from exc
    if outcome == "locked":
        return False
    return True


class JobFailure(Exception):
    def __init__(self, run_id, cause):
        super().__init__(str(cause))
        self.run_id = run_id
        self.cause = cause


def fail(job_failure):
    with engine.begin() as db:
        run_id = job_failure.run_id
        statement = select(runs.c.status).where(runs.c.id == run_id).with_for_update()
        if db.scalar(statement) != JobState.QUEUED:
            return
        cause = job_failure.cause
        if isinstance(cause, (ValueError, TypeError, KeyError, OverflowError)):
            reason = str(cause) or "输入资料或批次参数不符合要求"
        else:
            reason = "处理失败，请检查 worker 日志，或在页面续跑重试"
        finish(db, run_id, {"status": JobState.FAILED, "failure": reason[:320]})


def finish(db, run_id, output):
    db.execute(update(runs).where(runs.c.id == run_id).values(**output, finished_at=int(time())))
    record(db, str(output["status"]), "worker", "run", run_id)
