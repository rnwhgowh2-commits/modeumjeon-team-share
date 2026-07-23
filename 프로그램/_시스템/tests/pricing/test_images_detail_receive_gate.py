# -*- coding: utf-8 -*-
"""[2026-07-23 리뷰지적 I3·I4·I5] 이미지·상세 **수신 경계** — 성공 게이트 + 재정제.

이 파일이 지키는 것 두 가지.

I3 🟠 **크롤 실패(status != 'ok')면 이미지·상세를 덮지 않는다.**
   같은 파일(`api_pricing.py`)의 재고 영속은 2026-07-08 사고 대응으로 이미
   `status == 'ok'` 게이트가 있는데, 이미지·상세만 게이트가 없었다. 무스톰프는
   "빈 값"만 막지 "**틀린 값**"은 못 막는다 — 에러 페이지·롯데온 대체상품 가드가
   **다른 상품 사진**을 실어 오면 그대로 대표이미지가 갈린다(오등록 = 금전·계정 위험).

I4 🟠 **수신 경계에서 다시 정제한다.**
   확장이 원시값(추적픽셀·남의 몰 `<a href>`·스킨 아이콘)을 실어 보내면 종전엔
   DB 를 거쳐 그대로 마켓으로 갔다. 정제기는 서버에 있으니 멱등 재실행 비용이 0 이다.

I5 🟠 **오늘 실제로 저장되는 경로는 `parse` 쪽이다.**
   확장 화이트리스트에 `image_urls`/`detail_html` 키가 없어 crawl-result 경로로는
   아직 안 온다. 그래서 `_persist_images_and_detail`(parse) 에도 같은 핀을 박는다.
"""
import json
import os

import pytest
from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from unittest.mock import patch

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

import lemouton.sourcing.models as M                       # noqa: E402
from lemouton.sources.models import SourceProduct          # noqa: E402
from lemouton.sources.service import upsert_source_product  # noqa: E402
from shared.db import Base                                  # noqa: E402

SSF_URL = "https://www.ssfshop.com/LEMOUTON/GM0024031234567/good"
GOOD_IMGS = ["https://img.ssfshop.com/cmd/LB_750x1000/a.jpg",
             "https://img.ssfshop.com/cmd/LB_750x1000/b.jpg"]
GOOD_DETAIL = '<div class="d"><p>소재: 스웨이드</p><img src="https://img.x/d1.jpg"/></div>'
# 다른 상품 사진 — 실패 크롤이 이걸로 덮으면 오등록이다
WRONG_IMGS = ["https://img.ssfshop.com/cmd/LB_750x1000/OTHER_PRODUCT.jpg"]


@pytest.fixture
def eng():
    e = create_engine("sqlite://")
    Base.metadata.create_all(e)
    seed = Session(e)
    seed.add(M.Model(model_code="SF", model_name_raw="SSF테스트"))
    seed.commit()
    upsert_source_product(seed, site="ssf", url=SSF_URL)
    seed.commit()
    seed.close()
    return e


@pytest.fixture
def client(eng):
    import webapp.routes.api_pricing as _mod
    app = Flask(__name__)
    app.register_blueprint(_mod.bp)
    app.config.update(TESTING=True)
    with patch.object(_mod, "SessionLocal", side_effect=lambda: Session(eng)):
        yield app.test_client()


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


# ═════════════════════════════════════════════════════════════════
# I3 — 실패 크롤은 이미지·상세를 덮지 않는다 (crawl-result 경로)
# ═════════════════════════════════════════════════════════════════
def test_실패크롤은_기존_이미지를_다른상품_사진으로_덮지_않는다(client, eng):
    """🟠 무스톰프는 '빈 값'만 막는다. **틀린 값**을 막는 건 status 게이트뿐이다."""
    _post(client, image_urls=GOOD_IMGS, detail_html=GOOD_DETAIL)
    r = _post(client, status="error", price=None, image_urls=WRONG_IMGS,
              detail_html='<div class="d"><p>일시적인 오류가 발생했습니다</p></div>')
    assert r.status_code == 200, r.get_data(as_text=True)
    sp = _sp(eng)
    assert json.loads(sp.images_json) == GOOD_IMGS, "실패 크롤이 대표이미지를 갈아치웠다"
    assert '소재: 스웨이드' in sp.detail_html, "실패 크롤이 상세를 에러문구로 덮었다"


def test_성공크롤은_당연히_갱신한다(client, eng):
    """게이트를 건다고 정상 갱신까지 막으면 안 된다(회귀 핀)."""
    _post(client, image_urls=GOOD_IMGS)
    fresh = ["https://img.ssfshop.com/cmd/LB_750x1000/z.jpg"]
    _post(client, image_urls=fresh, status="ok")
    assert json.loads(_sp(eng).images_json) == fresh


# ═════════════════════════════════════════════════════════════════
# I4 — 수신 경계 재정제 (crawl-result 경로)
# ═════════════════════════════════════════════════════════════════
def test_확장이_보낸_남의몰_링크는_수신경계에서_지워진다(client, eng):
    """🔴 확장이 원시 상세를 실어 보내면 종전엔 DB→마켓으로 그대로 갔다.

    정제기는 서버에 있고 멱등이라 재실행 비용이 0 이다.
    """
    _post(client, detail_html=(
        '<div class="d"><p>소재 안내</p>'
        '<a href="https://lemouton.co.kr/product/list.html?cate_no=64">다른 상품</a>'
        '<script>track()</script></div>'))
    got = _sp(eng).detail_html
    assert 'href' not in got and 'lemouton.co.kr/product/list.html' not in got
    assert '<script' not in got
    assert '소재 안내' in got and '다른 상품' in got


