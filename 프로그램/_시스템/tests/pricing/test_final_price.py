"""Unit tests for lemouton.pricing.final_price.compute_final_price.

Pure function — no DB, no Flask context needed.
"""
import pytest
from lemouton.pricing.final_price import compute_final_price


class B:
    """Minimal fake benefit item."""
    def __init__(self, *, id=1, name='', btype='rate', value=0.0, enabled=True, category=None):
        self.id = id
        self.benefit_name = name
        self.benefit_type = btype
        self.value = value
        self.enabled = enabled
        self.category = category


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
