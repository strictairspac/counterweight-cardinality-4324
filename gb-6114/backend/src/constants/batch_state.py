from enum import StrEnum


class BatchState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
