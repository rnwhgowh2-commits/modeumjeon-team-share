# -*- coding: utf-8 -*-
"""11번가 배송중 라인 주문일 교정 — 같은 주문의 실주문일(ordDt)로 근사(ordNo[:8])를 덮는다.

배송중(shipping) 목록은 ordDt 미제공 → order_export 가 ordNo 앞8자리로 근사(라이브 82/82 일치).
부분발송처럼 같은 주문번호가 날짜목록에도 있으면 그 실주문일로 교정(정밀). 클레임행은 공란 유지.
"""
from lemouton.markets import order_export as oe


def test_partial_shipment_shipping_line_gets_real_ordt():
    """부분발송 — 같은 주문번호의 배송완료 라인 실주문일로 배송중 라인 교정."""
    rows = [
        # 배송완료 라인: 실주문일(ordDt 출처)
        {"오픈마켓주문번호": "202607100001", "주문일": "2026-07-06 10:00:00",
         "주문상태": "배송완료", "_ordt_real": True},
        # 배송중 라인(같은 주문): ordDt 없어 ordNo[:8]=2026-07-10 으로 근사됨(실제는 07-06)
        {"오픈마켓주문번호": "202607100001", "주문일": "2026-07-10",
         "주문상태": "배송중", "_ordt_real": False},
    ]
    out = oe._eleven11_fill_shipping_ordt(rows)
    ship = [r for r in out if r["주문상태"] == "배송중"][0]
    assert ship["주문일"] == "2026-07-06 10:00:00"   # 실주문일로 교정
    assert "_ordt_real" not in ship                  # 임시 플래그 제거


def test_shipping_without_sibling_keeps_approximation():
    """같은 주문의 날짜소스가 없으면 근사(ordNo[:8]) 유지 — 폴백 파괴 금지."""
    rows = [
        {"오픈마켓주문번호": "202607100002", "주문일": "2026-07-10",
         "주문상태": "배송중", "_ordt_real": False},
    ]
    out = oe._eleven11_fill_shipping_ordt(rows)
    assert out[0]["주문일"] == "2026-07-10"           # 근사 유지
    assert "_ordt_real" not in out[0]


def test_claim_row_blank_orderdate_untouched():
    """클레임행(_kind='change', 주문일 공란)은 같은 주문번호 실주문일이 있어도 안 채운다(의도)."""
    rows = [
        {"오픈마켓주문번호": "202607100003", "주문일": "2026-07-06 09:00:00",
         "주문상태": "배송완료", "_ordt_real": True},
        {"오픈마켓주문번호": "202607100003", "주문일": "",
         "주문상태": "취소완료", "_kind": "change"},
    ]
    out = oe._eleven11_fill_shipping_ordt(rows)
    claim = [r for r in out if r.get("_kind") == "change"][0]
    assert claim["주문일"] == ""                      # 공란 유지 → new_order_rows 드롭


def test_real_ordt_rows_unchanged():
    """실주문일 소스 행은 그대로(불필요한 덮어쓰기 없음)."""
    rows = [
        {"오픈마켓주문번호": "202607160009", "주문일": "2026-07-16 20:59:55",
         "주문상태": "결제완료", "_ordt_real": True},
    ]
    out = oe._eleven11_fill_shipping_ordt(rows)
    assert out[0]["주문일"] == "2026-07-16 20:59:55"
    assert "_ordt_real" not in out[0]
