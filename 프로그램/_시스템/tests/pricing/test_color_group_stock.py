# -*- coding: utf-8 -*-
"""[TEST] SS 색상그룹 최저가 소싱처 선정 — 재고 선필터 회귀 (H3, 2026-06-12).

배경: decide_ss_color_group 가 최저가 소싱처를 '재고 무관 가격만'으로 골라,
      그 소싱처가 품절이면 색상 전체가 out_of_stock 으로 숨겨졌다(재고있는 더 비싼
      소싱처가 있어도 통째 미노출 = 판매기회 손실). 쿠팡 경로(coupang_decide)는
      이미 stock<=0 선필터가 있는데 SS 경로만 빠져 있었다 → 대칭으로 맞춤.
"""
from lemouton.pricing.color_group import decide_ss_color_group


def _opt(sku, sources, *, boxhero=0, lemouton_only=False, pricing=None):
    p = {
        "guardrail_lower_effective": 99000,
        "guardrail_upper_effective": 120000,
        "use_margin_formula_for_external_effective": False,
        "external_ss_price_effective": 128900,
    }
    if pricing:
        p.update(pricing)
    return {
        "canonical_sku": sku,
        "boxhero_stock": boxhero,
        "lemouton_only": lemouton_only,
        "sources": sources,
        "pricing": p,
    }


def test_cheapest_source_out_of_stock_falls_to_instock_source():
    # 최저가(lotteon 10만, 품절)가 아니라 재고있는 ssf(11만)로 넘어가 노출돼야 한다.
    opts = [_opt("SKU1", [
        {"name": "lotteon", "price": 100000, "stock": 0},
        {"name": "ssf", "price": 110000, "stock": 5},
    ])]
    res = decide_ss_color_group(opts)
    assert len(res) == 1
    assert res[0].displayed is True
    assert res[0].reason == "external_fixed"


def test_all_sources_out_of_stock_stays_hidden():
    # 전 소싱처 품절이면 그대로 미노출(out_of_stock) — 동작 보존.
    opts = [_opt("SKU1", [
        {"name": "ssf", "price": 110000, "stock": 0},
    ])]
    res = decide_ss_color_group(opts)
    assert res[0].displayed is False
    assert res[0].reason == "out_of_stock"


def test_cheapest_instock_source_selected_normally():
    # 최저가가 재고있으면 그대로 최저가 선정 — 동작 보존.
    opts = [_opt("SKU1", [
        {"name": "lotteon", "price": 100000, "stock": 3},
        {"name": "ssf", "price": 110000, "stock": 5},
    ])]
    res = decide_ss_color_group(opts)
    assert res[0].displayed is True
