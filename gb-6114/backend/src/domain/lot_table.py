from contextlib import contextmanager
from uuid import uuid4

from sqlalchemy import text


def _band_collation(db):
    # 生产目标是 MySQL 8，沿用 utf8mb4_0900_bin 的精确匹配；
    # MariaDB 没有该排序规则，退回 utf8mb4_bin（同样是二进制精确比较）。
    if db.dialect.name != "mysql":
        return ""
    if getattr(db.dialect, "is_mariadb", False):
        return " COLLATE utf8mb4_bin"
    return " COLLATE utf8mb4_0900_bin"


@contextmanager
def inspection_table(db, calibration, inspection):
    table = f"counterweight_lot_{uuid4().hex[:12]}"
    collation = _band_collation(db)
    if db.dialect.name == "mysql":
        ddl = f"""
        CREATE TEMPORARY TABLE {table} (
            measurement_id INTEGER AUTO_INCREMENT PRIMARY KEY,
            phase TINYINT NOT NULL,
            mass VARCHAR(24){collation} NOT NULL,
            slot_band VARCHAR(24){collation} NOT NULL,
            INDEX phase_bands (phase, mass, slot_band)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    else:
        ddl = f"""
        CREATE TEMPORARY TABLE {table} (
            measurement_id INTEGER PRIMARY KEY,
            phase INTEGER NOT NULL,
            mass VARCHAR(24) NOT NULL,
            slot_band VARCHAR(24) NOT NULL
        )
        """
    db.execute(text(ddl))
    try:
        insert = text(f"INSERT INTO {table} (phase, mass, slot_band) VALUES (:phase, :mass, :slot)")
        for phase, cells in enumerate((calibration, inspection)):
            for cell in cells:
                db.execute(insert, [dict(phase=phase, mass=cell.mass, slot=cell.slot) for _ in range(cell.count)])
        yield table
    finally:
        drop = "DROP TEMPORARY TABLE IF EXISTS" if db.dialect.name == "mysql" else "DROP TABLE IF EXISTS"
        db.execute(text(f"{drop} {table}"))


def joint_frequencies(db, table):
    rows = db.execute(text(f"""
        SELECT mass, slot_band, COUNT(*) AS pieces
        FROM {table} WHERE phase = 0 GROUP BY mass, slot_band
    """))
    return {(row.mass, row.slot_band): row.pieces for row in rows}


def actual_count(db, table, check):
    return db.execute(text(f"""
        SELECT COUNT(*) FROM {table}
        WHERE phase = 1 AND mass = :mass AND slot_band = :slot
    """), {"mass": check.mass, "slot": check.slot}).scalar_one()


def actual_counts_for_bands(db, payload, bands):
    """装载待查批次明细，对给定档位组合逐一做真实 COUNT 验核。

    bands: 可迭代的 (mass, slot)。返回 {(mass, slot): count}。
    """
    calibration, inspection, _checks = parse_payload(payload)
    wanted = list(dict.fromkeys(bands))
    counts = {}
    with inspection_table(db, calibration, inspection) as table:
        for mass, slot in wanted:
            counts[(mass, slot)] = db.execute(text(f"""
                SELECT COUNT(*) FROM {table}
                WHERE phase = 1 AND mass = :mass AND slot_band = :slot
            """), {"mass": mass, "slot": slot}).scalar_one()
    return counts


def parse_payload(payload):
    # 延迟导入避免 domain 包内循环依赖。
    from .inputs import parse
    return parse(payload)
