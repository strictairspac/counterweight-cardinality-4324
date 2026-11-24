from fastapi import APIRouter, Depends, HTTPException, Response

from src.config.resources import engine
from src.constants.job_state import JobState
from src.controllers.access import identity, operator, reviewer
from src.controllers.workbench import new_review, pause_run, resume_run, run_batch
from src.schemas.reviews import ReviewEntry, ReviewInput
from src.schemas.runs import RunEntry
from src.services import reviews, runs
from src.utils.serial import canonical_json

router = APIRouter(prefix="/runs", tags=["Execution"])


@router.get("", response_model=list[RunEntry], dependencies=[Depends(identity)])
def list_runs():
    with engine.connect() as db:
        return runs.list_entries(db)


@router.get("/{run_id}", response_model=RunEntry, dependencies=[Depends(identity)])
def run_detail(run_id: int):
    with engine.connect() as db:
        return runs.get(db, run_id)


@router.post("/{run_id}/resume", response_model=RunEntry)
def resume(run_id: int, user=Depends(operator)):
    # 续跑/重跑同一批：幂等，已入库实测直接沿用，并发调用安全。
    return resume_run(run_id, user)


# 常见近义路径，全部指向同一个幂等续跑流程。
router.add_api_route("/{run_id}/continue", resume, methods=["POST"], response_model=RunEntry)
router.add_api_route("/{run_id}/retry", resume, methods=["POST"], response_model=RunEntry)


@router.post("/{run_id}/rerun", response_model=RunEntry)
def rerun(run_id: int, user=Depends(operator)):
    # 「重跑同一批」与续跑是同一幂等流程：沿用入库实测，不重复测量。
    return resume_run(run_id, user)


@router.post("/{run_id}/pause", response_model=RunEntry)
def pause(run_id: int, user=Depends(operator)):
    return pause_run(run_id, user)


@router.post("/{run_id}/batches/{batch_id}/run", response_model=RunEntry)
def execute_batch(run_id: int, batch_id: int, user=Depends(operator)):
    return run_batch(run_id, batch_id, user)


@router.get("/{run_id}/review", response_model=ReviewEntry | None, dependencies=[Depends(identity)])
def review_detail(run_id: int):
    with engine.connect() as db:
        runs.get(db, run_id)
        return reviews.get(db, run_id)


@router.post("/{run_id}/review", response_model=ReviewEntry, status_code=201)
def sign(run_id: int, form: ReviewInput, user=Depends(reviewer)):
    return new_review(run_id, form, user)


@router.get("/{run_id}/export", dependencies=[Depends(identity)])
def export(run_id: int):
    with engine.connect() as db:
        run = runs.get(db, run_id)
        if run["status"] != JobState.DONE or not run.get("progress", {}).get("all_results"):
            raise HTTPException(409, "没有可导出的执行结果：全部复检号都有结果后，才可导出可签核的容量证明")
        run["review"] = reviews.get(db, run_id)
    return Response(canonical_json(run), media_type="application/json", headers={
        "Content-Disposition": f"attachment; filename=evidence-{run_id}.json",
    })
