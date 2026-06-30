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
from lemouton.sets.models import SetChannel, SetChannelOption, ChannelChangeEvent
from lemouton.sets import collect_service as col


class _MO:
    def __init__(self, oid, stock, price):
        self.option_id = oid; self.stock = stock; self.price = price
        self.color = ""; self.size = ""; self.usable = True


class _FR:
    def __init__(self, options):
        self.success = True; self.product_name = "P"; self.options = options; self.error = None


@pytest.fixture
def db():
    eng = create_engine("sqlite://"); Base.metadata.create_all(eng)
    s = Session(eng); yield s; s.close()


def _seed(db, market):
    ch = SetChannel(set_id=1, market=market, account_key="a",
                    market_product_id="999", status="linked")
    db.add(ch); db.flush()
    db.add(SetChannelOption(channel_id=ch.id, canonical_sku="SKU1",
                            market_option_id="11", status="matched",
                            mkt_stock=8, mkt_price=140000))
    db.commit(); return ch


def test_collect_smartstore_records_change(db):
    ch = _seed(db, "smartstore")
    fetcher = lambda market, pid, env_prefix=None: _FR([_MO("11", 0, 133900)])
    r = col.collect_channel(db, ch.id, fetcher=fetcher); db.commit()
    sco = db.query(SetChannelOption).filter_by(channel_id=ch.id).first()
    evs = db.query(ChannelChangeEvent).all()
    assert r["ok"] and sco.mkt_stock == 0 and sco.mkt_price == 133900
    assert {(e.field, e.prev_value, e.next_value) for e in evs} == {("stock", 8, 0), ("price", 140000, 133900)}


def test_collect_coupang_stock_null(db):
    ch = _seed(db, "coupang")
    fetcher = lambda market, pid, env_prefix=None: _FR([_MO("11", 0, 133900)])
    col.collect_channel(db, ch.id, fetcher=fetcher); db.commit()
    sco = db.query(SetChannelOption).filter_by(channel_id=ch.id).first()
    assert sco.mkt_stock is None and sco.mkt_price == 133900


def test_collect_set_iterates_channels(db):
    _seed(db, "smartstore")
    fetcher = lambda market, pid, env_prefix=None: _FR([_MO("11", 3, 133900)])
    r = col.collect_set(db, 1, fetcher=fetcher); db.commit()
    assert r["ok"] and len(r["channels"]) == 1 and r["channels"][0]["market"] == "smartstore"
