# -*- coding: utf-8 -*-
"""[M4-4] 크롤 결과의 이미지 URL·상세 HTML 저장 + 무(無)스톰프.

배경 — 6마켓 전부 대표 이미지가 필수, 옥션·G마켓·11번가·롯데온 4마켓은 상세 HTML 도
필수다(`lemouton/registration/compile_more.py`). 크롤이 이 둘을 실어 오면
`SourceProduct.images_json` / `.detail_html` 에 저장한다.

★ **무스톰프가 핵심이다.** 이미지·상세를 안 실은 크롤(구버전 확장, 파싱 실패, 로그인
  만료 등)이 이미 확보한 값을 지워 버리면 그 상품은 **등록 자체가 막힌다**.
  빈 값 = '이번엔 못 뽑았다'이지 '없다'가 아니다 → 기존값 보존.

★ 지식재산권 — 저장하는 건 **URL 문자열**뿐이다. 파일은 받지 않고, 마켓 업로드는
  브랜드별 지재권 제외 정책 통과 후 별도 단계에서 한다.
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
from lemouton.sources.models import SourceProduct
from lemouton.sources.service import upsert_source_product
from shared.db import Base

SSF_URL = "https://www.ssfshop.com/LEMOUTON/GM0024031234567/good"
IMGS = ["https://img.ssfshop.com/cmd/LB_500x500/a.jpg",
        "https://img.ssfshop.com/cmd/LB_500x500/b.jpg"]
# ⚠️ [2026-07-23 리뷰지적 I4] 수신 경계에서 `sanitize_detail_html` 을 **다시** 태우므로
#    이 상수는 정제기의 정본 표기(void 태그 `<img …/>`)로 맞춰 둔다. 재정제는 멱등이라
#    이미 정제된 값은 글자 하나 안 바뀐다 — 아래 `==` 비교가 그 멱등성까지 잠근다.
DETAIL = '<div class="detail"><p>소재: 스웨이드</p><img src="https://img.x/d1.jpg"/></div>'


@pytest.fixture
def env():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    seed = Session(eng)
    seed.add(M.Model(model_code="SF", model_name_raw="SSF테스트"))
    seed.commit()
    upsert_source_product(seed, site="ssf", url=SSF_URL)
    seed.commit()
    seed.close()

    import webapp.routes.api_pricing as _mod
    app = Flask(__name__)
    app.register_blueprint(_mod.bp)
    app.config.update(TESTING=True)
    with patch.object(_mod, "SessionLocal", side_effect=lambda: Session(eng)):
        yield app.test_client(), eng


def _post(client, **item_extra):
    item = {"url": SSF_URL, "price": 100000, "stock": 5, "status": "ok",
            "product_name": "SSF 상품",
            "options": [{"color": "블랙", "size": "260", "stock": 5, "price": 100000}]}
    item.update(item_extra)
    return client.post("/api/sources/crawl-result", json={"items": [item]})


def _sp(eng):
    q = Session(eng)
    try:
        return q.query(SourceProduct).filter_by(site="ssf").first()
    finally:
        q.close()


def test_이미지목록과_상세html_이_저장된다(env):
    client, eng = env
    r = _post(client, image_urls=IMGS, detail_html=DETAIL)
    assert r.status_code == 200, r.get_data(as_text=True)
    sp = _sp(eng)
    assert json.loads(sp.images_json) == IMGS
    assert sp.detail_html == DETAIL


def test_이미지없는_크롤이_기존_이미지를_지우지_않는다(env):
    """[무스톰프 핀] 지워지면 그 상품은 6마켓 어디에도 등록 못 한다."""
    client, eng = env
    _post(client, image_urls=IMGS, detail_html=DETAIL)
    r = _post(client)                       # 구버전 payload — 이미지·상세 키 없음
    assert r.status_code == 200, r.get_data(as_text=True)
    sp = _sp(eng)
    assert json.loads(sp.images_json) == IMGS, "이미지가 크롤 한 번에 소실(스톰프)"
    assert sp.detail_html == DETAIL, "상세 HTML 이 크롤 한 번에 소실(스톰프)"


def test_빈_이미지목록_빈_상세는_기존값을_덮지_않는다(env):
    """빈 값 = '이번엔 못 뽑았다'. '없다'로 확정해 지우지 않는다."""
    client, eng = env
    _post(client, image_urls=IMGS, detail_html=DETAIL)
    r = _post(client, image_urls=[], detail_html="   ")
    assert r.status_code == 200, r.get_data(as_text=True)
    sp = _sp(eng)
    assert json.loads(sp.images_json) == IMGS
    assert sp.detail_html == DETAIL


def test_새_이미지목록은_기존값을_갱신한다(env):
    """보존은 '빈 값일 때'만이다. 실값이 오면 최신으로 갱신돼야 한다."""
    client, eng = env
    _post(client, image_urls=IMGS)
    fresh = ["https://img.ssfshop.com/cmd/LB_500x500/z.jpg"]
    _post(client, image_urls=fresh)
    assert json.loads(_sp(env[1]).images_json) == fresh


def test_이미지목록의_빈문자열_원소는_버린다(env):
    client, eng = env
    _post(client, image_urls=["", "  ", IMGS[0], None])
    assert json.loads(_sp(eng).images_json) == [IMGS[0]]
