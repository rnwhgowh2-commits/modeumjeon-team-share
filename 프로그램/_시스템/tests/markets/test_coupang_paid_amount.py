# -*- coding: utf-8 -*-
"""쿠팡 실결제금액 — 발주서 응답의 orderPrice·discountPrice 로 채운다.

라이브 감사(2026-07-21): 쿠팡 61/61행 실결제금액 공란. 데이터코드지도(발주서 조회)
확정 필드: orderPrice = 결제 가격(salesPrice×수량), discountPrice = 총 할인
(즉시할인+다운로드쿠폰+쿠팡지원할인). 고객 실결제 = orderPrice − discountPrice.
둘 다 마켓 원본값이라 폴백이 아니다. orderPrice 가 없으면 빈칸 유지(날조 금지).
"""
import copy
import datetime as _dt

KST = _dt.timezone(_dt.timedelta(hours=9))

_BOX = {
    "shipmentBoxId": "SB-1", "orderId": "OID-1",
    "orderedAt": "2026-07-10T10:00:00", "shippingPrice": {"units": 0},
    "orderer": {"name": "구매자"}, "receiver": {"name": "수령인", "addr1": "서울"},
    "orderItems": [{
        "vendorItemId": "VI-1", "sellerProductName": "신발",
        "shippingCount": 2, "salesPrice": {"units": 19000},
        "orderPrice": {"units": 38000}, "discountPrice": {"units": 3000},
    }],
}


def _rows(monkeypatch, box):
    calls = {"n": 0}

    def fake(w0, w1, client=None, status=None, next_token=None):
        calls["n"] += 1
        return {"data": [box]} if calls["n"] == 1 else {"data": []}

    import shared.platforms.coupang.orders as cp_orders
    monkeypatch.setattr(cp_orders, "fetch_orders", fake)
    from lemouton.markets.order_export import coupang_order_rows
    since = _dt.datetime(2026, 7, 9, tzinfo=KST)
    until = _dt.datetime(2026, 7, 11, tzinfo=KST)
    return coupang_order_rows(since, until, client=object(),
                              include_settlement=False)


def test_실결제는_결제가격_빼기_할인(monkeypatch):
    rows = _rows(monkeypatch, _BOX)
    assert rows[0]["실결제금액"] == 35000          # 38000 − 3000


def test_할인이_없으면_결제가격_그대로(monkeypatch):
    box = copy.deepcopy(_BOX)
    del box["orderItems"][0]["discountPrice"]
    rows = _rows(monkeypatch, box)
    assert rows[0]["실결제금액"] == 38000


def test_결제가격이_없으면_빈칸_유지(monkeypatch):
    """orderPrice 미제공이면 지어내지 않는다(폴백 금지)."""
    box = copy.deepcopy(_BOX)
    del box["orderItems"][0]["orderPrice"]
    rows = _rows(monkeypatch, box)
    assert rows[0]["실결제금액"] == ""


def test_옵션추가금은_구조적으로_0(monkeypatch):
    """쿠팡 vendorItem = 옵션 단위 상품이라 단가에 옵션가가 이미 포함 → 추가금 0."""
    rows = _rows(monkeypatch, _BOX)
    assert rows[0]["옵션추가금"] == 0


def test_미정산_추정은_판매자부담할인을_빼고_계산한다(monkeypatch):
    """정산 기준 매출 = 판매액 − 판매자할인쿠폰(즉시+다운로드). 쿠팡지원할인은 쿠팡이
    보전하므로 안 뺀다. 상품 11.55%·배송비 3% (2026-07-21 사장님 확정 요율).
    38000 − (2000+1000) = 35000 × 0.8845 = 30957.5 → 30958 (배송비 0)."""
    import copy as _c
    box = _c.deepcopy(_BOX)
    box["orderItems"][0]["instantCouponDiscount"] = {"units": 2000}
    box["orderItems"][0]["downloadableCouponDiscount"] = {"units": 1000}
    box["orderItems"][0]["coupangDiscount"] = {"units": 5000}   # 쿠팡 부담 — 차감 금지
    calls = {"n": 0}

    def fake(w0, w1, client=None, status=None, next_token=None):
        calls["n"] += 1
        return {"data": [box]} if calls["n"] == 1 else {"data": []}

    import shared.platforms.coupang.orders as cp_orders
    monkeypatch.setattr(cp_orders, "fetch_orders", fake)
    # 정산 API 는 빈 결과 → 추정 경로를 태운다
    import lemouton.markets.order_export as oe
    monkeypatch.setattr(oe, "_coupang_settle_map", lambda *a, **k: ({}, {}))
    since = _dt.datetime(2026, 7, 9, tzinfo=KST)
    until = _dt.datetime(2026, 7, 11, tzinfo=KST)
    rows = oe.coupang_order_rows(since, until, client=object(),
                                 include_settlement=True)
    r = rows[0]
    assert r["정산예정금액"] == round((38000 - 3000) * 0.8845)   # 30958
    assert r["_settle_source"] == "estimated"
