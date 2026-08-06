# -*- coding: utf-8 -*-
"""롯데온 5축 왕복 어댑터.

지도 근거:
  · 조회 POST /v1/openapi/product/v1/product/detail  (lotteon.product.get_detail · st=code)
        확보 필드: data.pdNm(상품명) · data.slStatCd(판매상태) ·
                   data.itmLst[].slPrc(판매가) · .stkQty(재고)
        🔴 `res.note = "전체 스펙 롯데ON apiNo=94"` — **상세 HTML·이미지 필드는 미확보**.
           문서로 모르는 것을 지어내지 않는다. 응답에 실제로 있으면 읽고, 없으면
           「확인불가」로 남긴다(프로브로 실측해 지도에 되채운다).
  · 가격 POST .../item/price/change   (spdNo + sitmNo)
  · 재고 POST .../item/stock/change   (spdNo + sitmNo)
  · 3축  POST .../product/modification/request — 「수정 **요청**」 · st=code(문서만)

재고 함정(기존 코드 관례): stkMgtYn=N(미관리)이면 센티넬 999,999,999 이 온다 —
그대로 노출하면 「재고 10억」이 된다. None(확인불가)으로 둔다.
"""
from __future__ import annotations

import pytest

from lemouton.uploader.roundtrip.markets.lotteon import make_lotteon_ops


def _detail(*, name="원래이름", price=10000, stock=5, status="STP",
            stk_managed="Y", extra=None):
    d = {
        "spdNo": "SPD1",
        "pdNm": name,
        "slStatCd": status,
        "itmLst": [{"sitmNo": "ITM1", "sitmNm": "옵션A", "slPrc": price,
                    "stkQty": stock, "stkMgtYn": stk_managed, "slStatCd": "SALE"}],
    }
    if extra:
        d.update(extra)
    return d


class FakeLotteonClient:
    def __init__(self, detail=None):
        self.detail = detail or _detail()
        self.posts = []
        self._cfg = {"tr_grp_cd": "SR", "tr_no": "T1", "lrtr_no": "",
                     "paths": {"detail": "/detail",
                               "price_change": "/price", "stock_change": "/stock",
                               "product_update": "/modify"}}

    def request(self, *, method, path, body=None, **kw):
        self.posts.append((path, body))
        if path == "/detail":
            return {"returnCode": "0000", "data": dict(self.detail)}
        # ★ 실제 body 모양 — 가격은 itmPrcLst, 재고는 itmStkLst 래퍼.
        #   래퍼가 틀리면 롯데온은 0건 접수를 「정상」이라 답한다(2026-07-21 이력).
        if path == "/price":
            self.detail["itmLst"][0]["slPrc"] = body["itmPrcLst"][0]["slPrc"]
            return {"returnCode": "0000",
                    "data": [{"resultCode": "0000", "sitmNo": "ITM1"}]}
        if path == "/stock":
            self.detail["itmLst"][0]["stkQty"] = body["itmStkLst"][0]["stkQty"]
            return {"returnCode": "0000",
                    "data": [{"resultCode": "0000", "sitmNo": "ITM1"}]}
        if path == "/modify":
            return {"returnCode": "0000"}
        raise AssertionError(path)


def _ops(cli):
    return make_lotteon_ops("SPD1", client=cli)


# ── 되읽기 ───────────────────────────────────────────────────────────────────
def test_확보된_축은_읽는다():
    s = _ops(FakeLotteonClient()).snapshot()

    assert s.name == "원래이름"
    assert s.sale_price == 10000
    assert s.value_of("stock") == 5


def test_상세와_이미지는_응답에_없으면_확인불가로_남긴다():
    """지도에 미확보 필드다 — 없으면 없다고 적는다(0·빈문자로 채우지 않는다)."""
    s = _ops(FakeLotteonClient()).snapshot()

    assert s.detail_html is None
    assert s.image_urls is None
    assert "detail_html" in s.missing
    assert "image_urls" in s.missing


