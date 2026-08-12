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
    #: 옵션 API(esm.26) 응답. `optSeq` 가 재고 전용 API 가 요구하는 **진짜 열쇠**다
    #: — 이걸 안 읽고 이름을 지어냈다가 라이브에서 재고가 통째로 실패했다(2026-08-08).
    def __init__(self, goods=None, *, options=True):
        self.goods = goods or _goods()
        self.puts = []
        qty = dict((self.goods.get("itemAddtionalInfo") or {}).get("stock") or {})
        self.options_envelope = {
            "type": "RECOMMEND", "isStockManage": True,
            "independent": {"details": [{"optSeq": 77, "qty": qty}]},
        } if options else {"type": "NONE", "independent": {"details": []}}
        self._cfg = {"paths": {"detail": "/item/v1/goods/{goodsNo}",
                               "update": "/item/v1/goods/{goodsNo}",
                               "options": "/item/v1/goods/{goodsNo}/recommended-options",
                               "stock_change": "/item/v1/goods/{goodsNo}/stock"}}

    def request(self, *, method, path, body=None, **kw):
        if method == "GET":
            if path.endswith("recommended-options"):
                return copy.deepcopy(self.options_envelope)
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
    # 상품명은 **읽히지만** 기본으로 시험 대상에서 빠진다(2026-08-07 사고 — 아래 시험 참조).
    assert s.missing == ("name",)


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
def test_무거운_세_축은_한_번에_쓴다():
    cli = FakeEsmClient()

    ops = make_esm_ops("G1", market="auction", client=cli, allow_name=True)
    ops.apply({"name": "새이름", "detail_html": "<p>새</p>",
               "image_urls": ("http://img/x.jpg", "http://img/y.jpg")})

    b = cli.puts[-1]
    assert b["itemBasicInfo"]["goodsName"]["kor"] == "새이름"
    assert b["itemAddtionalInfo"]["descriptions"]["kor"]["html"] == "<p>새</p>"
    assert b["itemAddtionalInfo"]["images"]["basicImgURL"] == "http://img/x.jpg"
    assert b["itemAddtionalInfo"]["images"]["addtionalImg1URL"] == "http://img/y.jpg"
    assert len(cli.puts) == 1


def test_판매상태를_반드시_실어_보낸다():
    """지도: isSell 은 「상품수정 API 호출 시 필수 설정」. 빠지면 거부되거나
    엉뚱한 상태가 된다 — 조회한 현재 상태를 그대로 실어 보낸다."""
    cli = FakeEsmClient(_goods(is_sell=False))

    _ops(cli).apply({"detail_html": "<p>새</p>"})

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

    ops = make_esm_ops("G1", market="auction", client=FakeEsmClient(), allow_name=True)
    ops.apply({"name": "새이름"})

    assert ops.snapshot().name == "새이름"


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


# ── 400 본문을 반드시 건져 올린다 ────────────────────────────────────────────
def test_400_이면_마켓이_준_사유를_그대로_올린다():
    """🔴 [지도 이력 esm-register-400-triple] 「400 본문(resultCode 1000 message)이
    진짜 스펙이다. raise_for_status 로 본문을 버리면 스펙 발굴이 불가능해진다.」

    라이브에서 실제로 겪었다 — 옥션 왕복이 400 인데 사유가 안 보여 원인을 못 찾았다.
    """
    import requests

    class Rejecting:
        _cfg = {"paths": {"detail": "/g/{goodsNo}", "update": "/g/{goodsNo}"}}

        def request(self, *, method, path, body=None, **kw):
            if method == "GET":
                return _goods()
            resp = requests.Response()
            resp.status_code = 400
            resp._content = ('{"resultCode":1000,"message":"판매기간을 확인해 주세요."}'
                             ).encode("utf-8")
            raise requests.HTTPError("400 Client Error", response=resp)

    with pytest.raises(RuntimeError, match="판매기간을 확인해 주세요"):
        make_esm_ops("G1", market="auction", client=Rejecting()).apply({"detail_html": "<p>x</p>"})


def test_본문이_없으면_원래_예외를_그대로_올린다():
    """사유를 못 얻었다고 조용히 삼키면 안 된다."""
    class Broken:
        _cfg = {"paths": {"detail": "/g/{goodsNo}", "update": "/g/{goodsNo}"}}

        def request(self, *, method, path, body=None, **kw):
            if method == "GET":
                return _goods()
            raise RuntimeError("연결 끊김")

    with pytest.raises(RuntimeError, match="연결 끊김"):
        make_esm_ops("G1", market="auction", client=Broken()).apply({"detail_html": "<p>x</p>"})


