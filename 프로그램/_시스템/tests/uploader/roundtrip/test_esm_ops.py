# -*- coding: utf-8 -*-
"""옥션·G마켓(ESM) 5축 왕복 어댑터.

지도 근거 — `auction.esm.20` / `gmarket.esm.20` (st=ok · 라이브검증):
    등록 [POST] /item/v1/goods · **수정 [PUT] /item/v1/goods/{goodsNo}** · 조회 [GET] 같은 경로
    상품명   itemBasicInfo.goodsName.kor
    가격     itemAddtionalInfo.price.Iac(옥션) / .Gmkt(G마켓)
    재고     itemAddtionalInfo.stock.Iac / .Gmkt
    이미지   itemAddtionalInfo.images.basicImgURL + addtionalImg1URL~14URL
    상세     itemAddtionalInfo.descriptions.kor.html
    판매상태 isSell.iac / isSell.gmkt  ← **수정 API 호출 시 필수**

🔴 idTrap (지도 원문): `isEditableGoodsName` 이 false 면
   「상품명 수정해서 입력시 처리되지 않으며 **별도 에러 처리 없음**」
   = 200 인데 안 바뀐다. 보내기 전에 조회로 알 수 있으므로 아예 안 보낸다.
"""
from __future__ import annotations

import copy

import pytest

from lemouton.uploader.roundtrip.markets.esm import make_esm_ops, resolve_master_goods_no


def _goods(*, name="원래이름", price=10000, stock=5, html="<p>원래</p>",
           images=("http://img/rep.jpg", "http://img/a.jpg"),
           editable_name=True, is_sell=False, market="auction"):
    site = "iac" if market == "auction" else "gmkt"
    imgs = {"basicImgURL": images[0]}
    for i, u in enumerate(images[1:], start=1):
        imgs[f"addtionalImg{i}URL"] = u
    return {
        "goodsNo": "G1",
        "isEditableGoodsName": editable_name,
        "isSell": {site: is_sell},
        "itemBasicInfo": {"goodsName": {"kor": name}},
        "itemAddtionalInfo": {
            "price": {"Iac" if market == "auction" else "Gmkt": price},
            "stock": {"Iac" if market == "auction" else "Gmkt": stock},
            "images": imgs,
            "descriptions": {"kor": {"type": 2, "html": html}},
        },
    }


class FakeEsmClient:
    def __init__(self, goods=None):
        self.goods = goods or _goods()
        self.puts = []
        self._cfg = {"paths": {"detail": "/item/v1/goods/{goodsNo}",
                               "update": "/item/v1/goods/{goodsNo}"}}

    def request(self, *, method, path, body=None, **kw):
        if method == "GET":
            return copy.deepcopy(self.goods)
        if method == "PUT":
            self.puts.append(copy.deepcopy(body))
            self.goods = copy.deepcopy(body)
            return {"goodsNo": "G1", "resultCode": 0}
        raise AssertionError(f"{method} {path}")


def _ops(client, market="auction"):
    return make_esm_ops("G1", market=market, client=client)


# ── 되읽기 ───────────────────────────────────────────────────────────────────
def test_되읽기가_다섯_축을_모두_준다():
    s = _ops(FakeEsmClient()).snapshot()

    assert s.name == "원래이름"
    assert s.sale_price == 10000
    assert s.value_of("stock") == 5
    assert s.detail_html == "<p>원래</p>"
    assert s.image_urls == ("http://img/rep.jpg", "http://img/a.jpg")
    assert s.missing == ()


def test_옥션과_G마켓은_서로_다른_칸을_읽는다():
    """옥션 값을 G마켓 자리에서 읽으면 남의 사이트 값을 쓰게 된다."""
    g = _goods(market="gmarket", price=7777, stock=3)

    s = _ops(FakeEsmClient(g), market="gmarket").snapshot()

    assert s.sale_price == 7777
    assert s.value_of("stock") == 3


def test_판매중이면_판매중으로_알린다():
    on = _ops(FakeEsmClient(_goods(is_sell=True)))
    off = _ops(FakeEsmClient(_goods(is_sell=False)))

    assert on.on_sale() is True
    assert off.on_sale() is False


# ── 🔴 상품명 수정 불가 함정 ─────────────────────────────────────────────────
def test_상품명_수정불가_상품은_상품명을_확인불가로_남긴다():
    """isEditableGoodsName=false 면 보내도 조용히 무시된다 — 아예 안 보낸다."""
    s = _ops(FakeEsmClient(_goods(editable_name=False))).snapshot()

    assert "name" in s.missing
    assert s.has("name") is False


