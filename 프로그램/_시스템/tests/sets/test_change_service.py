"""변동 기록 서비스 record_change 테스트 (in-memory SQLite)."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from shared.db import Base

for _m in (
    "lemouton.sourcing.models", "lemouton.sourcing.models_pricing",
    "lemouton.sourcing.models_v2", "lemouton.pricing.settings",
    "lemouton.uploader.models", "lemouton.templates.models",
    "lemouton.inventory.models", "lemouton.sources.models",
    "lemouton.multitenancy.models", "lemouton.audit.models",
    "lemouton.mapping.models", "lemouton.sets.models",
):
    try:
        __import__(_m)
    except ImportError:
        pass

from lemouton.sets.models import ChannelChangeEvent
from lemouton.sets import change_service


@pytest.fixture
def db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = Session(eng)
    yield s
    s.close()


def test_record_change_creates_event(db):
    """8→0 변동: True 반환, 이벤트 1행 저장, next_value==0."""
    result = change_service.record_change(
        db,
        set_id=6,
        market="coupang",
        canonical_sku="X",
        field="stock",
        source="market",
        prev_value=8,
        next_value=0,
    )
    db.commit()

    assert result is True
    events = db.query(ChannelChangeEvent).all()
    assert len(events) == 1
    assert events[0].next_value == 0


def test_record_change_same_value_no_event(db):
    """0→0 동일값: False 반환, 이벤트 0행."""
    result = change_service.record_change(
        db,
        set_id=6,
        market="coupang",
        canonical_sku="X",
        field="stock",
        source="market",
        prev_value=0,
        next_value=0,
    )
    db.commit()

    assert result is False
    events = db.query(ChannelChangeEvent).all()
    assert len(events) == 0


def test_list_changes_filters_and_orders(db):
    from datetime import datetime, timezone
    from lemouton.sets import change_service as cs
    def ev(i, market, field, source, p, n):
        db.add(ChannelChangeEvent(set_id=7, market=market, canonical_sku="S"+str(i),
               field=field, source=source, prev_value=p, next_value=n,
               at=datetime(2026, 6, 30, 1, i, 0, tzinfo=timezone.utc)))
    ev(1, "coupang", "stock", "market", 8, 0)
    ev(2, "coupang", "price", "market", 100, 90)
    ev(3, "smartstore", "stock", "market", 5, 3)
    ev(4, "coupang", "stock", "source", 10, 12)
    db.commit()
    rows = cs.list_changes(db, set_id=7, market="coupang", field="stock")
    assert [r["canonical_sku"] for r in rows] == ["S4", "S1"]
    assert rows[0]["source"] == "source" and rows[0]["next_value"] == 12
    allc = cs.list_changes(db, set_id=7, market="coupang")
    assert len(allc) == 3
    assert len(cs.list_changes(db, set_id=7)) == 4


def test_snapshot_source_values_records_and_idempotent(db):
    from lemouton.sets import change_service as cs
    from lemouton.sets.models import SetChannel, SetChannelOption
    ch = SetChannel(set_id=5, market="smartstore", account_key="a", market_product_id="9", status="linked")
    db.add(ch); db.flush()
    db.add(SetChannelOption(channel_id=ch.id, canonical_sku="K", market_option_id="1", status="matched"))
    db.commit()
    n1 = cs.snapshot_source_values(db, set_id=5, value_map={"K": {"stock": 7, "price": 50000}}); db.commit()
    assert n1 == 2
    evs = db.query(ChannelChangeEvent).filter_by(source="source").all()
    assert {(e.field, e.next_value) for e in evs} == {("stock", 7), ("price", 50000)}
    n2 = cs.snapshot_source_values(db, set_id=5, value_map={"K": {"stock": 7, "price": 50000}}); db.commit()
    assert n2 == 0
    n3 = cs.snapshot_source_values(db, set_id=5, value_map={"K": {"stock": 0, "price": 50000}}); db.commit()
    assert n3 == 1
    last = (db.query(ChannelChangeEvent).filter_by(source="source", field="stock")
            .order_by(ChannelChangeEvent.at.desc()).first())
    assert last.prev_value == 7 and last.next_value == 0
