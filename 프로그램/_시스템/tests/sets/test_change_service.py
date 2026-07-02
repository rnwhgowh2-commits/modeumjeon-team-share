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


def _seed_ch(db, set_id, market):
    from lemouton.sets.models import SetChannel, SetChannelOption
    ch = SetChannel(set_id=set_id, market=market, account_key="a",
                    market_product_id="9", status="linked")
    db.add(ch); db.flush()
    db.add(SetChannelOption(channel_id=ch.id, canonical_sku="K",
                            market_option_id="1", status="matched"))
    db.commit()


def test_snapshot_records_3_price_stages(db):
    from lemouton.sets import change_service as cs
    _seed_ch(db, 6, "smartstore")
    n = cs.snapshot_source_values(db, set_id=6, value_map={
        "K": {"surface": 145000, "cost": 89000,
              "ss_price": 125000, "cp_price": 129000}}); db.commit()
    evs = {(e.field, e.next_value) for e in
           db.query(ChannelChangeEvent).filter_by(source="source").all()}
    assert ("surface", 145000) in evs
    assert ("cost", 89000) in evs
    assert ("planned", 125000) in evs   # 스마트스토어 → ss_price
    assert n == 3


def test_snapshot_planned_coupang_uses_cp(db):
    from lemouton.sets import change_service as cs
    _seed_ch(db, 7, "coupang")
    cs.snapshot_source_values(db, set_id=7, value_map={
        "K": {"ss_price": 125000, "cp_price": 129000}}); db.commit()
    planned = (db.query(ChannelChangeEvent)
               .filter_by(source="source", field="planned").first())
    assert planned.next_value == 129000   # 쿠팡 → cp_price


def test_list_changes_price_returns_3_stages(db):
    from datetime import datetime, timezone
    from lemouton.sets import change_service as cs
    for f, v in [("surface", 145000), ("cost", 89000),
                 ("planned", 125000), ("stock", 5)]:
        db.add(ChannelChangeEvent(set_id=9, market="smartstore", canonical_sku="K",
               field=f, source="source", prev_value=None, next_value=v,
               at=datetime(2026, 6, 30, tzinfo=timezone.utc)))
    db.commit()
    rows = cs.list_changes(db, set_id=9, field="price")
    assert {r["field"] for r in rows} == {"surface", "cost", "planned"}  # stock 제외


def test_list_automation_log(db):
    from lemouton.sets.models import ProductSet
    from lemouton.sets import change_service as cs
    ps = ProductSet(model_code="AF", name="르무통 메이트")
    db.add(ps); db.flush()
    cs.record_change(db, set_id=ps.id, market="coupang", canonical_sku="AF-GRAY-220",
                     field="stock", source="source", prev_value=12, next_value=4)
    db.commit()
    rows = cs.list_automation_log(db, limit=30)
    assert len(rows) == 1
    r = rows[0]
    assert r["action"] == "값 변동 감지" and r["result"] == "chg"
    assert r["market"] == "쿠팡" and r["market_key"] == "coupang"
    assert "재고" in r["target"] and "12" in r["target"] and "4" in r["target"]
    assert r["brand"] == "르무통 메이트"
