# -*- coding: utf-8 -*-
"""쿠팡 실결제금액 = orderPrice − 판매자부담쿠폰(즉시+다운로드).

라이브 감사(2026-07-21): 쿠팡 61/61행 실결제금액 공란. 데이터코드지도(발주서 조회)
확정 필드: orderPrice = 결제 가격(salesPrice×수량), instantCouponDiscount·
downloadableCouponDiscount = 판매자부담 쿠폰, coupangDiscount = 쿠팡부담.
전부 마켓 원본값이라 폴백이 아니다. orderPrice 가 없으면 빈칸 유지(날조 금지).

기준이 두 번 바뀐 자리다 — 왜 지금이 이 값인지 남긴다
    · 2026-07-23  `orderPrice` **그대로**(할인 차감 전). 샵마인 K열과 글자 그대로
      맞추려던 규약이었다.
    · 2026-08-06  사장님 확정 → **판매자부담쿠폰을 뺀다.** 「매출」은 우리가 실제로
      번 돈이어야 한다. 옛 규약 때문에 쿠팡만 매출이 쿠폰만큼 부풀어 있었고,
      「정가−실결제」로 재는 마켓 할인 카드에서 쿠팡만 **영원히 0** 으로 보였다
      (2026-08-06 실측: 하루치는 정말 0 이었지만 7일치엔 47,700원이 있었다).

🔴 `discountPrice`(총 할인)를 쓰지 않는 이유
    총 할인에는 **쿠팡부담**(coupangDiscount)이 섞여 있다. 그건 쿠팡이 우리에게
    보전하므로 우리 매출이 줄지 않는다. 그걸 빼면 매출이 실제보다 작아진다.
    롯데온이 `_lo_seller_dc`(셀러 부담)만 빼는 것과 같은 규칙이다.

🔴 이중 차감 금지
    정산 추정(`_cp_estimate_settle`)은 **단가×수량 − 판매자부담쿠폰**으로 따로
    계산한다 — 실결제금액을 안 본다. 그래서 여기서 빼도 정산이 두 번 깎이지 않는다.
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


def test_판매자부담쿠폰이_없으면_결제가격_그대로(monkeypatch):
    """`discountPrice` 3,000 이 있어도 판매자부담이 0 이면 안 뺀다(쿠팡부담일 수 있다)."""
    rows = _rows(monkeypatch, _BOX)
    assert rows[0]["실결제금액"] == 38000


def test_할인이_없으면_결제가격_그대로(monkeypatch):
    box = copy.deepcopy(_BOX)
    del box["orderItems"][0]["discountPrice"]
    rows = _rows(monkeypatch, box)
    assert rows[0]["실결제금액"] == 38000


def test_판매자부담쿠폰은_빼고_쿠팡부담은_안_뺀다(monkeypatch):
    """🔴 이 시험이 지키는 것 — 「매출」은 우리가 실제로 번 돈이어야 한다.

    즉시 2,000 + 다운로드 1,000 은 우리 주머니에서 나가므로 뺀다.
    쿠팡지원 5,000 은 쿠팡이 보전하므로 빼면 매출이 실제보다 작아진다.
    (`discountPrice` 총 8,000 을 그대로 빼면 5,000 을 손해 본 것처럼 보인다.)
    """
    box = copy.deepcopy(_BOX)
    box["orderItems"][0]["instantCouponDiscount"] = {"units": 2000}
    box["orderItems"][0]["downloadableCouponDiscount"] = {"units": 1000}
    box["orderItems"][0]["coupangDiscount"] = {"units": 5000}
    box["orderItems"][0]["discountPrice"] = {"units": 8000}
    rows = _rows(monkeypatch, box)
    assert rows[0]["실결제금액"] == 35000, "판매자부담쿠폰 3,000 이 안 빠졌거나 쿠팡부담까지 뺐다"
    assert rows[0]["단가"] == 19000 and rows[0]["수량"] == 2, "정가 근거(단가·수량)가 흔들리면 안 된다"


def test_정가와_실결제의_차가_곧_판매자부담쿠폰이다(monkeypatch):
    """마켓 할인 카드가 「정가−실결제」로 재기 때문에 이 항등식이 곧 화면의 값이다.

    이게 깨지면 쿠팡만 할인이 0 으로 보이거나(옛 규약) 두 번 세어진다.
    """
    box = copy.deepcopy(_BOX)
    box["orderItems"][0]["instantCouponDiscount"] = {"units": 2000}
    box["orderItems"][0]["downloadableCouponDiscount"] = {"units": 1000}
    r = _rows(monkeypatch, box)[0]
    정가 = r["단가"] * r["수량"]
    assert 정가 - r["실결제금액"] == r["_cp_seller_dc"] == 3000


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
    monkeypatch.setattr(oe, "_coupang_settle_map", lambda *a, **k: ({}, {}, {}))
    since = _dt.datetime(2026, 7, 9, tzinfo=KST)
    until = _dt.datetime(2026, 7, 11, tzinfo=KST)
    rows = oe.coupang_order_rows(since, until, client=object(),
                                 include_settlement=True)
    r = rows[0]
    # 기준 = 38,000 − 판매자부담할인 3,000 = 35,000 (사장님 확정 「할인가가 정산 기준」)
    # 🔴 [2026-08-13 정정] 옛 시험은 `round(35000 * 0.8845)` = 30,958 로 **구현식을
    #   그대로 베껴** 있었다. 쿠팡은 수수료를 먼저 반올림한다:
    #     35,000 × 11.55% = 4,042.5 → **4,043**(엑셀 실측 28행 전부 올림) → 정산 30,957
    #   파이썬 `round()` 는 은행가 반올림이라 4,042 로 내려 1원 크게 잡고 있었다.
    assert r["정산예정금액"] == 35000 - 4043      # 30,957
    assert r["_settle_source"] == "estimated"
    # 🔴 이중 차감 금지 — 추정은 단가×수량 기준이라 실결제를 안 본다.
    #   실결제도 35,000 이지만 정산이 (35,000−3,000) 로 또 깎이면 안 된다.
    assert r["실결제금액"] == 35000
