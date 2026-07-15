# -*- coding: utf-8 -*-
"""[TEST] 스마트스토어 발주확인 표시 — placeOrderStatus 반영.

네이버는 발주확인해도 productOrderStatus=PAYED(결제완료) 그대로라, placeOrderStatus=OK 를
읽어야 '배송준비중'을 구분한다(안 읽으면 이미 배송준비된 주문이 결제완료로 둔갑).
"""
import pytest

from lemouton.markets.order_export import _ss_status


@pytest.mark.parametrize("pos,place,expected", [
    ("PAYED", "OK", "배송준비중"),      # 발주확인됨(배송준비) — 핵심 케이스
    ("PAYED", None, "결제완료"),         # 아직 발주확인 전
    ("PAYED", "", "결제완료"),
    ("PAYED", "NONE", "결제완료"),
    ("PAYED", "ok", "배송준비중"),       # 대소문자 무관
    ("DELIVERING", "OK", "배송중"),      # 이미 배송중이면 placeOrder 무관
    ("PURCHASE_DECIDED", "OK", "구매확정"),
    ("CANCELED", "OK", "취소완료"),
])
def test_ss_status_reflects_place_order(pos, place, expected):
    assert _ss_status(pos, place) == expected