# ── 🔴 판매기간 — 조회값을 그대로 되돌려 보내면 400 ──────────────────────────
def test_판매기간은_0_기존유지_으로_보낸다():
    """🔴 [2026-08-06 라이브] 옥션 수정이 400.
       resultCode=1000 "[IAC] 판매기간은 -1(무제한), 0, 15, 30, 60, 90만 가능합니다."

    지도 원문(esm.20 sellingPeriod): 「입력 가능 기간 : -1(무제한), 15, 30, 60, 90.
    **수정시 0 입력 경우 기존 기간 유지.** **조회 API 경우 남은 판매 기간 확인 가능**」

    → 조회는 '남은 일수'(예: 37)를 주고 수정은 그 값을 안 받는다.
      GET→PUT 왕복에서 조회값을 그대로 되돌리면 반드시 400.
      0 을 넣으면 **기존 기간이 그대로 유지**된다 — 상품 설정을 안 바꾸는 유일한 답.
    """
    g = _goods()
    g["itemAddtionalInfo"]["sellingPeriod"] = {"Iac": 37, "Gmkt": 37}
    cli = FakeEsmClient(g)

    _ops(cli).apply({"detail_html": "<p>x</p>"})

    sp = cli.puts[-1]["itemAddtionalInfo"]["sellingPeriod"]
    assert sp["Iac"] == 0, f"조회값을 그대로 보내면 400 난다: {sp}"
    assert sp["Gmkt"] == 0


def test_판매기간_칸이_없으면_만들지_않는다():
    """없는 칸을 지어내면 마켓이 다른 이유로 거부할 수 있다."""
    cli = FakeEsmClient()

    _ops(cli).apply({"detail_html": "<p>x</p>"})

    assert "sellingPeriod" not in cli.puts[-1]["itemAddtionalInfo"]


# ── 🔴 [2026-08-07 사고] 상품수정이 재심사를 유발해 상품이 잠겼다 ────────────
def test_ESM_상품명은_기본으로_시험하지_않는다():
    """🔴 실제 사고: 판매중지 상품에 가격·상품명·상세를 바꿨더니 첫 전송 직후
    마켓이 「지식재산권침해 우려(1250) 노출 제한」으로 상품을 잠갔다.
    원복도 손복구도 거부돼 **되돌릴 수 없는 변경**이 남았다.

    상품명에 브랜드가 들어간 상품은 수정 자체가 재심사 대상이 된다 —
    ESM 은 상품명 축을 기본으로 시험하지 않는다(명시적으로 켤 때만).
    """
    s = _ops(FakeEsmClient()).snapshot()

    assert "name" in s.missing, "상품명은 기본으로 시험 대상에서 빠져야 한다"


def test_상품명을_명시적으로_켜면_시험한다():
    """근거가 생기면 켤 수 있어야 한다 — 영영 막지는 않는다."""
    ops = make_esm_ops("G1", market="auction", client=FakeEsmClient(),
                       allow_name=True)

    assert "name" not in ops.snapshot().missing


# ── 🔴 가격·재고는 **전용 API** 로 (전체 상품수정 PUT 이 재심사를 유발했다) ──
def test_가격은_전용_API_로_보낸다():
    """🔴 [2026-08-07] 전체 상품수정 PUT(esm.20)으로 가격을 바꿨더니 재심사가 돌아
    브랜드 상품이 잠겼다. 지도에 **가격 전용 API** 가 따로 있다 —
    esm.186 `PUT /item/v1/goods/{goodsNo}/price` (esm/prices.update_price 로 배선됨).
    쿠팡과 같은 구조인데 ESM 만 놓쳤다.
    """
    sent = {}

    def fake_price(goods_no, market, price, *, client):
        sent.update(goods_no=goods_no, market=market, price=price)
        class R:
            success = True
            error_message = None
        return R()

    cli = FakeEsmClient()
    ops = make_esm_ops("G1", market="auction", client=cli)
    ops.apply({"sale_price": 11000}, _price_fn=fake_price)

    assert sent == {"goods_no": "G1", "market": "auction", "price": 11000}
    assert cli.puts == [], "가격에 전체 상품수정 PUT 을 쓰면 재심사가 돈다"


def test_재고는_옵션관리_API_로_보낸다():
    """esm.26 `PUT .../recommended-options` (esm/inventory.update_stock 로 배선됨·st=ok)."""
    sent = {}

    def fake_stock(goods_no, market, option_id, stock, *, client):
        sent.update(goods_no=goods_no, market=market, option_id=option_id, stock=stock)
        return True

    cli = FakeEsmClient()
    ops = make_esm_ops("G1", market="auction", client=cli)
    ops.apply({"stock": 7}, _stock_fn=fake_stock)

    assert sent["stock"] == 7 and sent["goods_no"] == "G1"
    assert cli.puts == [], "재고에 전체 상품수정 PUT 을 쓰면 안 된다"


def test_상품명_상세_이미지만_전체수정을_쓴다():
    """이 3축은 전용 API 가 없다 — 전체 PUT 뿐이고, 그래서 재심사 위험이 있다."""
    cli = FakeEsmClient()
    ops = make_esm_ops("G1", market="auction", client=cli, allow_name=True)

    ops.apply({"detail_html": "<p>새</p>"})

    assert len(cli.puts) == 1
    assert cli.puts[0]["itemAddtionalInfo"]["descriptions"]["kor"]["html"] == "<p>새</p>"
