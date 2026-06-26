# -*- coding: utf-8 -*-
"""[TEST] 확장 크롤 결과 — 신규 등록 URL 의 SourceProduct 자동 생성.

배경(신규 소싱처/URL 매트릭스 미반영, 2026-06-26):
  사용자가 소싱처 URL 을 새로 등록(예: '르무통 공홈(1) 단품')하고 크롬 확장으로
  크롤하면 위젯엔 '완료'가 떠도 매트릭스/셀엔 '크롤링 미실시'로 남았다.
  원인 = 등록(api_add_source_url)은 BundleSourceUrl 만 만들고 SourceProduct 는
  안 만든다. 서버사이드 전체크롤은 upsert 후 긁지만, 확장 크롤 저장 경로
  save_crawl_result 는 '기존' SourceProduct 만 갱신하고 없으면 not_found 로
  조용히 버렸다(무결성 §4 '누락에 경고' 위반). 그래서 매트릭스가 SourceProduct
  를 URL 로 못 찾아 '크롤링 미실시'.

  수정: 들어온 크롤 URL 이 '등록된 BundleSourceUrl' 이면 source_key 로
  SourceProduct 를 생성(upsert)한 뒤 가격/재고 저장. 등록 안 된 URL 은 그대로
  not_found(쓰레기 행 생성 금지).

이 테스트가 '신규 등록 URL 의 확장 크롤 결과 영속'을 영구 잠근다.
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


NEW_URL = "https://www.lemouton.co.kr/product/detail.html?product_no=1234"


@pytest.fixture
def env():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)

    # 시드: Model + Option + BundleSourceUrl(신규 등록 URL, SourceProduct 없음)
    seed = Session(eng)
    seed.add(M.Model(model_code="LT", model_name_raw="르무통테스트"))
    seed.add(M.Option(canonical_sku="LT-블랙-260", model_code="LT",
                      color_code="블랙", size_code="260", is_active=True))
    bsu = M.BundleSourceUrl(model_code="LT", source_key="lemouton",
                            url=NEW_URL, sort_order=0, url_type="단품")
    seed.add(bsu)
    seed.commit()
    seed.close()

    import webapp.routes.api_pricing as _mod
    from unittest.mock import patch

    app = Flask(__name__)
    app.register_blueprint(_mod.bp)
    app.config.update(TESTING=True)

    # 라우트는 SessionLocal() 을 1회 열고 finally 에서 close 한다.
    #   매 호출마다 같은 engine 의 새 세션을 주면, 라우트가 닫아도 데이터(commit)는
    #   engine 에 남아 테스트가 별도 세션으로 검증할 수 있다.
    with patch.object(_mod, "SessionLocal", side_effect=lambda: Session(eng)):
        yield app.test_client(), eng


def _sp_for(eng, url):
    s = Session(eng)
    try:
        return (s.query(SourceProduct)
                .filter_by(url=normalize_url(url), deleted_at=None).first())
    finally:
        s.close()


def test_new_registered_url_creates_source_product(env):
    """등록된 신규 URL 의 확장 크롤 결과 → SourceProduct 생성 + 가격/재고 저장."""
    client, eng = env

    # 크롤 전: SourceProduct 없음
    assert _sp_for(eng, NEW_URL) is None

    r = client.post("/api/sources/crawl-result", json={"items": [
        {"url": NEW_URL, "price": 116900, "stock": 8, "status": "ok",
         "product_name": "르무통 메이트 블랙"},
    ]})
    assert r.status_code == 200, r.get_data(as_text=True)
    d = r.get_json()
    assert d["ok"] is True
    assert d["updated"] == 1, f"updated 가 1이 아님: {d}"
    assert d["not_found"] == [], f"등록 URL 인데 not_found 로 버려짐: {d}"

    # 크롤 후: SourceProduct 가 생기고 가격/재고가 저장됨
    sp = _sp_for(eng, NEW_URL)
    assert sp is not None, "신규 등록 URL 의 SourceProduct 가 생성되지 않음 (조용한 드롭)"
    assert sp.site == "lemouton"
    assert sp.last_price == 116900
    assert sp.last_stock == 8
    assert sp.last_status == "ok"


def test_unregistered_url_stays_not_found(env):
    """등록 안 된 URL 은 SourceProduct 를 만들지 않고 not_found 로 표면화(쓰레기 행 금지)."""
    client, eng = env
    GHOST = "https://www.lemouton.co.kr/product/detail.html?product_no=99999"

    r = client.post("/api/sources/crawl-result", json={"items": [
        {"url": GHOST, "price": 50000, "stock": 1, "status": "ok"},
    ]})
    assert r.status_code == 200
    d = r.get_json()
    assert d["updated"] == 0
    assert len(d["not_found"]) == 1
    assert _sp_for(eng, GHOST) is None, "등록 안 된 URL 인데 SourceProduct 가 생성됨"
