"""tests/pricing/test_unified.py — 통합 가격 계산기 (Phase 1 TDD).

ai-workflow cycle 20260521 · Phase 1 · Task 1
"""
import types

import pytest

from lemouton.pricing.unified import (
    compute_sale_price_unified, PriceResult,
    resolve_market_policy, compute_market_price,
)


# ============ 기본 계산 — 마진율 = 판매가 대비 (2026-07-20) ============

def test_basic_margin_of_price():
    # 95,000 / (1 - 0.1155 - 0.10) = 121,096.24 → 100원단위 버림 → 121,000
    r = compute_sale_price_unified(95_000, 0.10, 0.1155, shipping_fee=0)
    assert r.final_price == 121_000


def test_with_shipping():
    # 위 + 배송비 3,000 → 124,096.24 → 버림 → 124,000
    r = compute_sale_price_unified(95_000, 0.10, 0.1155, shipping_fee=3_000)
    assert r.final_price == 124_000


def test_round_numbers():
    # 100,000 / (1 - 0.10 - 0.20) = 142,857.14 → 버림 → 142,800
    r = compute_sale_price_unified(100_000, 0.20, 0.10, shipping_fee=0)
    assert r.final_price == 142_800


def test_zero_purchase():
    r = compute_sale_price_unified(0, 0.10, 0.1155)
    assert r.final_price == 0
    assert r.guardrail_status == 'none'


def test_none_purchase():
    r = compute_sale_price_unified(None, 0.10, 0.1155)
    assert r.final_price == 0


# ============ 라운딩 (floor/버림, 전 경로 통일 — 2026-07-02) ============

def test_rounding_floor():
    # [2026-07-02] 백원단위 버림 — 100,000 + 배송 50 = 100,050 → 버림 → 100,000
    r = compute_sale_price_unified(100_000, 0.0, 0.0, shipping_fee=50)
    assert r.final_price == 100_000


def test_rounding_down():
    # 100,000 + 배송 49 = 100,049 → 100,000
    r = compute_sale_price_unified(100_000, 0.0, 0.0, shipping_fee=49)
    assert r.final_price == 100_000


def test_rounding_unit_custom():
    # 1,000원 단위 버림 — 100,600 → 100,000
    r = compute_sale_price_unified(100_000, 0.0, 0.0, shipping_fee=600,
                                   rounding_unit=1_000)
    assert r.final_price == 100_000


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
    # final 121,000 < 하한 130,000
    r = compute_sale_price_unified(95_000, 0.10, 0.1155,
                                   guardrail=(130_000, 140_000))
    assert r.guardrail_status == 'below'


def test_guardrail_above():
    # final 121,000 >= 상한 121,000 (상한 포함 = above)
    r = compute_sale_price_unified(95_000, 0.10, 0.1155,
                                   guardrail=(100_000, 121_000))
    assert r.guardrail_status == 'above'


# ============ breakdown (산출과정 표시용) ============

def test_breakdown_values():
    r = compute_sale_price_unified(95_000, 0.10, 0.1155, shipping_fee=0)
    b = r.breakdown
    assert b['purchase_price'] == 95_000
    assert b['margin_amount'] == 12_110            # 판매가(121,096) × 0.10
    assert b['subtotal_before_ship'] == 121_096
    assert b['fee_amount'] == 13_987               # round(121,096 × 0.1155)
    assert b['final_price'] == 121_000             # 121,096.24 → 버림 → 121,000


def test_result_type():
    r = compute_sale_price_unified(95_000, 0.10, 0.1155)
    assert isinstance(r, PriceResult)


# ============ [2026-06-02] mode='amount' (마진금액 = 수수료 뒤 실수령) ============

def test_amount_mode_basic():
    # (100,000 + 5,000) / (1 - 0.0945) = 115,958.03 → 115,958 → 100단위 버림 → 115,900
    r = compute_sale_price_unified(
        100_000, 0.0, 0.0945, shipping_fee=0,
        mode='amount', margin_amount=5_000)
    assert r.breakdown['mode'] == 'amount'
    assert r.final_price == 115_900


def test_amount_mode_net_received_equals_amount():
    # 핵심 의미 검증: 수수료(판매가×수수료율) 차감 후 실수령 ≈ 원가 + 마진금액
    fee = 0.0945
    r = compute_sale_price_unified(
        100_000, 0.0, fee, shipping_fee=0, mode='amount', margin_amount=5_000)
    net = r.final_price - r.final_price * fee  # 판매가 - 수수료
    # 라운딩 오차(±100) 내에서 원가+마진금액(105,000) 회수
    assert abs(net - 105_000) < 150


