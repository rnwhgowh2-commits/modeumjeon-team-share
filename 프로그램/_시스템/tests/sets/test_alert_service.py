import pytest
from datetime import datetime, timezone
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
from lemouton.sets.models import SetChannel, SetChannelOption, ChannelChangeEvent
from lemouton.sets import alert_service as al


@pytest.fixture
def db():
    eng = create_engine("sqlite://"); Base.metadata.create_all(eng)
    s = Session(eng); yield s; s.close()


def _chan(db, market, stock):
    ch = SetChannel(set_id=1, market=market, account_key="a",
                    market_product_id="9", status="linked")
    db.add(ch); db.flush()
    db.add(SetChannelOption(channel_id=ch.id, canonical_sku="SKU1",
                            market_option_id="11", status="matched",
                            mkt_stock=stock, mkt_price=133900))
    db.commit(); return ch


def test_market_soldout_smartstore(db):
    _chan(db, "smartstore", 0)
    assert any(a["type"] == "market_soldout" for a in al.alerts_for_set(db, 1))


def test_coupang_stock0_no_soldout(db):
    _chan(db, "coupang", 0)
    assert not any(a["type"] == "market_soldout" for a in al.alerts_for_set(db, 1))


def test_price_spike(db):
    _chan(db, "smartstore", 5)
    db.add(ChannelChangeEvent(set_id=1, market="smartstore", canonical_sku="SKU1",
        field="price", source="market", prev_value=100000, next_value=133900,
        at=datetime(2026, 6, 30, tzinfo=timezone.utc)))
    db.commit()
    assert any(a["type"] == "price_spike" for a in al.alerts_for_set(db, 1))
