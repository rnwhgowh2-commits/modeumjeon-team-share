"""schema_patch.ensure_market_columns 멱등 ALTER 테스트 (in-memory SQLite)."""
import pytest
from sqlalchemy import create_engine, text, inspect


def test_ensure_market_columns_adds_missing(tmp_path):
    """컬럼 없는 옛 set_channel_options 테이블 → 2회 호출 멱등 → 3컬럼 존재."""
    from lemouton.sets.schema_patch import ensure_market_columns

    eng = create_engine("sqlite://")

    # 옛 테이블: mkt_* 컬럼 없이 수동 생성
    with eng.begin() as conn:
        conn.execute(text(
            "CREATE TABLE set_channel_options ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  channel_id INTEGER NOT NULL,"
            "  canonical_sku VARCHAR(128) NOT NULL,"
            "  status VARCHAR(16) NOT NULL"
            ")"
        ))

    # 1회 호출
    ensure_market_columns(eng)
    # 2회 호출 (멱등)
    ensure_market_columns(eng)

    insp = inspect(eng)
    col_names = {c["name"] for c in insp.get_columns("set_channel_options")}
    assert "mkt_stock" in col_names
    assert "mkt_price" in col_names
    assert "mkt_fetched_at" in col_names


def test_ensure_market_columns_no_table_is_noop():
    """테이블 없으면 에러 없이 return."""
    from lemouton.sets.schema_patch import ensure_market_columns

    eng = create_engine("sqlite://")
    # 테이블 없음 — 예외 없어야 함
    ensure_market_columns(eng)
