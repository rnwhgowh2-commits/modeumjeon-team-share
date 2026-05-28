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
    """[Phase 2-1] selected 명시 필수. 그 조합만 생성."""
    import re
    steps = [
        {"axis_name": "색상", "values": ["블랙", "화이트"]},
        {"axis_name": "사이즈", "values": ["250", "260"]},
    ]
    # selected 명시 — 4 조합 모두
    r = create_combination_options(db, "AF", steps,
                                   selected=[["블랙", "250"], ["블랙", "260"],
                                             ["화이트", "250"], ["화이트", "260"]])
    assert r['created'] == 4
    opts = db.query(M.Option).filter_by(model_code="AF").all()
    assert len(opts) == 4
    for o in opts:
        assert re.match(r'^SKU-[A-Z0-9]{8}$', o.canonical_sku)
        assert o.boxhero_sku == o.canonical_sku
        assert o.barcode and len(o.barcode) == 13


def test_create_no_selected_only_step_design(db):
    """[Phase 2-1 핵심] selected 없으면 옵션 0건 (자동 카르테시안 금지). 단계 설계만 저장."""
    r = create_combination_options(db, "AF", [
        {"axis_name": "색상", "values": ["블랙", "화이트"]},
        {"axis_name": "사이즈", "values": ["250", "260"]},
    ])
    assert r['created'] == 0
    assert db.query(M.Option).filter_by(model_code="AF").count() == 0
    # 단계 설계는 저장됨
    assert db.query(M.BundleOptionStep).filter_by(model_code="AF").count() == 2


def test_create_dedup_on_recall(db):
    """[Phase 1-2] axis 기반 중복 검사 — 같은 (model, axis) 면 신규 생성 X."""
    create_combination_options(db, "AF",
                               [{"axis_name": "색상", "values": ["블랙", "화이트"]}],
                               selected=[["블랙"], ["화이트"]])
    # 재호출 — 블랙은 이미 있으니 그레이만 신규
    r = create_combination_options(db, "AF",
                                   [{"axis_name": "색상",
                                     "values": ["블랙", "그레이"]}],
                                   selected=[["블랙"], ["그레이"]])
    assert r['created'] == 1
    assert db.query(M.Option).filter_by(model_code="AF").count() == 3


def test_create_selected_only(db):
    """[Phase 1-2] selected 만 생성. canonical_sku 는 SKU-XXX 형식."""
    import re
    steps = [
        {"axis_name": "색상", "values": ["블랙", "화이트"]},
        {"axis_name": "사이즈", "values": ["250", "260"]},
    ]
    r = create_combination_options(db, "AF", steps,
                                   selected=[["블랙", "250"], ["화이트", "260"]])
    assert r['created'] == 2
    # SKU-XXX 형식 검증
    for sku in r['skus']:
        assert re.match(r'^SKU-[A-Z0-9]{8}$', sku), f"SKU 형식 위반: {sku}"
    # axis 로 옵션 확인
    opts = db.query(M.Option).filter_by(model_code="AF").all()
    axis_set = {(o.color_code, o.size_code) for o in opts}
    assert axis_set == {("블랙", "250"), ("화이트", "260")}


def test_no_korean_canonical_sku(db):
    """[Phase 1 핵심] 어떤 매트릭스 입력도 한글 canonical_sku 생성 X."""
    create_combination_options(db, "AF", [
        {"axis_name": "색상", "values": ["블랙", "스카이블루", "다크네이비"]},
        {"axis_name": "사이즈", "values": ["220", "230"]},
    ])
    opts = db.query(M.Option).filter_by(model_code="AF").all()
    for o in opts:
        # 한글 코드포인트 (가-힣) 검증
        assert not any('가' <= ch <= '힣' for ch in o.canonical_sku), \
            f"한글 SKU 발견: {o.canonical_sku}"


def test_step_design_saved(db):
    create_combination_options(db, "AF",
                               [{"axis_name": "색상", "values": ["블랙"]}],
                               selected=[["블랙"]])
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
