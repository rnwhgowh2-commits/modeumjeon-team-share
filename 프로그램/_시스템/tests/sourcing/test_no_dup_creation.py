# -*- coding: utf-8 -*-
"""[TEST] create_combination_options 중복 생성 차단 (2026-06-13).

핵심: 이미 (색·사이즈) 옵션이 있으면 '조합 생성'을 다시 눌러도 중복 행을 만들지 않는다.
  - axis_values_json 이 NULL/빈 옛 행도 color/size 폴백으로 인식(기존 사각 차단).
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from shared.db import Base

for _m in (
    "lemouton.sourcing.models", "lemouton.sourcing.models_pricing",
    "lemouton.sources.models", "lemouton.templates.models",
    "lemouton.inventory.models", "lemouton.multitenancy.models",
    "lemouton.audit.models", "lemouton.mapping.models",
):
    try:
        __import__(_m)
    except ImportError:
        pass

import lemouton.sourcing.models as M
from lemouton.sourcing.option_service import create_combination_options

_STEPS = [
    {"axis_name": "색상", "values": ["스카이블루"]},
    {"axis_name": "사이즈", "values": ["220"]},
]


@pytest.fixture
def db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = Session(eng)
    s.add(M.Model(model_code="MM", model_name_raw="모델"))
    s.commit()
    yield s
    s.close()


def test_existing_null_axis_option_blocks_duplicate(db):
    # 옛 행: color/size 만 있고 axis_values_json 은 NULL (과거 데이터)
    db.add(M.Option(canonical_sku="OLD-1", model_code="MM",
                    color_code="스카이블루", size_code="220",
                    axis_values_json=None, is_active=True))
    db.commit()

    # '조합 생성' 다시 — 같은 (스카이블루,220) → 중복 생성 0 이어야 함
    res = create_combination_options(db, "MM", _STEPS,
                                     selected=[["스카이블루", "220"]])
    db.commit()
    assert res["created"] == 0, "이미 있는 (색·사이즈)는 다시 만들면 안 됨"
    cnt = (db.query(M.Option)
           .filter_by(model_code="MM", color_code="스카이블루", size_code="220").count())
    assert cnt == 1, "중복 행이 생기면 안 됨"


def test_new_combo_still_created(db):
    # 대조군: 없는 조합은 정상 생성
    res = create_combination_options(db, "MM", _STEPS,
                                     selected=[["스카이블루", "220"]])
    db.commit()
    assert res["created"] == 1
    assert db.query(M.Option).filter_by(model_code="MM").count() == 1
