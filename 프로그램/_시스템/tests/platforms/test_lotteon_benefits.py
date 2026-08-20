# -*- coding: utf-8 -*-
"""롯데온 셀러 주문혜택 조회(245) — 셀러/롯데부담 할인 파싱 단위테스트."""
from shared.platforms.lotteon.benefits import parse_benefit_map


def test_parse_seller_and_platform_discount():
    resp = {"data": {"orderItems": [
        {"odNo": "A1", "fvrList": [
            {"odFvrDvsCd": "DC", "prTypCd": "PRD_DC", "prEntpShrAmt": 966, "prSfcoShrAmt": 3864},
            {"odFvrDvsCd": "GF", "prTypCd": "GIV_PR", "prEntpShrAmt": 500, "prSfcoShrAmt": 0},
        ]},
    ]}}
    m = parse_benefit_map(resp)
    assert m["A1"] == {"seller_discount": 966, "platform_discount": 3864}


def test_numeric_strings_and_multiple_orders():
    resp = {"data": {"orderItems": [
        {"odNo": "B1", "fvrList": [
            {"odFvrDvsCd": "DC", "prEntpShrAmt": "100", "prSfcoShrAmt": "200"},
            {"odFvrDvsCd": "DC", "prEntpShrAmt": 50.0, "prSfcoShrAmt": 0},
        ]},
        {"odNo": "B2", "fvrList": []},
    ]}}
    m = parse_benefit_map(resp)
    assert m["B1"] == {"seller_discount": 150, "platform_discount": 200}
    assert m["B2"] == {"seller_discount": 0, "platform_discount": 0}
