# -*- coding: utf-8 -*-
"""스마트스토어 edit_options — 상품명·상세·이미지까지 쓸 수 있어야 한다.

배경(데이터 코드 지도 확인분):
    `PUT /external/v2/products/origin-products/{no}` (지도 st=ok · 라이브 검증됨) 는
    **originProduct 전체를 다시 보내는** 형식이라, 지금도 name·detailContent·images 가
    본문에 실려 나간다. 우리가 안 바꾸고 받은 값을 그대로 되돌려 보낼 뿐이다.
    → 3축 전송은 새 연동이 아니라 이 함수에 「쓰기」를 더하는 일.

가장 중요한 계약: **새 인자를 안 주면 기존 동작이 1비트도 달라지면 안 된다.**
"""
from __future__ import annotations

import copy

import pytest

from shared.platforms.smartstore.edit_product import edit_options


def _product(name="원래이름", detail="<p>원래상세</p>", price=10000,
             images=("http://cdn/rep.jpg",)):
    imgs = {"representativeImage": {"url": images[0]}}
    if len(images) > 1:
        imgs["optionalImages"] = [{"url": u} for u in images[1:]]
    return {
        "originProduct": {
            "name": name,
            "salePrice": price,
            "statusType": "SUSPENSION",
            "detailContent": detail,
            "images": imgs,
            "detailAttribute": {"optionInfo": {"optionCombinations": [
                {"id": 111, "stockQuantity": 3, "price": 0},
            ]}},
        },
        "smartstoreChannelProduct": {},
    }


class FakeClient:
    """GET 으로 준 것을 PUT 으로 받아 보관 — 무엇이 실제로 나갔는지 검사한다."""

    def __init__(self, product=None):
        self.product = product or _product()
        self.put_body = None

    def request(self, method, path, body=None, **kw):
        if method == "GET":
            return copy.deepcopy(self.product)
        if method == "PUT":
            self.put_body = copy.deepcopy(body)
            return {"originProductNo": 1}
        raise AssertionError(f"예상 못 한 호출: {method} {path}")


def _origin(cli):
    return cli.put_body["originProduct"]


# ── 기존 동작 보존 (가장 중요) ───────────────────────────────────────────────
def test_새_인자를_안_주면_상품명_상세_이미지는_그대로_나간다():
    cli = FakeClient()

    r = edit_options(1, sale_price=12000, option_updates={111: {"stockQuantity": 5}},
                     client=cli)

    assert r.success
    o = _origin(cli)
    assert o["name"] == "원래이름"
    assert o["detailContent"] == "<p>원래상세</p>"
    assert o["images"]["representativeImage"]["url"] == "http://cdn/rep.jpg"
    assert o["salePrice"] == 12000
    assert o["detailAttribute"]["optionInfo"]["optionCombinations"][0]["stockQuantity"] == 5


# ── 새로 되는 것 ─────────────────────────────────────────────────────────────
def test_상품명을_바꿔_보낸다():
    cli = FakeClient()

    edit_options(1, name="새이름", client=cli)

    assert _origin(cli)["name"] == "새이름"


def test_상세페이지를_바꿔_보낸다():
    cli = FakeClient()

    edit_options(1, detail_html="<p>새상세</p>", client=cli)

    assert _origin(cli)["detailContent"] == "<p>새상세</p>"


def test_이미지를_바꿔_보낸다_대표와_추가장():
    cli = FakeClient(_product(images=("http://cdn/rep.jpg", "http://cdn/b.jpg")))

    edit_options(1, image_urls=("http://cdn/new1.jpg", "http://cdn/new2.jpg"),
                 client=cli)

    imgs = _origin(cli)["images"]
    assert imgs["representativeImage"]["url"] == "http://cdn/new1.jpg"
    assert [x["url"] for x in imgs["optionalImages"]] == ["http://cdn/new2.jpg"]


def test_이미지가_한_장이면_추가장_칸을_남기지_않는다():
    """빈 optionalImages 를 보내면 네이버가 400 을 준다 — 아예 지운다."""
    cli = FakeClient(_product(images=("http://cdn/rep.jpg", "http://cdn/b.jpg")))

    edit_options(1, image_urls=("http://cdn/only.jpg",), client=cli)

    imgs = _origin(cli)["images"]
    assert imgs["representativeImage"]["url"] == "http://cdn/only.jpg"
    assert "optionalImages" not in imgs


# ── 안전 ─────────────────────────────────────────────────────────────────────
def test_상품명을_빈값으로는_못_보낸다():
    """빈 상품명이 나가면 마켓에서 이름 없는 상품이 된다 — 되돌리기 전엔 못 판다."""
    cli = FakeClient()

    with pytest.raises(ValueError):
        edit_options(1, name="   ", client=cli)

    assert cli.put_body is None, "거부했는데 PUT 이 나갔다"


def test_이미지를_빈_목록으로는_못_보낸다():
    cli = FakeClient()

    with pytest.raises(ValueError):
        edit_options(1, image_urls=(), client=cli)

    assert cli.put_body is None
