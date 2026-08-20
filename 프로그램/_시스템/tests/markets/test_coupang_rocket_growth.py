# -*- coding: utf-8 -*-
"""쿠팡 로켓그로스 주문 조회 — 정산예정금액에 통째로 빠져 있던 매출.

🔴 왜 필요한가(2026-08-06 실측) — 로켓그로스 주문은 **별도 창구**(rg/orders)로만 오는데
   우리 수집 코드는 그 창구를 아예 안 불렀다(grep 0건). 그래서 주문내역에도,
   정산예정금액에도 로켓그로스 매출이 **한 건도 없었다**(사장님 지적).

★ 이 API 는 판매가·수량만 준다 — **정산액은 없다**. 정산은 revenue-history 에 같이
  잡히는지 라이브 실측으로 확인해야 한다(/orders/diag/coupang-rg 창구).
★ 조회창 최대 30일(paidDateFrom~To, yyyymmdd). 페이징은 nextToken.
"""
from __future__ import annotations

import datetime as _dt


class _Client:
    _cfg = {"vendor_id": "A0001"}

    def __init__(self, pages=None):
        self.calls = []
        self.pages = pages or [{"code": 200, "data": [], "nextToken": ""}]
        self._i = 0

    def request(self, method, path, query=""):
        self.calls.append(query)
        p = self.pages[min(self._i, len(self.pages) - 1)]
        self._i += 1
        return p


_ORDER = {
    "orderId": 7001, "vendorId": "A0001", "paidAt": "2026-08-01T10:00:00",
    "orderItems": [
        {"vendorItemId": 91, "productName": "나이키 코트", "salesQuantity": 2,
         "salesPrice": "59000", "currency": "KRW"},
        {"vendorItemId": 92, "productName": "아디다스 삼바", "salesQuantity": 1,
         "salesPrice": "88000", "currency": "KRW"},
    ],
}


def test_주문을_옵션_단위로_펼쳐_돌려준다():
    from shared.platforms.coupang import rocket_growth as rg
    cli = _Client([{"code": 200, "data": [_ORDER], "nextToken": ""}])
    rows = rg.fetch_rg_orders("2026-08-01", "2026-08-05", client=cli)
    assert len(rows) == 2
    assert rows[0]["주문번호"] == "7001"
    assert rows[0]["옵션ID"] == "91"
    assert rows[0]["수량"] == 2
    assert rows[0]["단가"] == 59000
    assert rows[0]["상품금액"] == 118000          # 단가 × 수량
    assert rows[0]["주문일"] == "2026-08-01"
    assert "paidDateFrom=20260801" in cli.calls[0]
    assert "paidDateTo=20260805" in cli.calls[0]


def test_페이징은_nextToken_으로_이어_받는다():
    from shared.platforms.coupang import rocket_growth as rg
    cli = _Client([
        {"code": 200, "data": [_ORDER], "nextToken": "T2"},
        {"code": 200, "data": [dict(_ORDER, orderId=7002)], "nextToken": ""},
    ])
    rows = rg.fetch_rg_orders("2026-08-01", "2026-08-05", client=cli)
    assert {r["주문번호"] for r in rows} == {"7001", "7002"}
    assert "nextToken=T2" in cli.calls[1]


def test_조회창은_30일까지만_한번에():
    """마켓 제약 — 넘기면 창을 쪼갠다(넓게 물어 조용히 0건 되는 것 방지)."""
    from shared.platforms.coupang import rocket_growth as rg
    cli = _Client([{"code": 200, "data": [], "nextToken": ""}])
    rg.fetch_rg_orders("2026-06-01", "2026-08-05", client=cli)
    assert len(cli.calls) >= 3        # 66일 → 30일씩 3창 이상


def test_값이_없는_항목은_담지_않는다():
    """폴백 금지 — 옵션ID·수량이 없으면 그 줄은 만들지 않는다."""
    from shared.platforms.coupang import rocket_growth as rg
    bad = {"orderId": 7003, "paidAt": "2026-08-01T10:00:00",
           "orderItems": [{"productName": "이름만"}]}
    cli = _Client([{"code": 200, "data": [bad], "nextToken": ""}])
    assert rg.fetch_rg_orders("2026-08-01", "2026-08-05", client=cli) == []


def test_응답이_배열이어도_읽는다():
    """쿠팡 지급내역이 그랬듯 모양이 다를 수 있다(2026-08-06 실측 교훈)."""
    from shared.platforms.coupang import rocket_growth as rg

    class _ListClient(_Client):
        def request(self, method, path, query=""):
            self.calls.append(query)
            return [_ORDER]
    rows = rg.fetch_rg_orders("2026-08-01", "2026-08-05", client=_ListClient())
    assert len(rows) == 2


def test_결제일시가_타임스탬프여도_날짜로_읽는다():
    """지도 원문 — paidAt 이 'Time stamp 1746093162000' 로 오는 예시가 있다."""
    from shared.platforms.coupang import rocket_growth as rg
    o = dict(_ORDER, paidAt="1785546000000")      # 2026-08-01 10:00 KST (ms)
    cli = _Client([{"code": 200, "data": [o], "nextToken": ""}])
    rows = rg.fetch_rg_orders("2026-08-01", "2026-08-05", client=cli)
    assert rows[0]["주문일"].startswith("2026-08")


# ══ [2026-08-06 라이브 실측] 단가 필드명이 문서와 다르다 ═════════════════════
#  세소(쿠팡) 응답 data 50건인데 파싱 0건이었다. 실제 항목 키:
#    currency · productName · salesQuantity · **unitSalesPrice** · vendorItemId
#  문서(지도)는 salesPrice 라고 적혀 있다 → 두 이름을 모두 받는다.

_REAL_ORDER = {
    "orderId": 8001, "vendorId": "A0001", "paidAt": "2026-07-10T09:00:00",
    "orderItems": [{"vendorItemId": 55, "productName": "티셔츠",
                    "salesQuantity": 3, "unitSalesPrice": "12000", "currency": "KRW"}],
}


def test_실제_필드명_unitSalesPrice_로도_읽는다():
    from shared.platforms.coupang import rocket_growth as rg
    cli = _Client([{"code": 200, "data": [_REAL_ORDER], "nextToken": ""}])
    rows = rg.fetch_rg_orders("2026-07-01", "2026-07-25", client=cli)
    assert len(rows) == 1
    assert rows[0]["단가"] == 12000
    assert rows[0]["상품금액"] == 36000        # 12,000 × 3
    assert rows[0]["주문번호"] == "8001"


def test_문서_이름_salesPrice_도_계속_받는다():
    """둘 중 어느 이름으로 와도 읽는다(마켓이 되돌릴 수 있다)."""
    from shared.platforms.coupang import rocket_growth as rg
    cli = _Client([{"code": 200, "data": [_ORDER], "nextToken": ""}])
    assert len(rg.fetch_rg_orders("2026-08-01", "2026-08-05", client=cli)) == 2
