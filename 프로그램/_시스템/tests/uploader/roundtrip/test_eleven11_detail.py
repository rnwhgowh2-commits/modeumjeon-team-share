# -*- coding: utf-8 -*-
"""11번가 상세페이지 — **전용 API 가 따로 있었다**(2026-08-12 문서 확보).

  · 조회  GET  /rest/prodservices/getProductDetailCont/{prdNo}
          → <ProductDetailCont><prdDescContClob>…</prdDescContClob></ProductDetailCont>
  · 수정  POST /rest/prodservices/updateProductDetailCont/{prdNo}
          → 본문 같은 봉투. **성공 응답이 빈 <Product/>** 다.

🎯 이걸 쓰면 상품수정(PUT /product/{prdNo})의 **전체 교체 위험을 피한다**.
   문서 원문: 「상품수정은 … 기존 데이터는 사라지고 수정되는 정보로 교체됩니다.」

🔴🔴 수정 성공 응답에 resultCode 도 message 도 없다 — **되읽기가 유일한 검증 수단**이다.
   「보냈으니 됐다」로 적으면 거짓 보고가 된다.

⚠️ [오보 정정] 재고 상한 9,999 는 **내가 지어낸 값**이었다. 문서 어디에도 상한이 없고
   예제 재고는 500·62·99 다. 재고 실패를 수량 문제로 오진했을 때 넣은 추측이다.
"""
from __future__ import annotations

from lemouton.uploader.roundtrip.markets.eleven11 import make_eleven11_ops


class FakeEleven11:
    def __init__(self, *, detail="<p>원래 상세</p>"):
        self.state = {"price": 10000, "stock": 5, "detail": detail}
        self.calls = []

    def get_stocks(self, prd, *, client=None):
        return [{"opt_no": "1,2", "stock": self.state["stock"],
                 "prd_stck_no": "440634790", "opt_wght": 3,
                 "seller_stock_cd": "CD01101", "stat": "01"}]

    def get_price(self, prd, *, client=None):
        return self.state["price"]

    def get_detail(self, prd, *, client=None):
        self.calls.append(("get_detail", prd))
        return self.state["detail"]

    def update_detail(self, prd, html, *, client=None):
        self.calls.append(("update_detail", prd, html))
        self.state["detail"] = html


def _ops(f):
    return make_eleven11_ops("P1", client=object(), _get_stocks=f.get_stocks,
                             _get_price=f.get_price, _get_detail=f.get_detail,
                             _update_detail=f.update_detail)


def test_상세를_읽는다():
    s = _ops(FakeEleven11()).snapshot()

    assert s.detail_html == "<p>원래 상세</p>"
    assert "detail_html" not in s.missing, "전용 API 가 있는데 확인불가로 뺐다"


def test_상세를_못_읽으면_시험대상에서_뺀다():
    f = FakeEleven11()
    f.get_detail = lambda prd, client=None: None

    s = _ops(f).snapshot()

    assert s.detail_html is None
    assert "detail_html" in s.missing


def test_상세는_전용_API_로_보낸다():
    """🔴 상품수정(전체 교체)을 쓰면 나머지 필드가 지워진다 — 전용 API 로만."""
    f = FakeEleven11()

    _ops(f).apply({"detail_html": "<p>새 상세</p>"})

    assert ("update_detail", "P1", "<p>새 상세</p>") in f.calls
    assert f.state["detail"] == "<p>새 상세</p>"


def test_보낸_뒤_되읽으면_바뀐_값이_나온다():
    """수정 응답이 빈 <Product/> 라 성공 판정 근거가 없다 — 되읽기가 유일한 확인."""
    f = FakeEleven11()
    ops = _ops(f)

    ops.apply({"detail_html": "<p>새 상세</p>"})

    assert ops.snapshot().detail_html == "<p>새 상세</p>"


def test_상품명과_이미지는_여전히_확인불가다():
    """전용 API 가 없다 — 전체 교체 PUT 뿐이라 안 건드린다."""
    s = _ops(FakeEleven11()).snapshot()

    assert "name" in s.missing
    assert "image_urls" in s.missing


def test_지어낸_재고_상한을_쓰지_않는다():
    """🔴 문서에 재고 상한이 없다. 근거 없는 제약을 두면 되는 것도 안 하게 된다."""
    from lemouton.uploader.roundtrip.markets import eleven11 as M

    assert getattr(M, "STOCK_BOUNDS", None) is None, \
        "문서에 없는 상한을 코드가 들고 있다"
