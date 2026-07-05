# -*- coding: utf-8 -*-
"""[TEST] 확장 크롤 결과 저장 = 이번 가중 랩 served +1.

연속 모드 가중 라운드로빈의 진행 신호. save_crawl_result 가 URL 을 저장(크롤 완료)
할 때마다 crawl_lap_count 를 +1 해야 계수만큼 채우고 랩이 진행된다. 이게 없으면
카운터가 안 늘어 매 폴링이 전체 랩 = 계수 배수 무력(연속모드 원래 버그).
"""
import os
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
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
from lemouton.sources.models import SourceProduct
from lemouton.sources.service import normalize_url
from shared.db import Base

URL = "https://www.lemouton.co.kr/product/detail.html?product_no=555"


@pytest.fixture
def env():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    seed = Session(eng)
    seed.add(M.Model(model_code="LP", model_name_raw="랩테스트"))
    seed.add(M.BundleSourceUrl(model_code="LP", source_key="lemouton",
                               url=URL, sort_order=0, url_type="단품"))
    # SourceProduct 미리 생성(lap_count 0)
    seed.add(SourceProduct(site="lemouton", url=normalize_url(URL),
                           crawl_lap_count=0))
    seed.commit(); seed.close()

    import webapp.routes.api_pricing as _mod
    from unittest.mock import patch
    app = Flask(__name__)
    app.register_blueprint(_mod.bp)
    app.config.update(TESTING=True)
    with patch.object(_mod, "SessionLocal", side_effect=lambda: Session(eng)):
        yield app.test_client(), eng


def _lap(eng):
    s = Session(eng)
    try:
        sp = s.query(SourceProduct).filter_by(url=normalize_url(URL)).first()
        return sp.crawl_lap_count
    finally:
        s.close()


def test_each_crawl_result_increments_lap_count(env):
    client, eng = env
    assert _lap(eng) == 0
    for expect in (1, 2, 3):
        r = client.post("/api/sources/crawl-result", json={"items": [
            {"url": URL, "price": 100000, "stock": 5, "status": "ok"},
        ]})
        assert r.status_code == 200, r.get_data(as_text=True)
        assert _lap(eng) == expect, f"크롤 {expect}회 후 lap_count 가 {expect} 이어야"