def test_amount_mode_with_shipping():
    # base + 배송비 3,000 = 118,958.03 → 버림 → 118,900
    r = compute_sale_price_unified(
        100_000, 0.0, 0.0945, shipping_fee=3_000,
        mode='amount', margin_amount=5_000)
    assert r.final_price == 118_900


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
    assert r.final_price == 121_000  # rate 모드 값(판매가 대비·버림)


def test_fixed_mode_guardrail():
    r = compute_sale_price_unified(
        95_000, 0.10, 0.1155, mode='fixed', fixed_price=133_900,
        guardrail=(100_000, 130_000))
    assert r.guardrail_status == 'above'  # 133,900 >= 130,000


# ============ rate 모드 — 마진율 = 판매가 대비 (2026-07-20 변경) ============

def test_rate_mode_is_margin_of_price():
    # 판매가 = 원가 / (1 - 수수료율 - 마진율) → 95,000 / (1-0.1155-0.10) = 121,096 → 버림 121,000
    r = compute_sale_price_unified(95_000, 0.10, 0.1155, shipping_fee=0)
    assert r.final_price == 121_000
    assert r.breakdown['mode'] == 'rate'


def test_rate_mode_actual_margin_matches_input_rate():
    # 넣은 마진율이 '판매가 대비 실마진' 과 실제로 맞는지 (버림 오차 범위 안)
    purchase, rate, fee = 95_000, 0.10, 0.1155
    r = compute_sale_price_unified(purchase, rate, fee, shipping_fee=0)
    sell = r.final_price
    actual = (sell * (1 - fee) - purchase) / sell
    assert abs(actual - rate) < 0.001, f'실마진율 {actual:.4%} != 입력 {rate:.2%}'


def test_rate_and_amount_modes_agree():
    # 같은 결과를 노리는 두 모드가 같은 값을 내야 한다.
    #   rate: 판매가 = 원가/(1-수수료-마진율)   amount: 판매가 = (원가+마진금액)/(1-수수료)
    #   마진금액 = 판매가 × 마진율 을 넣으면 두 식은 수학적으로 동일하다.
    purchase, rate, fee = 95_000, 0.10, 0.1155
    by_rate = compute_sale_price_unified(purchase, rate, fee, shipping_fee=0)
    amt = round(by_rate.final_price * rate)
    by_amount = compute_sale_price_unified(
        purchase, 0, fee, mode='amount', margin_amount=amt, shipping_fee=0)
    assert abs(by_rate.final_price - by_amount.final_price) <= 100  # 버림 단위 오차


def test_rate_mode_impossible_when_fee_plus_margin_exceeds_100():
    # 수수료 + 마진율 >= 100% → 성립하는 판매가가 없다. 폴백 금지, 0 으로 막는다.
    r = compute_sale_price_unified(95_000, 0.90, 0.1155, shipping_fee=0)
    assert r.final_price == 0
    assert r.breakdown.get('impossible') is True
    assert '100%' in r.breakdown.get('impossible_reason', '')


def test_rate_mode_shipping_added_on_top():
    base = compute_sale_price_unified(95_000, 0.10, 0.1155, shipping_fee=0).final_price
    with_ship = compute_sale_price_unified(95_000, 0.10, 0.1155, shipping_fee=3_000).final_price
    assert with_ship - base == 3_000


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
    assert r.final_price == 115_900


# ============ 모르는 마켓 = 조용한 폴백 금지 (2026-07-20) ============

def test_unknown_market_raises_instead_of_silent_ss_fallback():
    """'lotteon' 등 정책 없는 마켓을 넣으면 스마트스토어 정책으로 계산되면 안 된다.

    이전엔 _PREFIX_MAP.get(market, 'ss') 라 수수료 6%·마진율 9.45% 로 조용히 계산됐다.
    그 값이 마켓에 올라가면 그대로 금전 손실이다.
    """
    # [2026-07-20] 롯데온·11번가·옥션·G마켓은 정식 지원으로 편입 — 이제 차단 대상이 아니다.
    #   차단해야 하는 건 '정말 모르는' 마켓(오타·신규 마켓 미설정)이다.
    from lemouton.pricing.unified import UnknownMarketPolicyError
    for m in ('ss_typo', 'wemakeprice', '', 'lotte_on'):
        with pytest.raises(UnknownMarketPolicyError):
            resolve_market_policy(_tpl(), m, 'sourcing')


