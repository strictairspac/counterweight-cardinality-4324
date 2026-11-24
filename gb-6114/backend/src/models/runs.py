from sqlalchemy import JSON, BigInteger, Column, ForeignKey, Integer, String, Table, text

from .base import metadata


runs = Table(
    "runs", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("case_id", ForeignKey("cases.id"), nullable=False, index=True),
    Column("status", String(16), nullable=False, index=True),
    Column("parameter", Integer, nullable=False),
    Column("actor", String(48), nullable=False),
    Column("created_at", BigInteger, nullable=False),
    Column("finished_at", BigInteger, nullable=True),
    Column("result", JSON(none_as_null=True), nullable=True),
    Column("failure", String(320), nullable=True),
    Column("digest", String(64), nullable=True),
    # 协作式中断标记：当前批次跑完后停止，等待人工「续跑」。
    Column("stop_requested", Integer, nullable=False, server_default=text("0"), default=0),
)
