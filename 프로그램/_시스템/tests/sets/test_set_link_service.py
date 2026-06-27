"""구성별 연동 실행 — in-memory SQLite + 가짜 fetcher(네트워크 없음)."""
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

import lemouton.sourcing.models as M
from lemouton.sets import set_service as svc
from lemouton.sets import channel_service as ch
from lemouton.sets import set_link_service as link
from lemouton.sets.models import SetChannelOption


@pytest.fixture
def db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = Session(eng)
    s.add(M.Model(model_code="AF", model_name_raw="에어포스"))
    for sku, c, z in [("AF-블랙-260", "블랙", "260"),
                      ("AF-블루-270", "블루", "270")]:
        s.add(M.Option(canonical_sku=sku, model_code="AF",
                       color_code=c, color_display=c, size_code=z, size_display=z))
    s.commit()
    yield s
    s.close()


def _set_with_channel(db, product_id="555"):
    ps = svc.create_set(db, model_code="AF", name="단품")
    sp = svc.add_product(db, set_id=ps.id, model_code="AF")
    svc.set_options(db, set_product_id=sp.id,
                    canonical_skus=["AF-블랙-260", "AF-블루-270"])
    c = ch.add_channel(db, set_id=ps.id, market="smartstore")
    ch.set_channel_product(db, channel_id=c.id, market_product_id=product_id)
    db.commit()
    return c


def _fetcher_ok(market, product_id):
    from lemouton.uploader.market_fetch import FetchResult
    from lemouton.uploader.linker import MarketOption
    return FetchResult(success=True, product_name="에어포스", error=None, options=[
        MarketOption(option_id="11", color="블랙", size="260", stock=5),
        MarketOption(option_id="22", color="navy", size="270mm", stock=0),
        MarketOption(option_id="99", color="레드", size="999", stock=1),
    ])


def test_link_set_channel_persists_matched(db):
    c = _set_with_channel(db)
    result = link.link_set_channel(db, c.id, fetcher=_fetcher_ok)
    db.commit()
    assert result["ok"] is True
    assert result["linked"] == 2
    assert result["unmatched"] == 1
    rows = {r.canonical_sku: r for r in
            db.query(SetChannelOption).filter_by(channel_id=c.id).all()}
    assert rows["AF-블랙-260"].market_option_id == "11"
    assert rows["AF-블랙-260"].status == "matched"
    assert rows["AF-블루-270"].market_option_id == "22"
    from lemouton.sets.models import SetChannel
    assert db.get(SetChannel, c.id).status == "linked"


def test_link_set_channel_rerun_replaces(db):
    c = _set_with_channel(db)
    link.link_set_channel(db, c.id, fetcher=_fetcher_ok)
    db.commit()
    link.link_set_channel(db, c.id, fetcher=_fetcher_ok)
    db.commit()
    assert db.query(SetChannelOption).filter_by(channel_id=c.id).count() == 2


def test_link_set_channel_duplicate_sku_writes_one_duplicate(db):
    c = _set_with_channel(db)
    def _dup(market, product_id):
        from lemouton.uploader.market_fetch import FetchResult
        from lemouton.uploader.linker import MarketOption
        return FetchResult(success=True, product_name="x", error=None, options=[
            MarketOption(option_id="A", color="블랙", size="260"),
            MarketOption(option_id="B", color="black", size="260mm"),
        ])
    result = link.link_set_channel(db, c.id, fetcher=_dup)
    db.commit()
    assert result["linked"] == 0
    assert result["duplicate"] == 1
    rows = db.query(SetChannelOption).filter_by(channel_id=c.id).all()
    blk = [r for r in rows if r.canonical_sku == "AF-블랙-260"]
    assert len(blk) == 1 and blk[0].status == "duplicate" and blk[0].market_option_id is None


def test_link_set_channel_missing_product_id(db):
    ps = svc.create_set(db, model_code="AF", name="단품")
    c = ch.add_channel(db, set_id=ps.id, market="smartstore")
    db.commit()
    result = link.link_set_channel(db, c.id, fetcher=_fetcher_ok)
    assert result["ok"] is False
    assert db.query(SetChannelOption).count() == 0


def test_link_set_channel_fetch_failure(db):
    c = _set_with_channel(db)
    def _bad(market, product_id):
        from lemouton.uploader.market_fetch import FetchResult
        return FetchResult(success=False, product_name=None, options=[], error="없음")
    result = link.link_set_channel(db, c.id, fetcher=_bad)
    assert result["ok"] is False
    assert db.query(SetChannelOption).count() == 0
