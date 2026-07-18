"""입력 객체 불변성 회귀 — compute_final_price 는 남의 객체를 변형하면 안 된다.

배경
----
`_compute_legacy` 의 결제 택1이 `it.enabled = False` 로 **호출자의 객체를 직접
변형**했다. 실제 사고 경로:

  api_benefits.py::bulk_breakdowns 가 `_build_breakdown_cache` 로 캐시를 1회 만들고
  (캐시의 tpl_by_src 에는 SourceBenefitTemplate ORM 객체가 담긴다),
  **같은 캐시 객체**로 모든 SKU 를 순회 계산한다.
  → 앞선 SKU 계산에서 택1에 진 결제 혜택이 enabled=False 로 영구히 죽고,
    **다음 SKU 부터 그 혜택이 후보에서 통째로 빠진다.**

왜 금전 손실인가 (이 파일의 핵심 시나리오)
------------------------------------------
택1 승자는 **판매가에 따라 바뀐다** (정률 vs 정액 교차점).
  · 제휴카드 5% (rate) / 무신사머니 3000원 (amount)
  · 판매가 40,000 → 카드 2,000 < 머니 3,000  → 승자=머니, 카드가 죽는다
  · 판매가 100,000 → 카드 5,000 > 머니 3,000 → 승자=카드 여야 한다
싼 SKU 를 먼저 계산하면 카드가 영구히 죽어서, 비싼 SKU 는 카드 5,000 을
못 받고 머니 3,000 만 받는다 → **매입가가 실제보다 비싸게 잡힌다.**

같은 파일의 tagged 경로 `_run()` 은 "shared item 객체를 일절 변경하지 않는다"는
주석과 함께 active(kind, it) callable 로 판정하는 올바른 패턴을 이미 쓴다.

주의: items_used 의 `enabled` **보고값**은 바꾸지 않는다 — 택1에서 진 항목은
여전히 `enabled: False` 로 보고돼야 한다. 변형만 없애는 것이지 보고를 바꾸는 게 아니다.
"""
import copy

from lemouton.pricing.final_price import compute_final_price


class B:
    """legacy 아이템 (tagged 필드 없음 → _is_tagged False)."""

    def __init__(self, *, id=1, name='', btype='rate', value=0.0,
                 enabled=True, category=None, apply_mode=None):
        self.id = id
        self.benefit_name = name
        self.benefit_type = btype
        self.value = value
        self.enabled = enabled
        self.category = category
        if apply_mode is not None:
            self.apply_mode = apply_mode


# 결제 혜택 2개(택1 분기 진입) + 비결제 1개.
# ※ '네이버' 가 이름에 들어가면 _is_payment 가 False 라 택1 대상이 아니다.
CARD_ID, MONEY_ID, SALE_ID = 1, 2, 3

CHEAP, PRICEY = 40000, 100000  # 승자가 뒤바뀌는 두 판매가


def _make_effective():
    return [
        ('tpl', B(id=CARD_ID, name='제휴카드 청구할인', btype='rate', value=0.05)),
        ('tpl', B(id=MONEY_ID, name='무신사머니 캐시백', btype='amount', value=3000)),
        ('tpl', B(id=SALE_ID, name='시즌오프 할인', btype='rate', value=0.1)),
    ]


def test_legacy_does_not_mutate_input_enabled():
    """택1에서 진 결제 항목이라도 호출자의 객체는 그대로여야 한다."""
    effective = _make_effective()
    before = {it.id: it.enabled for _k, it in effective}

    compute_final_price(PRICEY, effective)

    after = {it.id: it.enabled for _k, it in effective}
    mutated = {i: (before[i], after[i]) for i in before if before[i] != after[i]}
    assert not mutated, (
        f'입력 항목이 변형됐다 (id: (호출전, 호출후)): {mutated}\n'
        '결제 택1은 로컬 판정으로만 처리해야 하고, 남의 객체를 건드리면 안 된다.'
    )


def test_repeated_calls_are_identical():
    """같은 입력으로 연속 2번 호출 → 결과 완전 동일."""
    effective = _make_effective()

    first = copy.deepcopy(compute_final_price(PRICEY, effective))
    second = copy.deepcopy(compute_final_price(PRICEY, effective))

    assert first == second, (
        '연속 호출 결과가 다르다 = 첫 호출이 입력을 변형했다.\n'
        f"  1회차 final_price={first['final_price']}\n"
        f"  2회차 final_price={second['final_price']}"
    )


def test_shared_cache_across_skus_does_not_poison_later_skus():
    """bulk_breakdowns 재현 — 공유 캐시로 싼 SKU → 비싼 SKU 순회.

    싼 SKU 가 카드 혜택을 죽이면 비싼 SKU 가 카드 5% 를 못 받는다.
    """
    shared = _make_effective()
    compute_final_price(CHEAP, shared)          # 앞선 SKU (여기서 카드가 죽었었다)
    poisoned = compute_final_price(PRICEY, shared)['final_price']

    clean = compute_final_price(PRICEY, _make_effective())['final_price']

    assert poisoned == clean, (
        '앞선 SKU 계산이 공유 혜택 객체를 오염시켰다.\n'
        f'  깨끗한 입력: {clean}\n'
        f'  오염된 입력: {poisoned}  (차이 {poisoned - clean}원 비싸게 잡힘)'
    )


def test_winner_is_chosen_per_sale_price():
    """판매가마다 택1 승자가 독립적으로 정해져야 한다 (정률↔정액 교차)."""
    cheap_used = {u['id']: u['enabled']
                  for u in compute_final_price(CHEAP, _make_effective())['items_used']}
    pricey_used = {u['id']: u['enabled']
                   for u in compute_final_price(PRICEY, _make_effective())['items_used']}

    # 40,000 → 카드 2,000 < 머니 3,000
    assert cheap_used[MONEY_ID] is True, '싼 SKU 승자는 무신사머니'
    assert cheap_used[CARD_ID] is False, '싼 SKU 에서 카드는 택1 패자'
    # 100,000 → 카드 5,000 > 머니 3,000
    assert pricey_used[CARD_ID] is True, '비싼 SKU 승자는 제휴카드'
    assert pricey_used[MONEY_ID] is False, '비싼 SKU 에서 머니는 택1 패자'


def test_losers_still_reported_disabled():
    """변형은 없애되, 택1 패자의 **보고값**은 기존대로 enabled: False."""
    res = compute_final_price(PRICEY, _make_effective())
    by_id = {u['id']: u for u in res['items_used']}

    assert by_id[CARD_ID]['enabled'] is True
    assert by_id[MONEY_ID]['enabled'] is False, '택1 패자는 enabled False 로 보고돼야 한다'
    assert by_id[SALE_ID]['enabled'] is True, '결제 아닌 항목은 택1 영향 없음'
