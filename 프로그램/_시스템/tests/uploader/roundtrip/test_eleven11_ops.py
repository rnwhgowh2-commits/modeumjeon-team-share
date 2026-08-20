# -*- coding: utf-8 -*-
"""11번가 왕복 어댑터 — 가격·재고.

사장님 지적(2026-08-07): 「11번가도 가능하다 · 더망고는 이미 하고 있다」
확인해 보니 **가격·재고는 이미 우리 코드에 다 있었다** — 어댑터만 없었다:

  · 가격 쓰기  `GET /rest/prodservices/product/price/{prdNo}/{selPrc}`
               `eleven11/prices.update_price`
  · 재고 쓰기  `PUT /rest/prodservices/stockqty/{prdStckNo}`
               `eleven11/inventory.update_stock_by_stock_no`  (옵션 단위·안전)
  · 되읽기     `POST /rest/prodmarketservice/prodmarket/stocks`
               `eleven11/stocks_query.get_stocks` (지도 st=ok)

🔴 `inventory.update_stock` 은 **일부러 NotImplementedError** 를 낸다 —
   옵션 전체교체 API 라 한 옵션만 보내면 형제 옵션이 지워진다. 절대 쓰지 않는다.

상품명·상세·이미지는 수정 API 스펙 미확보 → 확인불가(지어내지 않는다).
"""
from __future__ import annotations

import pytest

from lemouton.uploader.roundtrip.markets.eleven11 import make_eleven11_ops


class FakeEleven11:
    def __init__(self, *, price=10000, stock=5):
        self.state = {"price": price, "stock": stock}
        self.calls = []

    # 어댑터가 주입해 쓰는 함수들 대역
    def get_stocks(self, prd, *, client=None):
        # 🔴 [2026-08-12 라이브] 재고수량 변경의 열쇠는 **prd_stck_no** 다.
        #    seller_stock_cd(판매자 관리코드)를 넘겼다가 두 번 거부당했다.
        #    optWght(상품무게)도 그대로 되돌려 보내야 한다(echo-back).
        self.calls.append(("get_stocks", prd))
        return [{"opt_no": "OPT1", "opt_nm": "색상", "dtl_opt_nm": "블랙",
                 "stock": self.state["stock"], "seller_stock_cd": "내관리코드",
                 "prd_stck_no": "1", "opt_wght": 300,
                 "add_prc": 0, "stat": "판매중"}]

    def get_price(self, prd, *, client=None):
        self.calls.append(("get_price", prd))
        return self.state["price"]

    def update_price(self, prd, price, *, client=None):
        self.calls.append(("update_price", prd, price))
        self.state["price"] = int(price)
        class R:
            success = True
            error_message = None
        return R()

    def update_stock(self, prd, stck_no, qty, opt_wght=None, *, client=None):
        self.calls.append(("update_stock", prd, stck_no, qty, opt_wght))
        self.state["stock"] = int(qty)
        class R:
            success = True
            error_message = None
        return R()


def _ops(f, **kw):
    return make_eleven11_ops("P1", client=object(), _get_stocks=f.get_stocks,
                             _get_price=f.get_price, _update_price=f.update_price,
                             _update_stock=f.update_stock, **kw)


# ── 되읽기 ───────────────────────────────────────────────────────────────────
def test_가격과_재고를_읽는다():
    s = _ops(FakeEleven11()).snapshot()

    assert s.sale_price == 10000
    assert s.value_of("stock") == 5


def test_상품명_상세_이미지는_확인불가다():
    """11번가 상품수정 API 스펙이 미확보다 — 없는 것을 있는 척 하지 않는다."""
    s = _ops(FakeEleven11()).snapshot()

    for axis in ("name", "detail_html", "image_urls"):
        assert axis in s.missing, f"{axis} 를 시험 대상으로 잡으면 안 된다"


def test_재고를_못_읽으면_0으로_채우지_않는다():
    f = FakeEleven11()
    f.get_stocks = lambda prd, client=None: []

    s = _ops(f).snapshot()

    assert s.value_of("stock") is None
    assert "stock" in s.missing


# ── 쓰기 ─────────────────────────────────────────────────────────────────────
def test_가격은_전용_API_로_보낸다():
    f = FakeEleven11()

    _ops(f).apply({"sale_price": 10100})

    assert ("update_price", "P1", 10100) in f.calls
    assert f.state["price"] == 10100


def test_재고는_prd_stck_no_로_한_옵션만_보낸다():
    """🔴 열쇠는 **prdStckNo** 다. seller_stock_cd(판매자 관리코드)를 넘기면
    「옵션재고 번호 …의 수량 업데이트 실패」로 거부된다(2026-08-12 라이브 2회).
    옵션 전체교체 API 를 쓰면 형제 옵션이 지워지므로 그쪽도 쓰지 않는다."""
    f = FakeEleven11()

    _ops(f).apply({"stock": 6})

    assert ("update_stock", "P1", "1", 6, 300) in f.calls, f"보낸 값: {f.calls}"
    assert f.state["stock"] == 6


def test_재고번호가_없으면_보내지_않는다():
    """관리코드로 대신 채워 보내면 거부된다 — 없으면 확인불가로 남긴다."""
    f = FakeEleven11()
    f.get_stocks = lambda prd, client=None: [
        {"opt_no": "OPT1", "stock": 5, "seller_stock_cd": "내관리코드"}]

    s = _ops(f).snapshot()

    assert "stock" in s.missing, "재고번호를 모르는데 시험 대상으로 잡았다"


def test_쓸_수_없는_축은_거부한다():
    """상품명은 전용 API 가 없다 — 상품수정(PUT)은 **전체 교체**라 안 쓴다."""
    f = FakeEleven11()

    with pytest.raises(RuntimeError, match="전체 교체"):
        _ops(f).apply({"name": "새이름"})


def test_쓰고_되읽으면_바뀐_값이_나온다():
    f = FakeEleven11()
    ops = _ops(f)

    ops.apply({"sale_price": 10100, "stock": 6})

    s = ops.snapshot()
    assert s.sale_price == 10100
    assert s.value_of("stock") == 6
