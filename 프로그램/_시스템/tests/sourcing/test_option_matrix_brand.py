# -*- coding: utf-8 -*-
"""[TEST] option-matrix payload 에 옵션별 브랜드 노출.

매트릭스가 옵션 행에 브랜드 배지를 그리려면 백엔드가 각 옵션에
brand(자체) + effective_brand(상속 반영) 를 내려줘야 한다.
"""
import os
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

os.environ.setdefault("ENVIRONMENT", "test")

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
from shared.db import Base


def _make_db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    return Session(eng)


def _entry(result, sku):
    return next((o for o in result.get("options", []) if o.get("sku") == sku), None)


def _run(s, code="BM"):
    from webapp.routes import api_pricing as _mod
    from unittest.mock import patch
    with patch.object(_mod, "SessionLocal", return_value=s):
        return _mod._option_matrix_data(code)


def test_option_entry_exposes_own_and_effective_brand():
    s = _make_db()
    s.add(M.Model(model_code="BM", model_name_raw="브랜드테스트", brand="르무통"))
    s.add(M.Option(canonical_sku="BM-블랙-260", model_code="BM",
                   color_code="블랙", size_code="260", brand="나이키"))
    s.add(M.Option(canonical_sku="BM-화이트-270", model_code="BM",
                   color_code="화이트", size_code="270", brand=None))
    s.commit()

    result = _run(s)
    assert result.get("ok"), f"API failed: {result}"

    e1 = _entry(result, "BM-블랙-260")
    assert e1["brand"] == "나이키"
    assert e1["effective_brand"] == "나이키"

    e2 = _entry(result, "BM-화이트-270")
    assert e2["brand"] is None                 # 자체는 미지정
    assert e2["effective_brand"] == "르무통"   # 모델 상속


def test_effective_brand_none_when_model_blank():
    s = _make_db()
    s.add(M.Model(model_code="BM", model_name_raw="미지정모델", brand=""))
    s.add(M.Option(canonical_sku="BM-블랙-260", model_code="BM",
                   color_code="블랙", size_code="260", brand=None))
    s.commit()

    e = _entry(_run(s), "BM-블랙-260")
    assert e["brand"] is None
    assert e["effective_brand"] is None
