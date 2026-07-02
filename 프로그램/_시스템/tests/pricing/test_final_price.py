"""Unit tests for lemouton.pricing.final_price.compute_final_price.

Pure function — no DB, no Flask context needed.
"""
import pytest
from lemouton.pricing.final_price import compute_final_price


class B:
    """Minimal fake benefit item (legacy — no tagged fields)."""
    def __init__(self, *, id=1, name='', btype='rate', value=0.0, enabled=True, category=None):
        self.id = id
        self.benefit_name = name
        self.benefit_type = btype
        self.value = value
        self.enabled = enabled
        self.category = category


class T:
    """Tagged fake benefit item — supports apply_mode/pay_method/channel."""
    def __init__(self, *, id=1, name='', btype='rate', value=0.0, enabled=True,
                 category=None, apply_mode=None, pay_method=None, channel=None):
        self.id = id
        self.benefit_name = name
        self.benefit_type = btype
        self.value = value
        self.enabled = enabled
        self.category = category
        self.apply_mode = apply_mode
        self.pay_method = pay_method
        self.channel = channel


# ── Test 1: 순차 누적 정률 ──────────────────────────────────────────────────────
def test_sequential_rate_deductions():
    """sale=10000, 두 개 rate 10% enabled → 10000→9000→8100."""
    items = [
        ('tpl', B(id=1, name='할인A', btype='rate', value=0.10)),
        ('tpl', B(id=2, name='할인B', btype='rate', value=0.10)),
    ]
    result = compute_final_price(10000, items)
    assert result['final_price'] == 8100
    assert result['sale_price'] == 10000.0
    assert len(result['steps']) == 2
    assert result['steps'][0]['base_after'] == 9000
    assert result['steps'][1]['base_after'] == 8100


# ── Test 2: 정액 차감 ───────────────────────────────────────────────────────────
def test_amount_deduction():
    """sale=10000, amount 3000 enabled → final 7000."""
    items = [('tpl', B(id=1, name='쿠폰', btype='amount', value=3000.0))]
    result = compute_final_price(10000, items)
    assert result['final_price'] == 7000
    assert result['steps'][0]['deduct'] == 3000


# ── Test 3: 카테고리 정렬 순서 ─────────────────────────────────────────────────
def test_category_sort_order():
    """amount → %적립 → %할인 순서로 deduct 돼야 한다."""
    # 의도적으로 순서를 뒤집어 입력
    items = [
        ('tpl', B(id=3, name='카드할인', btype='rate', value=0.05)),       # 카테고리 2 (rate 비적립)
        ('tpl', B(id=2, name='등급적립', btype='rate', value=0.10)),       # 카테고리 1 (rate 적립)
        ('tpl', B(id=1, name='즉시할인쿠폰', btype='amount', value=1000.0)), # 카테고리 0 (amount)
    ]
    result = compute_final_price(10000, items)
    names = [s['name'] for s in result['steps']]
    assert names == ['즉시할인쿠폰', '등급적립', '카드할인'], f"정렬 순서 오류: {names}"
    # 검산: 10000 -1000=9000, -900=8100, -405=7695
    assert result['steps'][0]['base_after'] == 9000
    assert result['steps'][1]['base_after'] == 8100
    assert result['steps'][2]['base_after'] == 7695


# ── Test 4: 결제 택1 ────────────────────────────────────────────────────────────
def test_payment_mutual_exclusion():
    """네이버 제외 결제 수단 2개 → 차감 큰 1개만 남김."""
    # 카드A: rate 0.05 → approx_deduct = 10000*0.05=500
    # 카드B: rate 0.10 → approx_deduct = 10000*0.10=1000  ← winner
    card_a = B(id=1, name='카드A 캐시백', btype='rate', value=0.05)
    card_b = B(id=2, name='카드B 캐시백', btype='rate', value=0.10)
    items = [('tpl', card_a), ('tpl', card_b)]
    result = compute_final_price(10000, items)
    # items_used 에서 enabled 확인
    used = {iu['name']: iu['enabled'] for iu in result['items_used']}
    assert used['카드B 캐시백'] is True
    assert used['카드A 캐시백'] is False
    # 네이버페이는 택1 그룹 제외 → 항상 누적
    naver = B(id=3, name='네이버페이 적립', btype='rate', value=0.01)
    items2 = [('tpl', card_a), ('tpl', card_b), ('tpl', naver)]
    result2 = compute_final_price(10000, items2)
    used2 = {iu['name']: iu['enabled'] for iu in result2['items_used']}
    assert used2['네이버페이 적립'] is True   # 네이버는 제외되지 않음
    assert used2['카드B 캐시백'] is True
    assert used2['카드A 캐시백'] is False


# ── Test 5: base_override ───────────────────────────────────────────────────────
def test_base_override():
    """base_override=39000, sale_price=50000 → calc 39000 기준, sale_price 반환 39000."""
    items = [('tpl', B(id=1, name='할인', btype='rate', value=0.10))]
    result = compute_final_price(50000, items, base_override=39000)
    assert result['sale_price'] == 39000.0
    assert result['final_price'] == 39000 - int(39000 * 0.10)  # 35100


