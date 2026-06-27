"""구성 × 판매처 채널 CRUD — in-memory SQLite 테스트."""
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


@pytest.fixture
def db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = Session(eng)
    s.add(M.Model(model_code="AF", model_name_raw="에어포스"))
    s.commit()
    yield s
    s.close()


def test_add_channel_and_set_product(db):
    ps = svc.create_set(db, model_code="AF", name="단품")
    c = ch.add_channel(db, set_id=ps.id, market="smartstore", account_key="main")
    db.commit()
    assert c.status == "pending"
    updated = ch.set_channel_product(db, channel_id=c.id,
                                     market_product_id="13153051689",
                                     api_fields={"category": "shoes"})
    db.commit()
    assert updated.market_product_id == "13153051689"
    assert updated.status == "linked"
    assert updated.api_fields == {"category": "shoes"}


def test_add_channel_defaults_account_key(db):
    # account_key 미지정 → 'default' 로 보정(nullable=False)
    ps = svc.create_set(db, model_code="AF", name="단품")
    c = ch.add_channel(db, set_id=ps.id, market="smartstore")
    db.commit()
    assert c.account_key == "default"


def test_list_and_remove_channel(db):
    ps = svc.create_set(db, model_code="AF", name="단품")
    ch.add_channel(db, set_id=ps.id, market="smartstore")
    c2 = ch.add_channel(db, set_id=ps.id, market="coupang")
    db.commit()
    assert len(ch.list_channels(db, ps.id)) == 2
    assert ch.remove_channel(db, c2.id) is True
    db.commit()
    assert len(ch.list_channels(db, ps.id)) == 1


def test_set_channel_product_missing_returns_none(db):
    assert ch.set_channel_product(db, channel_id=9999,
                                  market_product_id="1") is None
