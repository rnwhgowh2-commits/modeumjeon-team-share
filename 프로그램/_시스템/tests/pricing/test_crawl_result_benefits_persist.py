# -*- coding: utf-8 -*-
"""[TEST] b번(서버 반쪽) — 확장 crawl-result 경로가 혜택 키를 저장.

배경: 확장추출 경로(crawl-result → save_crawl_result → persist_crawled_options)는
  가격·재고만 저장하고 SSG·SSF 등의 동적 혜택 키(ssg_money_rate 등)를 버렸다
  → compute_breakdown 이 계산식에 프로모를 못 띄움([[project_ssg_benefits_never_refreshed_by_live_crawl]]).
  서버사이드 _ingest(service.save_crawl_result)는 이미 저장하나, 확장 경로는 우회.

이 테스트가 '확장 경로도 옵션·상품 레벨 dynamic_benefits_json 을 저장'을 잠근다.
(확장이 그 키를 실어 보내는 것은 별개 — 라이브 검증 필요. 여기선 서버 저장만 검증.)
"""
import json
import os
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from unittest.mock import patch
from flask import Flask

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
from lemouton.sources.models import SourceProduct, SourceOption
from lemouton.sources.service import upsert_source_product
from shared.db import Base

SSG_URL = "https://www.ssg.com/item/itemView.ssg?itemId=1000123"


@pytest.fixture
def env():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    seed = Session(eng)
    seed.add(M.Model(model_code="SG", model_name_raw="SSG테스트"))
    seed.commit()
    # 기존 SourceProduct(site=ssg) — 확장 crawl-result 가 이 행을 갱신
    upsert_source_product(seed, site="ssg", url=SSG_URL)
    seed.commit()
    seed.close()

    import webapp.routes.api_pricing as _mod
    app = Flask(__name__)
    app.register_blueprint(_mod.bp)
    app.config.update(TESTING=True)
    with patch.object(_mod, "SessionLocal", side_effect=lambda: Session(eng)):
        yield app.test_client(), eng


def _post(client, options):
    return client.post("/api/sources/crawl-result", json={"items": [{
        "url": SSG_URL, "price": 100000, "stock": 999, "status": "ok",
        "product_name": "SSG 상품", "options": options,
    }]})


def test_option_level_dynamic_benefits_persisted(env):
    client, eng = env
    r = _post(client, [
        {"color": "블랙", "size": "260", "stock": 5, "price": 100000,
         "ssg_money_rate": 0.05, "ssg_money_text": "5% 적립"},
    ])
    assert r.status_code == 200, r.get_data(as_text=True)
    q = Session(eng)
    try:
        so = (q.query(SourceOption)
              .filter_by(color_text="블랙", size_text="260mm", deleted_at=None).first())
        assert so is not None, "옵션행 생성 실패"
        assert so.dynamic_benefits_json, "옵션 혜택 JSON 이 비어있음(혜택 키 유실)"
        dyn = json.loads(so.dynamic_benefits_json)
        assert dyn.get("ssg_money_rate") == 0.05
        assert dyn.get("ssg_money_text") == "5% 적립"
    finally:
        q.close()


def test_product_level_dynamic_benefits_persisted(env):
    client, eng = env
    r = _post(client, [
        {"color": "블랙", "size": "260", "stock": 5, "price": 100000,
         "ssg_money_rate": 0.05, "ssg_money_text": "5% 적립"},
    ])
    assert r.status_code == 200, r.get_data(as_text=True)
    q = Session(eng)
    try:
        sp = q.query(SourceProduct).filter_by(site="ssg").first()
        assert sp is not None
        assert sp.dynamic_benefits_json, "상품 혜택 JSON 이 비어있음(혜택 키 유실)"
        dyn = json.loads(sp.dynamic_benefits_json)
        assert dyn.get("ssg_money_rate") == 0.05
    finally:
        q.close()


def test_no_benefit_keys_leaves_options_clean(env):
    """혜택 키 없는 payload → 옵션은 생성되되 혜택 JSON 은 비움(폴백·잡음 금지)."""
    client, eng = env
    r = _post(client, [{"color": "화이트", "size": "270", "stock": 3, "price": 100000}])
    assert r.status_code == 200
    q = Session(eng)
    try:
        so = (q.query(SourceOption)
              .filter_by(color_text="화이트", size_text="270mm", deleted_at=None).first())
        assert so is not None
        assert not so.dynamic_benefits_json, "혜택 키 없는데 JSON 이 생김(잡음)"
    finally:
        q.close()