def test_known_markets_still_resolve():
    for m in ('ss', 'smartstore', 'coupang', 'cp'):
        pol = resolve_market_policy(_tpl(), m, 'sourcing')
        assert pol['fee_rate'] > 0


def test_new_market_fee_defaults_are_owner_specified():
    """새 마켓 수수료 기본값 = 사장님이 준 값(13%). 내가 지어낸 값이 아니다.

    2026-07-20 사장님: 롯데온 13+α · 11번가 13 · 옥션/G마켓 13+α.
    '+α' 는 실정산에서 더 뗄 수 있다는 뜻이라, 화면에서 조정 가능해야 한다.
    """
    from lemouton.templates.models import PriceTemplate
    cols = {c.name: c for c in PriceTemplate.__table__.columns}
    for name in ('lotteon_fee_rate', 'eleven11_fee_rate',
                 'auction_fee_rate', 'gmarket_fee_rate'):
        assert name in cols, f'{name} 컬럼이 없다'
        assert cols[name].default.arg == 0.13, f'{name} 기본값이 13% 가 아니다'


# ============ 6개 마켓 전부 3가지 책정 방식 (2026-07-20) ============

_ALL_MARKETS = ('ss', 'coupang', 'lotteon', 'eleven11', 'auction', 'gmarket')


def test_all_markets_resolve_policy():
    """스스·쿠팡뿐 아니라 4개 마켓도 정책이 나와야 한다."""
    for m in _ALL_MARKETS:
        for side in ('sourcing', 'purchase'):
            pol = resolve_market_policy(None, m, side)
            assert pol['fee_rate'] > 0, f'{m}/{side} 수수료 없음'
            assert pol['mode'] in ('rate', 'amount', 'fixed')


def test_new_market_default_fees_match_owner_spec():
    """사장님 지정: 롯데온 13+α · 11번가 13 · 옥션/G마켓 13+α → 기본 13%."""
    for m in ('lotteon', 'eleven11', 'auction', 'gmarket'):
        assert resolve_market_policy(None, m, 'sourcing')['fee_rate'] == 0.13
    assert resolve_market_policy(None, 'ss', 'sourcing')['fee_rate'] == 0.06
    assert resolve_market_policy(None, 'coupang', 'sourcing')['fee_rate'] == 0.1155


def test_all_markets_support_three_modes():
    """마진율·마진금액·지정가 셋 다 마켓 상관없이 동작한다."""
    for m in _ALL_MARKETS:
        r = compute_market_price(_tpl(), m, 'sourcing', 100_000)
        assert r.final_price > 0, f'{m} rate 모드 실패'
        by_amount = compute_sale_price_unified(
            100_000, 0, resolve_market_policy(None, m, 'sourcing')['fee_rate'],
            mode='amount', margin_amount=5_000)
        assert by_amount.final_price > 100_000
        by_fixed = compute_sale_price_unified(
            100_000, 0, 0.13, mode='fixed', fixed_price=150_000)
        assert by_fixed.final_price == 150_000


def test_all_markets_have_full_column_set():
    """컬럼 이름 규칙이 같아야 resolve_market_policy 가 분기 없이 읽는다."""
    from lemouton.templates.models import PriceTemplate
    cols = {c.name for c in PriceTemplate.__table__.columns}
    for m in _ALL_MARKETS:
        for c in ('fee_rate', 'mode_sourcing', 'rate_sourcing', 'amount_sourcing',
                  'external_sale_price', 'mode_purchase', 'rate_purchase',
                  'amount_purchase', 'boxhero_sale_price', 'delivery_fee',
                  'pricing_policy', 'unify_rule'):
            assert f'{m}_{c}' in cols, f'{m}_{c} 컬럼 없음'


def test_new_market_fields_are_saveable():
    """저장 화이트리스트에 빠지면 화면에서 눌러도 조용히 안 저장된다."""
    import io as _io
    import pathlib
    src = pathlib.Path(__file__).resolve().parents[2] / 'webapp' / 'routes' / 'api.py'
    body = _io.open(src, encoding='utf-8').read()
    assert "for _p in ('lotteon', 'eleven11', 'auction', 'gmarket')" in body
    for c in ('fee_rate', 'mode_sourcing', 'rate_purchase', 'unify_rule'):
        assert f"'{c}'" in body, f'{c} 가 화이트리스트에 없음'
