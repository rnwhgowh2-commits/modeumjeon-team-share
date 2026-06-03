"""tests/pricing/test_unified.py — 통합 가격 계산기 (Phase 1 TDD).

ai-workflow cycle 20260521 · Phase 1 · Task 1
"""
import types

import pytest

from lemouton.pricing.unified import (
    compute_sale_price_unified, PriceResult,
    resolve_market_policy, compute_market_price,
)


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


# ============ [2026-06-02] mode='amount' (마진금액 = 수수료 뒤 실수령) ============

def test_amount_mode_basic():
    # (100,000 + 5,000) / (1 - 0.0945) = 115,958.03 → 115,958 → 100단위 → 116,000
    r = compute_sale_price_unified(
        100_000, 0.0, 0.0945, shipping_fee=0,
        mode='amount', margin_amount=5_000)
    assert r.breakdown['mode'] == 'amount'
    assert r.final_price == 116_000


def test_amount_mode_net_received_equals_amount():
    # 핵심 의미 검증: 수수료(판매가×수수료율) 차감 후 실수령 ≈ 원가 + 마진금액
    fee = 0.0945
    r = compute_sale_price_unified(
        100_000, 0.0, fee, shipping_fee=0, mode='amount', margin_amount=5_000)
    net = r.final_price - r.final_price * fee  # 판매가 - 수수료
    # 라운딩 오차(±100) 내에서 원가+마진금액(105,000) 회수
    assert abs(net - 105_000) < 150


def test_amount_mode_with_shipping():
    # base + 배송비 3,000
    r = compute_sale_price_unified(
        100_000, 0.0, 0.0945, shipping_fee=3_000,
        mode='amount', margin_amount=5_000)
    assert r.final_price == 119_000


def test_amount_mode_zero_purchase():
    r = compute_sale_price_unified(0, 0.0, 0.0945, mode='amount', margin_amount=5_000)
    assert r.final_price == 0


# ============ [2026-06-02] mode='fixed' (지정가 — 그대로) ============

def test_fixed_mode_exact():
    # 지정가 133,900 → 계산 없이 그대로 (라운딩도 안 함)
    r = compute_sale_price_unified(
        95_000, 0.10, 0.1155, mode='fixed', fixed_price=133_900)
    assert r.breakdown['mode'] == 'fixed'
    assert r.final_price == 133_900


def test_fixed_mode_independent_of_purchase():
    # 원가가 0이어도 지정가는 유지
    r = compute_sale_price_unified(0, 0.10, 0.1155, mode='fixed', fixed_price=128_900)
    assert r.final_price == 128_900


def test_fixed_mode_fallback_to_rate_when_zero():
    # mode=fixed 인데 지정가 미설정(0) → rate 폴백 (판매가 0 방지)
    r = compute_sale_price_unified(
        95_000, 0.10, 0.1155, mode='fixed', fixed_price=0)
    assert r.breakdown['mode'] == 'rate'
    assert r.final_price == 116_600  # rate 모드 기존값


def test_fixed_mode_guardrail():
    r = compute_sale_price_unified(
        95_000, 0.10, 0.1155, mode='fixed', fixed_price=133_900,
        guardrail=(100_000, 130_000))
    assert r.guardrail_status == 'above'  # 133,900 >= 130,000


# ============ rate 모드 회귀 — 기존 동작 불변 ============

def test_rate_mode_unchanged_default():
    # mode 기본값 'rate' — 기존 곱셈형 그대로
    r = compute_sale_price_unified(95_000, 0.10, 0.1155, shipping_fee=0)
    assert r.final_price == 116_600
    assert r.breakdown['mode'] == 'rate'


# ============ 정책 해석기 resolve_market_policy ============

def _tpl(**kw):
    base = dict(
        ss_mode_sourcing='rate', ss_rate_sourcing=0.0945, ss_amount_sourcing=0,
        ss_mode_purchase='rate', ss_rate_purchase=0.0945, ss_amount_purchase=0,
        ss_external_sale_price=0, ss_boxhero_sale_price=0,
        ss_fee_rate=0.06, ss_delivery_fee=3_000,
        coupang_mode_sourcing='rate', coupang_rate_sourcing=0.1242,
        coupang_amount_sourcing=0, coupang_mode_purchase='rate',
        coupang_rate_purchase=0.1242, coupang_amount_purchase=0,
        coupang_external_sale_price=0, coupang_boxhero_sale_price=0,
        coupang_fee_rate=0.1155, coupang_delivery_fee=3_500,
        rounding_unit=100,
    )
    base.update(kw)
    return types.SimpleNamespace(**base)


def test_resolve_ss_sourcing_amount():
    tpl = _tpl(ss_mode_sourcing='amount', ss_amount_sourcing=5_000)
    pol = resolve_market_policy(tpl, 'ss', 'sourcing')
    assert pol['mode'] == 'amount'
    assert pol['amount'] == 5_000
    assert pol['fee_rate'] == 0.06


def test_resolve_coupang_sourcing_fixed():
    tpl = _tpl(coupang_mode_sourcing='fixed', coupang_external_sale_price=133_900)
    pol = resolve_market_policy(tpl, 'coupang', 'sourcing')
    assert pol['mode'] == 'fixed'
    assert pol['fixed_price'] == 133_900


def test_resolve_ss_purchase_fixed_uses_boxhero_price():
    tpl = _tpl(ss_mode_purchase='fixed', ss_boxhero_sale_price=116_900)
    pol = resolve_market_policy(tpl, 'smartstore', 'purchase')
    assert pol['fixed_price'] == 116_900


def test_resolve_none_template_defaults():
    pol = resolve_market_policy(None, 'ss', 'sourcing')
    assert pol['mode'] == 'rate'
    assert pol['rate'] == 0.0945


# ============ compute_market_price — 해석기 + 계산 단일 진입점 ============

def test_compute_market_price_coupang_fixed():
    tpl = _tpl(coupang_mode_sourcing='fixed', coupang_external_sale_price=133_900)
    r = compute_market_price(tpl, 'coupang', 'sourcing', 100_000)
    assert r.final_price == 133_900


def test_compute_market_price_ss_sourcing_amount():
    tpl = _tpl(ss_mode_sourcing='amount', ss_amount_sourcing=5_000,
               ss_fee_rate=0.0945, ss_delivery_fee=0)
    r = compute_market_price(tpl, 'ss', 'sourcing', 100_000)
    assert r.final_price == 116_000
