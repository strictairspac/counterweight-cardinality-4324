from sqlalchemy import BigInteger, Column, ForeignKey, Integer, String, Table, UniqueConstraint

from .base import metadata


# 实测数台账。实测数是「资料 + 重量档 + 槽宽档」的客观计数，
# 同一档位组合即使对应多个复检号，也只保留一条实测数，复检号在条目表中全部保留。
measurements = Table(
    "measurements", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("case_id", ForeignKey("cases.id"), nullable=False, index=True),
    Column("mass", String(24), nullable=False),
    Column("slot_band", String(24), nullable=False),
    Column("actual_count", Integer, nullable=False),
    Column("run_id", ForeignKey("runs.id"), nullable=True),
    Column("actor", String(48), nullable=False),
    Column("created_at", BigInteger, nullable=False),
    Column("updated_at", BigInteger, nullable=False),
    UniqueConstraint("case_id", "mass", "slot_band", name="uq_measurements_case_band"),
    mysql_charset="utf8mb4",
    mysql_collate="utf8mb4_bin",
)
