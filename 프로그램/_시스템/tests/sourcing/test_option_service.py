"""tests/sourcing/test_option_service.py — 조합 추가 서비스 (Phase 2 · Task 4).

ai-workflow cycle 20260521 — in-memory SQLite 통합 테스트.
"""
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from shared.db import Base

# create_all 이 모든 FK 타겟 테이블을 찾도록 전체 모델 모듈 등록 (app.py 와 동일)
for _m in (
    "lemouton.sourcing.models", "lemouton.sourcing.models_pricing",
    "lemouton.sourcing.models_v2", "lemouton.pricing.settings",
    "lemouton.uploader.models", "lemouton.templates.models",
    "lemouton.inventory.models", "lemouton.sources.models",
    "lemouton.multitenancy.models", "lemouton.audit.models",
    "lemouton.mapping.models",
):
    try:
        __import__(_m)
    except ImportError:
        pass

import lemouton.sourcing.models as M
from lemouton.sourcing.option_service import (
    create_combination_options, save_step_design,
)


@pytest.fixture
def db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = Session(eng)
    s.add(M.Model(model_code="AF", model_name_raw="에어포스"))
    s.commit()
    yield s
    s.close()


def test_create_2axis(db):
    steps = [
        {"axis_name": "색상", "values": ["블랙", "화이트"]},
        {"axis_name": "사이즈", "values": ["250", "260"]},
    ]
    r = create_combination_options(db, "AF", steps)
    assert r['created'] == 4
    opts = db.query(M.Option).filter_by(model_code="AF").all()
    assert len(opts) == 4
    bk250 = db.query(M.Option).filter_by(canonical_sku="AF-블랙-250").first()
    assert bk250 is not None
    assert json.loads(bk250.axis_values_json) == ["블랙", "250"]
    assert bk250.color_code == "블랙" and bk250.size_code == "250"


def test_create_dedup_on_recall(db):
    create_combination_options(db, "AF", [{"axis_name": "색상",
                                           "values": ["블랙", "화이트"]}])
    # 재호출 — 블랙은 이미 있으니 그레이만 신규
    r = create_combination_options(db, "AF", [{"axis_name": "색상",
                                               "values": ["블랙", "그레이"]}])
    assert r['created'] == 1
    assert db.query(M.Option).filter_by(model_code="AF").count() == 3


def test_create_selected_only(db):
    steps = [
        {"axis_name": "색상", "values": ["블랙", "화이트"]},
        {"axis_name": "사이즈", "values": ["250", "260"]},
    ]
    r = create_combination_options(db, "AF", steps,
                                   selected=[["블랙", "250"], ["화이트", "260"]])
    assert r['created'] == 2
    assert sorted(r['skus']) == ["AF-블랙-250", "AF-화이트-260"]


def test_step_design_saved(db):
    create_combination_options(db, "AF", [{"axis_name": "색상",
                                           "values": ["블랙"]}])
    rows = db.query(M.BundleOptionStep).filter_by(model_code="AF").all()
    assert len(rows) == 1
    assert rows[0].axis_name == "색상" and rows[0].step_no == 1


def test_step_design_replaced(db):
    save_step_design(db, "AF", [{"axis_name": "색상", "values": ["블랙"]}])
    db.commit()
    save_step_design(db, "AF", [
        {"axis_name": "모델", "values": ["에어포스"]},
        {"axis_name": "색상", "values": ["블랙"]},
    ])
    db.commit()
    rows = db.query(M.BundleOptionStep).filter_by(model_code="AF").all()
    assert len(rows) == 2          # 기존 1개 교체 → 새 2개
