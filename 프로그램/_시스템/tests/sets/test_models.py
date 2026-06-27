"""구성 레이어 모델 — in-memory SQLite 테스트(네트워크 없음)."""
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
from lemouton.sets.models import ProductSet, SetProduct, SetOption, SetChannel


@pytest.fixture
def db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = Session(eng)
    s.add(M.Model(model_code="AF", model_name_raw="에어포스"))
    s.add(M.Option(canonical_sku="AF-블랙-260", model_code="AF",
                   color_code="블랙", size_code="260"))
    s.commit()
    yield s
    s.close()


def test_create_set_with_product_option_channel(db):
    ps = ProductSet(model_code="AF", name="2개세트")
    db.add(ps); db.flush()
    sp = SetProduct(set_id=ps.id, model_code="AF", quantity=2)
    db.add(sp); db.flush()
    db.add(SetOption(set_product_id=sp.id, canonical_sku="AF-블랙-260"))
    db.add(SetChannel(set_id=ps.id, market="smartstore"))
    db.commit()

    got = db.get(ProductSet, ps.id)
    assert got.name == "2개세트"
    assert got.products[0].quantity == 2
    assert got.products[0].options[0].canonical_sku == "AF-블랙-260"
    assert got.channels[0].market == "smartstore"
    assert got.channels[0].status == "pending"


def test_cascade_delete_set_removes_children(db):
    ps = ProductSet(model_code="AF", name="단품")
    db.add(ps); db.flush()
    sp = SetProduct(set_id=ps.id, model_code="AF", quantity=1)
    db.add(sp); db.flush()
    db.add(SetOption(set_product_id=sp.id, canonical_sku="AF-블랙-260"))
    db.add(SetChannel(set_id=ps.id, market="coupang"))
    db.commit()

    db.delete(ps)
    db.commit()
    assert db.query(SetProduct).count() == 0
    assert db.query(SetOption).count() == 0
    assert db.query(SetChannel).count() == 0


def test_channel_unique_set_market_account(db):
    from sqlalchemy.exc import IntegrityError
    ps = ProductSet(model_code="AF", name="단품")
    db.add(ps); db.flush()
    db.add(SetChannel(set_id=ps.id, market="smartstore", account_key="main"))
    db.commit()
    db.add(SetChannel(set_id=ps.id, market="smartstore", account_key="main"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_channel_unique_default_account(db):
    # account_key 미지정 → 'default' 센티넬. 같은 (set, market) 기본계정 중복 차단.
    from sqlalchemy.exc import IntegrityError
    ps = ProductSet(model_code="AF", name="단품")
    db.add(ps); db.flush()
    c1 = SetChannel(set_id=ps.id, market="smartstore")
    db.add(c1)
    db.commit()
    assert c1.account_key == "default"
    db.add(SetChannel(set_id=ps.id, market="smartstore"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_channel_option_link_result_and_cascade(db):
    from lemouton.sets.models import SetChannelOption
    ps = ProductSet(model_code="AF", name="단품")
    db.add(ps); db.flush()
    cha = SetChannel(set_id=ps.id, market="smartstore")
    db.add(cha); db.flush()
    db.add(SetChannelOption(channel_id=cha.id, canonical_sku="AF-블랙-260",
                            market_option_id="111", status="matched"))
    db.commit()
    got = db.get(SetChannel, cha.id)
    assert got.link_results[0].canonical_sku == "AF-블랙-260"
    assert got.link_results[0].market_option_id == "111"
    db.delete(got)
    db.commit()
    assert db.query(SetChannelOption).count() == 0


def test_channel_option_unique_channel_sku(db):
    from sqlalchemy.exc import IntegrityError
    from lemouton.sets.models import SetChannelOption
    ps = ProductSet(model_code="AF", name="단품")
    db.add(ps); db.flush()
    cha = SetChannel(set_id=ps.id, market="smartstore")
    db.add(cha); db.flush()
    db.add(SetChannelOption(channel_id=cha.id, canonical_sku="AF-블랙-260",
                            market_option_id="111", status="matched"))
    db.commit()
    db.add(SetChannelOption(channel_id=cha.id, canonical_sku="AF-블랙-260",
                            market_option_id="222", status="matched"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