def test_응답에_상세와_이미지가_실제로_있으면_읽기는_한다():
    """프로브로 확인되면 지도를 되채우고 이 경로가 살아난다 — 읽기는 미리 열어 둔다.

    단 **쓰기가 없으므로 시험 대상은 아니다** — 되돌려 쓸 수 없는 축은
    읽히더라도 확인불가로 뺀다(그래야 가격·재고까지 같이 죽지 않는다).
    """
    cli = FakeLotteonClient(_detail(extra={
        "pdDtlDesc": "<p>상세</p>",
        "imgLst": [{"imgUrl": "http://img/a.jpg"}, {"imgUrl": "http://img/b.jpg"}],
    }))

    s = _ops(cli).snapshot()

    assert s.detail_html == "<p>상세</p>"
    assert s.image_urls == ("http://img/a.jpg", "http://img/b.jpg")
    assert "detail_html" in s.missing, "쓰기가 없으면 시험 대상이 아니다"


def test_재고_미관리는_센티넬을_그대로_내지_않는다():
    """stkMgtYn=N 이면 999,999,999 가 온다 — 「재고 10억」으로 보이면 안 된다."""
    cli = FakeLotteonClient(_detail(stock=999999999, stk_managed="N"))

    s = _ops(cli).snapshot()

    assert s.value_of("stock") is None
    assert "stock" in s.missing


def test_판매중이면_판매중으로_알린다():
    assert _ops(FakeLotteonClient(_detail(status="SALE"))).on_sale() is True
    assert _ops(FakeLotteonClient(_detail(status="STP"))).on_sale() is False


def test_품절은_판매중지가_아니다():
    """SOUT(품절)은 아직 팔리는 상품이다 — 건드리면 안 된다(거부)."""
    assert _ops(FakeLotteonClient(_detail(status="SOUT"))).on_sale() is True


def test_모르는_상태는_건드리지_않는다():
    assert _ops(FakeLotteonClient(_detail(status="XYZ"))).on_sale() is True


# ── 쓰기 ─────────────────────────────────────────────────────────────────────
def test_가격과_재고는_전용_경로로_보낸다():
    cli = FakeLotteonClient()

    _ops(cli).apply({"sale_price": 11000, "stock": 7})

    paths = [p for p, _ in cli.posts]
    assert "/price" in paths and "/stock" in paths
    assert "/modify" not in paths
    assert _ops(cli).snapshot().sale_price == 11000


def test_읽지_못하는_축은_보내지_않는다():
    """되읽어 확인할 수 없는 축을 보내면 원복 여부를 영영 못 잔다."""
    cli = FakeLotteonClient()

    with pytest.raises(RuntimeError, match="확인불가|미확보"):
        _ops(cli).apply({"detail_html": "<p>새</p>"})

    assert "/modify" not in [p for p, _ in cli.posts]


# ── 🔴 읽을 수 있어도 쓸 수 없으면 시험 대상이 아니다 ────────────────────────
def test_상품명은_읽히지만_시험대상에서_뺀다():
    """🔴 [2026-08-06 라이브] 롯데온 상품명은 조회로 **읽힌다**(pdNm). 그래서 시험
    대상에 들어갔는데, 쓰기(product/modification/request)가 배선 안 돼 apply 가 거부했다.
    그 바람에 **가격·재고까지 통째로 실패**했다.

    원칙: 되돌려 쓸 수 없는 축은 읽히더라도 「확인불가」로 빼야 한다.
    """
    s = _ops(FakeLotteonClient()).snapshot()

    assert s.name == "원래이름", "읽기는 되어야 한다"
    assert "name" in s.missing, "쓸 수 없으면 시험 대상에서 빠져야 한다"
    assert s.has("name") is False


def test_가격과_재고는_시험대상으로_남는다():
    """쓸 수 없는 축 때문에 쓸 수 있는 축까지 막히면 안 된다."""
    s = _ops(FakeLotteonClient()).snapshot()

    assert s.has("sale_price") is True
    assert s.has("stock") is True


def test_상품명만_빼면_가격_재고는_정상_전송된다():
    cli = FakeLotteonClient()

    _ops(cli).apply({"sale_price": 11000, "stock": 7})

    paths = [p for p, _ in cli.posts]
    assert "/price" in paths and "/stock" in paths
