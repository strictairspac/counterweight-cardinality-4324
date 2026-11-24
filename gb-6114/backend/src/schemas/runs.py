from pydantic import BaseModel, Field

from src.constants.job_state import JobState


class RunInput(BaseModel):
    parameter: int = Field(strict=True, ge=1)


class RunEntry(BaseModel):
    id: int
    case_id: int
    case_title: str | None = None
    status: JobState
    parameter: int
    actor: str
    created_at: int
    finished_at: int | None
    result: dict | None
    failure: str | None
    digest: str | None
    stop_requested: int | None = 0
    progress: dict | None = None
    batches: list[dict] = Field(default_factory=list)
    items: list[dict] = Field(default_factory=list)
    measurements: list[dict] = Field(default_factory=list)
