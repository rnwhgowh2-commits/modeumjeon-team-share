"""tests/pricing/test_unified.py — 통합 가격 계산기 (Phase 1 TDD).

ai-workflow cycle 20260521 · Phase 1 · Task 1
"""
import pytest

from lemouton.pricing.unified import compute_sale_price_unified, PriceResult


# ============ 기본 곱셈형 계산 ============

def test_basic_multiplicative():
    # 95,000 × 1.10 × 1.1155 = 116,569.75 → 116,570 → 100원단위 → 116,600
    r = compute_sale_price_unified(95_000, 0.10, 0.1155, shipping_fee=0)
    assert r.final_price == 116_600


def test_with_shipping():
    # 95,000 × 1.10 × 1.1155 + 3,000 = 119,569.75 → 119,600
    r = compute_sale_price_unified(95_000, 0.10, 0.1155, shipping_fee=3_000)
    assert r.final_price == 119_600


def test_round_numbers():
    # 100,000 × 1.20 × 1.10 = 132,000
    r = compute_sale_price_unified(100_000, 0.20, 0.10, shipping_fee=0)
    assert r.final_price == 132_000


def test_zero_purchase():
    r = compute_sale_price_unified(0, 0.10, 0.1155)
    assert r.final_price == 0
    assert r.guardrail_status == 'none'


def test_none_purchase():
    r = compute_sale_price_unified(None, 0.10, 0.1155)
    assert r.final_price == 0


# ============ 라운딩 (round-half-up, 전 경로 통일) ============

def test_rounding_half_up():
    # 100,000 + 배송 50 = 100,050 → 100원단위 round-half-up → 100,100
    r = compute_sale_price_unified(100_000, 0.0, 0.0, shipping_fee=50)
    assert r.final_price == 100_100


def test_rounding_down():
    # 100,000 + 배송 49 = 100,049 → 100,000
    r = compute_sale_price_unified(100_000, 0.0, 0.0, shipping_fee=49)
    assert r.final_price == 100_000


def test_rounding_unit_custom():
    # 1,000원 단위 — 100,600 → 101,000
    r = compute_sale_price_unified(100_000, 0.0, 0.0, shipping_fee=600,
                                   rounding_unit=1_000)
    assert r.final_price == 101_000


# ============ 가드레일 ============

def test_guardrail_none():
    r = compute_sale_price_unified(95_000, 0.10, 0.1155)
    assert r.guardrail_status == 'none'


def test_guardrail_ok():
    # final 116,600 ∈ [100,000, 130,000)
    r = compute_sale_price_unified(95_000, 0.10, 0.1155,
                                   guardrail=(100_000, 130_000))
    assert r.guardrail_status == 'ok'


def test_guardrail_below():
    # final 116,600 < 하한 120,000
    r = compute_sale_price_unified(95_000, 0.10, 0.1155,
                                   guardrail=(120_000, 130_000))
    assert r.guardrail_status == 'below'


def test_guardrail_above():
    # final 116,600 >= 상한 116,600 (상한 포함 = above)
    r = compute_sale_price_unified(95_000, 0.10, 0.1155,
                                   guardrail=(100_000, 116_600))
    assert r.guardrail_status == 'above'


# ============ breakdown (산출과정 표시용) ============

def test_breakdown_values():
    r = compute_sale_price_unified(95_000, 0.10, 0.1155, shipping_fee=0)
    b = r.breakdown
    assert b['purchase_price'] == 95_000
    assert b['margin_amount'] == 9_500             # 95,000 × 0.10
    assert b['subtotal_after_margin'] == 104_500
    assert b['fee_amount'] == 12_070               # round(104,500 × 0.1155)
    assert b['final_price'] == 116_600


def test_result_type():
    r = compute_sale_price_unified(95_000, 0.10, 0.1155)
    assert isinstance(r, PriceResult)
