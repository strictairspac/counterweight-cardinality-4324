from enum import StrEnum


class JobState(StrEnum):
    QUEUED = "queued"
    PAUSED = "paused"
    DONE = "done"
    FAILED = "failed"