def test_확장이_보낸_추적픽셀은_수신경계에서_지워진다(client, eng):
    _post(client, detail_html=(
        '<div class="d"><p>소재</p>'
        '<img src="//log.ssfshop.com/px.gif?pid=1" width="1" height="1">'
        '<img src="https://img.x/d1.jpg"></div>'))
    got = _sp(eng).detail_html
    assert 'px.gif' not in got and 'log.ssfshop.com' not in got
    assert 'https://img.x/d1.jpg' in got


def test_확장이_보낸_비상품_이미지는_수신경계에서_걸러진다(client, eng):
    _post(client, image_urls=[
        'https://img.echosting.cafe24.com/thumb/img_product_big.gif',
        'https://x.com/common/blank.gif',
        'https://img.ssfshop.com/cmd/LB_750x1000/a.jpg'])
    assert json.loads(_sp(eng).images_json) == [
        'https://img.ssfshop.com/cmd/LB_750x1000/a.jpg']


def test_재정제후_한장도_안남으면_기존값을_지우지_않는다(client, eng):
    """재정제로 0장이 됐다 = '이번엔 못 건졌다'. 기존값을 지울 근거가 아니다."""
    _post(client, image_urls=GOOD_IMGS)
    _post(client, image_urls=['https://img.echosting.cafe24.com/thumb/img_product_big.gif'])
    assert json.loads(_sp(eng).images_json) == GOOD_IMGS


# ═════════════════════════════════════════════════════════════════
# I5 — 오늘 실제로 저장되는 경로(parse)에도 같은 핀
# ═════════════════════════════════════════════════════════════════
OK_PAYLOAD = {"product_name_raw": "SSF 르무통 메이트",
              "options": [{"color_text": "블랙", "size_text": "260",
                           "stock": 3, "price": 100000}]}
FAIL_PAYLOAD = {"product_name_raw": "", "options": []}


def _parse_persist(eng, payload, image_urls, detail_html):
    import webapp.routes.api_sources_parse as _mod
    with patch.object(_mod, "SessionLocal", side_effect=lambda: Session(eng)):
        _mod._persist_images_and_detail("ssf", SSF_URL, image_urls, detail_html,
                                        payload=payload)


def test_parse경로_이미지와_상세가_저장된다(eng):
    _parse_persist(eng, OK_PAYLOAD, GOOD_IMGS, GOOD_DETAIL)
    sp = _sp(eng)
    assert json.loads(sp.images_json) == GOOD_IMGS
    assert '소재: 스웨이드' in sp.detail_html


def test_parse경로_빈값은_기존값을_지우지_않는다(eng):
    """[무스톰프 핀] 지워지면 그 상품은 6마켓 어디에도 등록 못 한다."""
    _parse_persist(eng, OK_PAYLOAD, GOOD_IMGS, GOOD_DETAIL)
    _parse_persist(eng, OK_PAYLOAD, [], "   ")
    sp = _sp(eng)
    assert json.loads(sp.images_json) == GOOD_IMGS
    assert '소재: 스웨이드' in sp.detail_html


def test_parse경로_실패한_파싱은_이미지를_덮지_않는다(eng):
    """🟠 에러 페이지·대체상품 가드가 **다른 상품 사진**을 실어 오는 경우.

    parse 결과에는 `status` 필드가 없다(파서는 예외로 실패를 알린다). 그래서
    crawl-result 가 쓰는 것과 **같은 근거** — 상품명과 가격이 실제로 잡혔는가 —
    로 성공을 판정한다(`api_pricing.py`: `status = it.get('status') or
    ('ok' if price else 'error')`).
    """
    _parse_persist(eng, OK_PAYLOAD, GOOD_IMGS, GOOD_DETAIL)
    _parse_persist(eng, FAIL_PAYLOAD, WRONG_IMGS, '<div><p>일시적인 오류</p></div>')
    sp = _sp(eng)
    assert json.loads(sp.images_json) == GOOD_IMGS, "실패 파싱이 대표이미지를 갈아치웠다"
    assert '소재: 스웨이드' in sp.detail_html


def test_parse경로_수신값을_다시_정제한다(eng):
    """정제 안 된 값이 확장/파서 어느 쪽에서 오든 DB 에 원시로 남으면 안 된다."""
    _parse_persist(eng, OK_PAYLOAD,
                   ['https://img.echosting.cafe24.com/thumb/img_product_big.gif',
                    'https://img.ssfshop.com/cmd/LB_750x1000/a.jpg'],
                   '<div><p>소재</p><a href="/product/list.html">다른 상품</a>'
                   '<img src="//log.ssfshop.com/px.gif" width="1" height="1"></div>')
    sp = _sp(eng)
    assert json.loads(sp.images_json) == ['https://img.ssfshop.com/cmd/LB_750x1000/a.jpg']
    assert 'href' not in sp.detail_html and 'px.gif' not in sp.detail_html
    assert '다른 상품' in sp.detail_html