# ── Test 6: card-off ────────────────────────────────────────────────────────────
def test_card_off_disables_issuer_benefit():
    """card_enabled=False + card_issuer='현대카드' → '현대카드 캐시백' disabled_by_card_off."""
    items = [
        ('tpl', B(id=1, name='현대카드 캐시백', btype='rate', value=0.10)),
        ('tpl', B(id=2, name='등급적립', btype='rate', value=0.05)),
    ]
    result = compute_final_price(10000, items, card_enabled=False, card_issuer='현대카드')
    used = {iu['name']: iu for iu in result['items_used']}
    assert used['현대카드 캐시백']['disabled_by_card_off'] is True
    assert used['현대카드 캐시백']['enabled'] is False
    assert used['등급적립']['enabled'] is True
    # 현대카드 항목은 차감 안 됨 → base = 10000 * (1 - 0.05) = 9500
    assert result['final_price'] == 9500


# ── Test 7: 음수 방지 ──────────────────────────────────────────────────────────
def test_no_negative_final_price():
    """amount 99999 on base 10000 → final 0 (deduct capped at base)."""
    items = [('tpl', B(id=1, name='대형쿠폰', btype='amount', value=99999.0))]
    result = compute_final_price(10000, items)
    assert result['final_price'] == 0
    assert result['steps'][0]['deduct'] == 10000  # min(99999, 10000)


# ══════════════════════════════════════════════════════════════════════════════
# M2b 신규 테스트 (tagged-mode + preapplied)
# ══════════════════════════════════════════════════════════════════════════════

# ── Test 8: legacy unchanged (태그 없음 → path is None) ────────────────────────
def test_legacy_no_tags_path_is_none():
    """태그 없는 항목 집합 → path=None, 결과 동일."""
    items = [
        ('tpl', B(id=1, name='할인A', btype='rate', value=0.10)),
        ('tpl', B(id=2, name='할인B', btype='rate', value=0.05)),
    ]
    result = compute_final_price(10000, items)
    assert result['path'] is None
    # 10000 → 9000 → 8550 → 백원 버림 → 8500
    assert result['final_price'] == 8500


# ── Test 9: preapplied skip ────────────────────────────────────────────────────
def test_preapplied_skip():
    """apply_mode='preapplied' 항목은 차감 안 되고 items_used 에 preapplied=True 기록."""
    pre = T(id=1, name='선반영쿠폰', btype='amount', value=5000.0,
            apply_mode='preapplied')
    normal = T(id=2, name='일반할인', btype='rate', value=0.10)
    items = [('tpl', pre), ('tpl', normal)]
    result = compute_final_price(10000, items)
    # 선반영 항목은 차감 없음 → base 그대로
    assert result['final_price'] == 9000  # 10000 * (1-0.10) = 9000
    # items_used: preapplied=True
    used = {iu['name']: iu for iu in result['items_used']}
    assert used['선반영쿠폰'].get('preapplied') is True
    # steps 에 선반영 항목 없음
    step_names = [s['name'] for s in result['steps']]
    assert '선반영쿠폰' not in step_names
    assert '일반할인' in step_names


# ── Test 10: 제휴카드↔네이버페이 택1 (path min) ────────────────────────────────
def test_payment_affiliate_vs_naver_pay_min():
    """affiliate_card(10%) vs naver_pay(5%) — affiliate_card 가 더 싸므로 선택."""
    aff = T(id=1, name='제휴카드결제', btype='rate', value=0.10,
            apply_mode='payment', pay_method='affiliate_card')
    naver = T(id=2, name='네이버페이결제', btype='rate', value=0.05,
              apply_mode='payment', pay_method='naver_pay')
    # 둘 다 tagged → tagged mode
    items = [('tpl', aff), ('tpl', naver)]
    result = compute_final_price(10000, items)
    assert result['path']['pay_method'] == 'affiliate_card'
    # 10000 * (1-0.10) = 9000
    assert result['final_price'] == 9000


# ── Test 11: naver_via ↔ cashback exclusion ────────────────────────────────────
def test_naver_via_cashback_exclusion():
    """캐시백(2%) + 네이버경유 쿠폰(8%) — via=True: cashback off, coupon on → 9200.
    via=False: cashback on, coupon off → 9800. min → via=True (9200) 선택."""
    cashback = T(id=1, name='캐시백', btype='rate', value=0.02, apply_mode='cashback')
    coupon = T(id=2, name='네이버경유쿠폰', btype='rate', value=0.08, channel='naver_via')
    items = [('tpl', cashback), ('tpl', coupon)]
    result = compute_final_price(10000, items)
    # via=True → deduct 8% → 9200
    assert result['final_price'] == 9200
    assert result['path']['naver_via'] is True
    # steps 에 캐시백 없어야 함 (via=True 경로 선택 → cashback 비활성)
    step_names = [s['name'] for s in result['steps']]
    assert '캐시백' not in step_names
    assert '네이버경유쿠폰' in step_names


# ── Test 12: 무결제 경로 포함 ───────────────────────────────────────────────────
def test_no_payment_path_included():
    """affiliate_card 결제항목 1개 + 일반할인 5% → affiliate_card 경로가 더 싸면 선택."""
    pay = T(id=1, name='제휴카드결제', btype='rate', value=0.10,
            apply_mode='payment', pay_method='affiliate_card')
    discount = T(id=2, name='일반할인', btype='rate', value=0.05)
    items = [('tpl', pay), ('tpl', discount)]
    result = compute_final_price(10000, items)
    # 무결제(None): 일반할인만 → 9500
    # affiliate_card: 결제10% + 일반할인5% → 10000*0.9*0.95 = 8550 → 백원 버림 → 8500
    assert result['final_price'] == 8500
    assert result['path']['pay_method'] == 'affiliate_card'
