# -*- coding: utf-8 -*-
"""[TEST] crawl-result 가 **증거 없는 옵션가**를 칠하지 못하게 못 박는다 (이슈 #636).

무엇이 있었나 (2026-08-06 라이브 실측)
    돈 무결성 감시기가 며칠째 빨갛고 INV-5 가 285건이었다. 285건 전부
    `source_options.current_price == source_products.last_price` 였고 상품마다
    서로 다른 가격이 **1종뿐**이었다 — 옵션을 읽어서 얻은 값이 아니라 상품 대표가의
    복사본이었다는 뜻이다.

    범인은 crawl-result 의 「옵션단위 표시가 일괄 갱신」이었다. 이 줄에는 문이 하나도
    없어서, 2026-07-31 06:36:59 에 도착한 **단 한 번의** crawl-result(상품 51개·소싱처
    8곳이 같은 마이크로초로 도장됨)가 `options[]` 없이 상품가만 들고 왔는데도 그
    상품들의 **모든 옵션**에 current_price 를 칠했다. 재고는 안 건드리므로(직전
    06:34:50 하드리셋으로 NULL) 「가격은 있는데 재고는 없는」 행이 태어났고,
    옵션 last_fetched_at 도 안 올라가 INV-4 까지 같은 행으로 겹쳐 울렸다.

    데이터 정합성 3대 원칙 ② — 가격은 그 URL 실값으로만. 매칭·크롤 실패 시 대표가
    폴백 금지. 옵션 목록을 보지도 못한 크롤은 그 옵션들의 가격을 말할 자격이 없다.

무엇을 잠그나
    · options[] 없이 온 크롤은 기존 옵션가를 **건드리지 않는다**
    · 실패(status != 'ok') 크롤도 마찬가지
    · options[] 를 들고 온 정상 크롤은 예전처럼 일괄 갱신이 동작한다(회원가·혜택가)
"""
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

import lemouton.sourcing.models as M                      # noqa: E402
from lemouton.sources.models import SourceOption, SourceProduct  # noqa: E402
from shared.db import Base                                 # noqa: E402

URL = "https://www.ssg.com/item/itemView.ssg?itemId=1000123456"
OLD_PRICE = 131000          # 옵션을 실제로 읽어서 넣어 둔 값
PRODUCT_PRICE = 119900      # 크롤이 들고 온 상품 대표가


@pytest.fixture
def env():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    seed = Session(eng)
    seed.add(M.Model(model_code="SG", model_name_raw="SSG테스트"))
    seed.commit()
    seed.add(M.BundleSourceUrl(model_code="SG", source_key="ssg", url=URL,
                               sort_order=0, url_type="색상모음전"))
    sp = SourceProduct(site="ssg", url=URL, last_price=OLD_PRICE)
    seed.add(sp)
    seed.commit()
    seed.add(SourceOption(source_product_id=sp.id, color_text="블랙",
                          size_text="260mm", current_price=OLD_PRICE,
                          current_stock=None))
    seed.commit()
    seed.close()

    import webapp.routes.api_pricing as _mod
    app = Flask(__name__)
    app.register_blueprint(_mod.bp)
    app.config.update(TESTING=True)
    with patch.object(_mod, "SessionLocal", side_effect=lambda: Session(eng)):
        yield app.test_client(), eng


def _only_option(eng):
    q = Session(eng)
    try:
        return q.query(SourceOption).filter_by(deleted_at=None).one()
    finally:
        q.close()


def test_options_없이_온_크롤은_옵션가를_안_칠한다(env):
    """이게 285건을 만든 바로 그 요청 모양이다 — 상품가만 있고 options[] 가 없다."""
    client, eng = env
    r = client.post("/api/sources/crawl-result", json={"items": [{
        "url": URL, "price": PRODUCT_PRICE, "status": "ok",
    }]})
    assert r.status_code == 200, r.get_data(as_text=True)

    so = _only_option(eng)
    assert so.current_price == OLD_PRICE, (
        "옵션을 보지도 못한 크롤이 상품 대표가를 옵션에 칠했다(폴백 가격 — 원칙 ② 위반)")
    assert so.current_stock is None, "재고는 여전히 「확인 불가」여야 한다"

    # 상품 대표가는 갱신된다 — 화면 폴백은 그대로 살아 있어 표시가 비지 않는다.
    q = Session(eng)
    try:
        assert q.query(SourceProduct).one().last_price == PRODUCT_PRICE
    finally:
        q.close()


def test_실패한_크롤은_옵션가를_안_칠한다(env):
    """실패 크롤이 가격을 다시 칠하면 옛값·엉뚱한 값이 현재가로 둔갑한다."""
    client, eng = env
    r = client.post("/api/sources/crawl-result", json={"items": [{
        "url": URL, "price": PRODUCT_PRICE, "status": "error", "error": "WAF 차단",
        "options": [{"color": "블랙", "size": "260", "price": PRODUCT_PRICE}],
    }]})
    assert r.status_code == 200, r.get_data(as_text=True)
    assert _only_option(eng).current_price == OLD_PRICE, "실패 크롤이 옵션가를 덮었다"


def test_options_를_들고_온_정상_크롤은_예전처럼_일괄갱신한다(env):
    """무신사 회원가·롯데온 혜택가는 상품 내 균일 — 그 기능은 죽이면 안 된다."""
    client, eng = env
    r = client.post("/api/sources/crawl-result", json={"items": [{
        "url": URL, "price": PRODUCT_PRICE, "status": "ok",
        "options": [{"color": "블랙", "size": "260", "stock": 4}],
    }]})
    assert r.status_code == 200, r.get_data(as_text=True)

    so = _only_option(eng)
    assert so.current_price == PRODUCT_PRICE, "정상 크롤인데 옵션가 일괄갱신이 안 됐다"
    assert so.current_stock == 4, "옵션 재고가 영속 안 됐다"