def test_상품명_수정불가인데_보내려_하면_거부한다():
    cli = FakeEsmClient(_goods(editable_name=False))

    with pytest.raises(RuntimeError, match="상품명"):
        _ops(cli).apply({"name": "새이름"})

    assert cli.puts == [], "거부했는데 PUT 이 나갔다"


# ── 쓰기 ─────────────────────────────────────────────────────────────────────
def test_다섯_축_전부_한_번에_쓴다():
    cli = FakeEsmClient()

    _ops(cli).apply({"sale_price": 11000, "stock": 7, "name": "새이름",
                     "detail_html": "<p>새</p>",
                     "image_urls": ("http://img/x.jpg", "http://img/y.jpg")})

    b = cli.puts[-1]
    assert b["itemBasicInfo"]["goodsName"]["kor"] == "새이름"
    assert b["itemAddtionalInfo"]["price"]["Iac"] == 11000
    assert b["itemAddtionalInfo"]["stock"]["Iac"] == 7
    assert b["itemAddtionalInfo"]["descriptions"]["kor"]["html"] == "<p>새</p>"
    assert b["itemAddtionalInfo"]["images"]["basicImgURL"] == "http://img/x.jpg"
    assert b["itemAddtionalInfo"]["images"]["addtionalImg1URL"] == "http://img/y.jpg"
    assert len(cli.puts) == 1


def test_판매상태를_반드시_실어_보낸다():
    """지도: isSell 은 「상품수정 API 호출 시 필수 설정」. 빠지면 거부되거나
    엉뚱한 상태가 된다 — 조회한 현재 상태를 그대로 실어 보낸다."""
    cli = FakeEsmClient(_goods(is_sell=False))

    _ops(cli).apply({"sale_price": 11000})

    assert cli.puts[-1]["isSell"]["iac"] is False, "판매중지 상품이 판매중으로 켜졌다"


def test_이미지가_줄면_남은_추가이미지_칸을_지운다():
    """옛 칸이 남으면 원복했다고 믿는데 사진이 한 장 더 붙어 있다."""
    cli = FakeEsmClient(_goods(images=("http://img/rep.jpg", "http://img/a.jpg",
                                       "http://img/b.jpg")))

    _ops(cli).apply({"image_urls": ("http://img/only.jpg",)})

    imgs = cli.puts[-1]["itemAddtionalInfo"]["images"]
    assert imgs["basicImgURL"] == "http://img/only.jpg"
    assert "addtionalImg1URL" not in imgs
    assert "addtionalImg2URL" not in imgs


def test_쓰고_되읽으면_바뀐_값이_나온다():
    ops = _ops(FakeEsmClient())

    ops.apply({"name": "새이름", "stock": 7})

    s = ops.snapshot()
    assert s.name == "새이름"
    assert s.value_of("stock") == 7


# ── 상품번호 해석 — 마스터 goodsNo 를 줘도 되어야 한다 ───────────────────────
def test_마스터번호를_주면_변환하지_않고_그대로_쓴다():
    """🔴 [2026-08-06 라이브] 후보 조회는 **마스터 goodsNo** 를 준다. 그걸 다시
    site-goods 변환에 넣으면 400 「사이트 상품 번호가 잘 못 되었습니다」로 죽는다.
    변환이 실패하면 입력값을 마스터로 보고 넘어가야 한다(상세조회가 진짜 판별)."""
    from lemouton.uploader.roundtrip.markets.esm import resolve_master_goods_no

    class Boom:
        _cfg = {"paths": {"site_goods_map": "/site-goods/{siteGoodsNo}/goods-no"}}

        def request(self, **kw):
            raise RuntimeError("사이트 상품 번호가 잘 못 되었습니다.")

    assert resolve_master_goods_no("6390703083", client=Boom()) == "6390703083"


def test_사이트번호를_주면_마스터로_바꿔_쓴다():
    class Mapper:
        _cfg = {"paths": {"site_goods_map": "/site-goods/{siteGoodsNo}/goods-no"}}

        def request(self, **kw):
            return {"goodsNo": "G-MASTER"}

    assert resolve_master_goods_no("SITE-1", client=Mapper()) == "G-MASTER"
