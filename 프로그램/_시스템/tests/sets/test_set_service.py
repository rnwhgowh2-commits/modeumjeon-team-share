"""구성 CRUD 서비스 — in-memory SQLite 테스트."""
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


@pytest.fixture
def db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = Session(eng)
    s.add(M.Model(model_code="AF", model_name_raw="에어포스"))
    for sku, c, z in [("AF-블랙-260", "블랙", "260"),
                      ("AF-블랙-270", "블랙", "270"),
                      ("AF-블루-260", "블루", "260")]:
        s.add(M.Option(canonical_sku=sku, model_code="AF", color_code=c, size_code=z))
    s.commit()
    yield s
    s.close()


def test_create_set_add_product_and_options(db):
    ps = svc.create_set(db, model_code="AF", name="단품")
    sp = svc.add_product(db, set_id=ps.id, model_code="AF", quantity=1)
    rows = svc.set_options(db, set_product_id=sp.id,
                           canonical_skus=["AF-블랙-260", "AF-블랙-270"])
    db.commit()
    assert len(rows) == 2
    detail = svc.get_set_detail(db, ps.id)
    assert detail["name"] == "단품"
    assert detail["products"][0]["quantity"] == 1
    assert set(detail["products"][0]["options"]) == {"AF-블랙-260", "AF-블랙-270"}


def test_set_options_replaces(db):
    ps = svc.create_set(db, model_code="AF", name="단품")
    sp = svc.add_product(db, set_id=ps.id, model_code="AF")
    svc.set_options(db, set_product_id=sp.id, canonical_skus=["AF-블랙-260"])
    svc.set_options(db, set_product_id=sp.id,
                    canonical_skus=["AF-블루-260", "AF-블랙-270"])
    db.commit()
    detail = svc.get_set_detail(db, ps.id)
    assert set(detail["products"][0]["options"]) == {"AF-블루-260", "AF-블랙-270"}


def test_list_sets_and_delete_cascades(db):
    a = svc.create_set(db, model_code="AF", name="단품")
    svc.create_set(db, model_code="AF", name="2개세트")
    db.commit()
    assert len(svc.list_sets(db, "AF")) == 2

    sp = svc.add_product(db, set_id=a.id, model_code="AF")
    svc.set_options(db, set_product_id=sp.id, canonical_skus=["AF-블랙-260"])
    db.commit()
    assert svc.delete_set(db, a.id) is True
    db.commit()
    assert len(svc.list_sets(db, "AF")) == 1
    from lemouton.sets.models import SetOption
    assert db.query(SetOption).count() == 0


def test_get_set_detail_missing_returns_empty(db):
    assert svc.get_set_detail(db, 9999) == {}
