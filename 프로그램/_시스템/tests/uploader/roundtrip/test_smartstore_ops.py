# -*- coding: utf-8 -*-
"""스마트스토어 왕복 어댑터 — 되읽기·쓰기·판매상태를 runner 가 쓸 모양으로 묶는다."""
from __future__ import annotations

import copy

from lemouton.uploader.roundtrip.markets.smartstore import make_smartstore_ops


def _product(name="원래이름", detail="<p>원래</p>", price=10000, status="SUSPENSION",
             images=("http://cdn/rep.jpg", "http://cdn/b.jpg"), stock=3):
    imgs = {"representativeImage": {"url": images[0]},
            "optionalImages": [{"url": u} for u in images[1:]]}
    return {"originProduct": {
        "name": name, "salePrice": price, "statusType": status,
        "detailContent": detail, "images": imgs,
        "detailAttribute": {"optionInfo": {"optionCombinations": [
            {"id": 111, "stockQuantity": stock, "price": 0},
            {"id": 222, "stockQuantity": 9, "price": 1000},
        ]}},
    }}


class FakeClient:
    def __init__(self, product=None):
        self.product = product or _product()
        self.puts = []

    def request(self, method, path, body=None, **kw):
        if method == "GET":
            return copy.deepcopy(self.product)
        if method == "PUT":
            self.puts.append(copy.deepcopy(body))
            self.product = copy.deepcopy(body)      # 진짜 마켓처럼 보관
            return {"originProductNo": 1}
        raise AssertionError(method)


def test_되읽기가_다섯_축을_모두_준다():
    ops = make_smartstore_ops(1, client=FakeClient())

    s = ops.snapshot()

    assert s.name == "원래이름"
    assert s.detail_html == "<p>원래</p>"
    assert s.image_urls == ("http://cdn/rep.jpg", "http://cdn/b.jpg")
    assert s.sale_price == 10000
    assert s.options[0] == ("111", 3, 0)
    assert s.missing == ()


def test_판매중이면_판매중으로_알린다():
    on = make_smartstore_ops(1, client=FakeClient(_product(status="SALE")))
    off = make_smartstore_ops(1, client=FakeClient(_product(status="SUSPENSION")))

    assert on.on_sale() is True
    assert off.on_sale() is False


def test_재고는_첫_옵션에만_쓰고_형제_옵션은_안_건드린다():
    """옵션 하나만 시험한다. 형제 옵션 재고까지 바꾸면 원복 범위가 커진다."""
    cli = FakeClient()
    ops = make_smartstore_ops(1, client=cli)

    ops.apply({"stock": 7})

    combos = cli.puts[-1]["originProduct"]["detailAttribute"]["optionInfo"]["optionCombinations"]
    assert combos[0]["stockQuantity"] == 7
    assert combos[1]["stockQuantity"] == 9, "형제 옵션이 바뀌었다"


def test_다섯_축_전부_한_번에_쓴다():
    cli = FakeClient()
    ops = make_smartstore_ops(1, client=cli)

    ops.apply({"sale_price": 11000, "stock": 7, "name": "새이름",
               "detail_html": "<p>새</p>", "image_urls": ("http://cdn/x.jpg",)})

    o = cli.puts[-1]["originProduct"]
    assert o["salePrice"] == 11000
    assert o["name"] == "새이름"
    assert o["detailContent"] == "<p>새</p>"
    assert o["images"]["representativeImage"]["url"] == "http://cdn/x.jpg"
    assert o["detailAttribute"]["optionInfo"]["optionCombinations"][0]["stockQuantity"] == 7
    assert len(cli.puts) == 1, "축마다 따로 PUT 하면 429 위험 — 한 번에 보내야 한다"


def test_쓰고_되읽으면_바뀐_값이_나온다():
    """어댑터 두 개(쓰기·읽기)가 같은 상품을 보는지 — 왕복이 성립하는 최소 조건."""
    ops = make_smartstore_ops(1, client=FakeClient())

    ops.apply({"name": "새이름", "stock": 7})

    s = ops.snapshot()
    assert s.name == "새이름"
    assert s.options[0][1] == 7
