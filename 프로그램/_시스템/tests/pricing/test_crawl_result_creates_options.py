# -*- coding: utf-8 -*-
"""[TEST] 확장추출 경로(crawl-result)도 색·사이즈별 SourceOption 을 '생성' 영속.

배경(무신사 한정수량 재고, 2026-06-26):
  무신사·롯데온은 navGrab→parse 가 아니라 확장 client 추출 → crawl-result 경로.
  기존 _persist_option_stocks 는 '기존' SO 만 갱신(생성 안 함) + ext_bridge 가
  options[] 를 전송 안 해, 신규 URL 은 사이즈별 재고가 영속 안 돼 매트릭스가
  상품 last_stock(합계)을 균일 폴백(한정수량 사이즈도 '있음' 둔갑).

  수정: ① ext_bridge 가 options[] 전송 ② crawl-result 가 persist_crawled_options
  (parse·_ingest 와 같은 단일 루틴)로 색·사이즈별 SO 를 생성(upsert).
  확장추출 옵션 키는 color/size(파서는 color_text/size_text) — 둘 다 허용.

이 테스트가 'crawl-result 가 options[]→SourceOption 생성'을 영구 잠근다.
"""
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
from shared.db import Base

URL = "https://www.musinsa.com/products/123456"


@pytest.fixture
def env():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    seed = Session(eng)
    seed.add(M.Model(model_code="MU", model_name_raw="무신사테스트"))
    seed.commit()
    bsu = M.BundleSourceUrl(model_code="MU", source_key="musinsa",
                            url=URL, sort_order=0, url_type="색상모음전")
    seed.add(bsu)
    seed.commit()
    seed.close()

    import webapp.routes.api_pricing as _mod
    app = Flask(__name__)
    app.register_blueprint(_mod.bp)
    app.config.update(TESTING=True)
    with patch.object(_mod, "SessionLocal", side_effect=lambda: Session(eng)):
        yield app.test_client(), eng


def _so(eng, color, size):
    # upsert_source_option 이 size 를 '260mm' 로 정규화(_norm_size) — 매트릭스는 숫자로 매칭.
    q = Session(eng)
    try:
        return (q.query(SourceOption)
                .filter_by(color_text=color, size_text=f"{size}mm", deleted_at=None).first())
    finally:
        q.close()


def test_crawl_result_creates_persize_options_color_size_keys(env):
    """무신사식 options(color/size 키) → 색·사이즈별 SourceOption 생성, 품절(0) 영속."""
    client, eng = env
    r = client.post("/api/sources/crawl-result", json={"items": [{
        "url": URL, "price": 89000, "stock": 999, "status": "ok",
        "product_name": "무신사 운동화",
        "options": [
            {"color": "블랙", "size": "260", "stock": 3, "price": 89000},
            {"color": "블랙", "size": "265", "stock": 0, "price": 89000},   # 품절
            {"color": "화이트", "size": "260", "stock": 12, "price": 89000},
        ],
    }]})
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()["updated"] == 1

    # SourceProduct + 색·사이즈별 SourceOption 생성
    assert Session(eng).query(SourceProduct).filter_by(site="musinsa").count() == 1
    assert _so(eng, "블랙", "260").current_stock == 3
    assert _so(eng, "블랙", "265").current_stock == 0, "한정수량/품절 265 가 영속 안 됨"
    assert _so(eng, "화이트", "260").current_stock == 12


def test_crawl_result_no_options_is_noop(env):
    """options 없는 소싱처(롯데온 등) → SO 생성 안 함(기존 동작 보존, 예외 없음)."""
    client, eng = env
    r = client.post("/api/sources/crawl-result", json={"items": [{
        "url": URL, "price": 89000, "stock": 999, "status": "ok",
        "product_name": "롯데온식(옵션없음)",
    }]})
    assert r.status_code == 200
    assert r.get_json()["updated"] == 1
    assert Session(eng).query(SourceOption).count() == 0  # 옵션행 생성 안 함
