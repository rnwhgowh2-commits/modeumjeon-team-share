"""P4 Task1 — list_linked_sets 가 카드용 소/판 요약·신호등 상태를 내려주는지."""
import datetime as _dt

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
from lemouton.sets.models import (
    ProductSet, SetProduct, SetChannel, SetChannelOption,
)
from lemouton.sets import set_service as svc


@pytest.fixture
def db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = Session(eng)
    yield s
    s.close()


def _seed(db, market, mkt_stock):
    ps = ProductSet(model_code="M1", name="르무통 메이트 모음전")
    db.add(ps)
    db.flush()
    db.add(SetProduct(set_id=ps.id, model_code="M1", quantity=1))
    ch = SetChannel(set_id=ps.id, market=market, account_key="default",
                    market_product_id="999", status="linked")
    db.add(ch)
    db.flush()
    db.add(SetChannelOption(
        channel_id=ch.id, canonical_sku="SKU1", market_option_id="11",
        status="matched", mkt_stock=mkt_stock, mkt_price=125000,
        mkt_fetched_at=_dt.datetime(2026, 6, 30, 8, 50)))
    db.commit()
    return ps


def test_channel_market_summary_and_signals(db):
    _seed(db, "smartstore", 50)
    rows = svc.list_linked_sets(db)
    assert len(rows) == 1
    ch = rows[0]["channels"][0]
    assert ch["mkt_stock_total"] == 50
    assert ch["mkt_price"] == 125000
    sig = ch["signals"]
    assert sig["send"] == "warn"    # last_sent_at None = 미전송
    assert sig["stock"] == "ok"     # 재고 50 > 0, soldout 알림 없음
    assert sig["price"] == "ok"


def test_market_soldout_makes_stock_sev(db):
    _seed(db, "smartstore", 0)
    ch = svc.list_linked_sets(db)[0]["channels"][0]
    assert ch["mkt_stock_total"] == 0
    assert ch["signals"]["stock"] == "sev"   # mkt_stock 0 → market_soldout → 심각
