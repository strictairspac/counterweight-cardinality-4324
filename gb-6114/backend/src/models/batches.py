from sqlalchemy import (
    BigInteger,
    Column,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    UniqueConstraint,
    text,
)

from .base import metadata


# 复检批次计划：提交时按原顺序稳定切分，续跑沿用同一批编号，不再重新分批。
recheck_batches = Table(
    "recheck_batches", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("run_id", ForeignKey("runs.id"), nullable=False),
    Column("batch_no", Integer, nullable=False),
    Column("title", String(60), nullable=False),
    Column("status", String(16), nullable=False, server_default=text("'pending'")),
    Column("total", Integer, nullable=False, server_default=text("0")),
    Column("claimed_by", String(48), nullable=True),
    Column("claimed_at", BigInteger, nullable=True),
    Column("finished_at", BigInteger, nullable=True),
    Column("attempts", Integer, nullable=False, server_default=text("0")),
    UniqueConstraint("run_id", "batch_no", name="uq_recheck_batches_run_no"),
    Index("ix_recheck_batches_run_status", "run_id", "status"),
    mysql_charset="utf8mb4",
    mysql_collate="utf8mb4_bin",
)


# 复检号条目：每个复检号一行，即使与别的复检号共用同一实测数也完整保留。
recheck_items = Table(
    "recheck_items", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("run_id", ForeignKey("runs.id"), nullable=False),
    Column("batch_id", ForeignKey("recheck_batches.id"), nullable=False),
    Column("position", Integer, nullable=False),
    Column("code", String(24), nullable=False),
    Column("mass", String(24), nullable=False),
    Column("slot_band", String(24), nullable=False),
    Column("status", String(16), nullable=False, server_default=text("'pending'")),
    Column("measurement_id", ForeignKey("measurements.id"), nullable=True),
    Column("actual_count", Integer, nullable=True),
    Column("measured_at", BigInteger, nullable=True),
    UniqueConstraint("run_id", "code", name="uq_recheck_items_run_code"),
    Index("ix_recheck_items_run_position", "run_id", "position"),
    Index("ix_recheck_items_batch", "batch_id"),
    mysql_charset="utf8mb4",
    mysql_collate="utf8mb4_bin",
)
