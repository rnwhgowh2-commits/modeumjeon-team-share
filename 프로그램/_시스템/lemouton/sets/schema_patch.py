"""판매처 현재값 컬럼 멱등 ALTER — set_channel_options 테이블용.

create_all 은 기존 테이블에 신규 컬럼을 추가하지 않으므로,
라이브 DB 에 mkt_stock / mkt_price / mkt_fetched_at 컬럼을 안전하게 추가한다.
"""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

# 추가할 컬럼 정의: (column_name, sqlite_type, postgresql_type)
_COLUMNS = [
    ("mkt_stock",      "INTEGER",   "INTEGER"),
    ("mkt_price",      "INTEGER",   "INTEGER"),
    ("mkt_fetched_at", "TIMESTAMP", "TIMESTAMP"),
]

_TABLE = "set_channel_options"


def ensure_market_columns(engine: Engine) -> None:
    """set_channel_options 테이블에 mkt_* 컬럼이 없으면 ALTER TABLE 로 추가한다.

    - 테이블이 없으면 그냥 return (create_all 이 아직 안 됐거나 테스트 환경).
    - 이미 컬럼이 있으면 아무것도 하지 않는다 (멱등).
    - SQLite / PostgreSQL 양쪽 호환.
    """
    insp = inspect(engine)
    if _TABLE not in insp.get_table_names():
        return

    existing_cols = {c["name"] for c in insp.get_columns(_TABLE)}

    with engine.begin() as conn:
        is_pg = conn.dialect.name == "postgresql"
        for col_name, sqlite_type, pg_type in _COLUMNS:
            if col_name in existing_cols:
                continue
            dtype = pg_type if is_pg else sqlite_type
            conn.execute(text(
                f"ALTER TABLE {_TABLE} ADD COLUMN {col_name} {dtype}"
            ))
