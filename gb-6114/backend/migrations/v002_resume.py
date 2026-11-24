from sqlalchemy import inspect, text

from src.models import batches as _batches  # noqa: F401  注册表结构
from src.models import measurements as _measurements  # noqa: F401
from src.models.base import metadata
from src.models.runs import runs


def upgrade(connection):
    # checkfirst=True：新库直接建齐，旧库只补缺失的续跑相关表。
    metadata.create_all(connection)
    columns = {column["name"] for column in inspect(connection).get_columns(runs.name)}
    if "stop_requested" not in columns:
        connection.execute(text(
            "ALTER TABLE runs ADD COLUMN stop_requested INTEGER NOT NULL DEFAULT 0"
        ))
