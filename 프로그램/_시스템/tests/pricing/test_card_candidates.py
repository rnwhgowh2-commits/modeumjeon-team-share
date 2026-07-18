# -*- coding: utf-8 -*-
"""결제카드 다중 후보 (Phase 1B M1-4) — 최유리 카드 자동 선택.

검증 5종 (작업 지시):
  ① 현대카드만 있을 때 기존과 동일
  ② 삼성카드 7% 청구할인이 있으면 현대카드 대신 삼성 채택
  ③ 대안이 현대카드보다 불리하면 현대카드 채택 (플로어)
  ④ 적립율·청구할인 둘 다 차감되는지
  ⑤ 카드 후보 0개일 때 안 터지는지
"""
import pytest

from lemouton.pricing.card_candidates import (
    HYUNDAI_FLOOR_KEY, apply_card_candidates,
)
from lemouton.pricing.final_price import compute_final_price


# ────────────────────────────────────────────────────────────────────────────
# 더블 — PurchaseCard / 혜택 행
# ────────────────────────────────────────────────────────────────────────────

class Card:
    def __init__(self, key, label, accrual_rate, is_hyundai_default=False, active=True):
        self.key = key
        self.label = label
        self.accrual_rate = accrual_rate
        self.is_hyundai_default = is_hyundai_default
        self.active = active


class Row:
    """SourceBenefitTemplate / OptionBenefitOverride 유사 행."""

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


class Floor:
    """api_benefits 가 만드는 레거시 현대카드 항목(_DynBenefit) 형태."""

    def __init__(self, *, name='현대카드 2.73% (청구할인 fallback)',
                 btype='rate', value=0.0273, enabled=True):
        self.id = -1
        self.benefit_name = name
        self.benefit_type = btype
        self.value = value
        self.enabled = enabled
        self.sort_order = 999
        self.template_id = None


NEXON = Card('nexon_hyundai', '넥슨현대카드', 0.027, is_hyundai_default=True)
SAMSUNG = Card('samsung_select', '삼성셀렉트', 0.01)
CARDS = [NEXON, SAMSUNG]


def _run(effective, cards, *, sale_price=100000, floor=None, **kw):
    eff, info = apply_card_candidates(effective, cards, floor=floor)
    return compute_final_price(sale_price, eff, **kw), info


# ────────────────────────────────────────────────────────────────────────────
# ① 현대카드만 — 청구할인 행이 없으면 기존(legacy) 동작 그대로
# ────────────────────────────────────────────────────────────────────────────

def test_hyundai_only_matches_legacy_exactly():
    """청구할인 행 0건 → legacy 경로 유지, 기준선(회귀 스냅샷)과 완전 동일."""
    res, info = _run([], CARDS, sale_price=100000, floor=Floor())

    assert info['mode'] == 'legacy'
    assert info['candidates'] == []
    # tests/pricing/test_final_price_regression.py::legacy_floor_hyundai_only 기준선
    assert res['final_price'] == 97200
    assert res['path'] is None
    assert [(s['name'], s['deduct'], s['base_after']) for s in res['steps']] == [
        ('현대카드 2.73% (청구할인 fallback)', 2730, 97270),
    ]


def test_hyundai_only_lotteon_shape_matches_legacy():
    """롯데온 실전 형태도 그대로 — 적립·네이버페이·현대카드 3단 누적."""
    eff = [
        ('tpl', Row(id=1, name='롯데오너스 적립', value=0.05)),
        ('tpl', Row(id=2, name='네이버페이 적립', value=0.01)),
    ]
    res, info = _run(eff, CARDS, sale_price=129000, floor=Floor())

    assert info['mode'] == 'legacy'
    # legacy_lotteon_shape 기준선과 동일
    assert res['final_price'] == 118000
    assert res['path'] is None


def test_hyundai_only_ssg_shape_matches_legacy():
    """SSG 실전 형태 — 카드혜택가(정액)와 현대카드가 legacy 택1 그대로 경합."""
    eff = [
        ('dyn', Row(id=-1, name='SSG MONEY 적립', value=0.01)),
        ('dyn', Row(id=-1, name='SSG 카드혜택가', btype='amount', value=3000.0)),
    ]
    res, info = _run(eff, CARDS, sale_price=98000, floor=Floor())

    assert info['mode'] == 'legacy'
    # legacy_ssg_card_benefit_shape 기준선과 동일 (카드혜택가 3,000 이 택1 승자)
    assert res['final_price'] == 94000
    assert res['path'] is None
    assert [(s['name'], s['deduct'], s['base_after']) for s in res['steps']] == [
        ('SSG 카드혜택가', 3000, 95000),
        ('SSG MONEY 적립', 950, 94050),
    ]


def test_hyundai_only_musinsa_shape_matches_legacy():
    """무신사 실전 형태 — 상품쿠폰·등급적립 정액 + 현대카드 2.73%."""
    eff = [
        ('dyn', Row(id=-1, name='상품쿠폰', btype='amount', value=5000.0)),
        ('dyn', Row(id=-1, name='등급적립', btype='amount', value=1780.0)),
    ]
    res, info = _run(eff, CARDS, sale_price=89000,
                     floor=Floor(name='현대카드 2.73% (무신사머니 미적용 시)'))

    assert info['mode'] == 'legacy'
    # legacy_musinsa_shape 기준선과 동일
    assert res['final_price'] == 79900
    assert res['path'] is None


def test_hyundai_only_musinsa_money_active_matches_legacy():
    """무신사머니가 잡혀 현대카드 플로어가 enabled=False 인 형태도 동일."""
    eff = [('dyn', Row(id=-1, name='무신사머니 결제 적립', btype='amount', value=2400.0))]
    res, info = _run(eff, CARDS, sale_price=89000,
                     floor=Floor(name='현대카드 2.73% (무신사머니 미적용 시)',
                                 enabled=False))

    assert info['mode'] == 'legacy'
    # legacy_musinsa_money_active 기준선과 동일
    assert res['final_price'] == 86600
    assert res['path'] is None


# ────────────────────────────────────────────────────────────────────────────
# ② 삼성카드 7% 청구할인이 있으면 현대카드 대신 삼성 채택
# ────────────────────────────────────────────────────────────────────────────

def test_samsung_billing_discount_beats_hyundai_floor():
    eff = [('tpl', Row(id=1, name='삼성카드 7% 청구할인', value=0.07,
                       apply_mode='payment', pay_method='samsung_select'))]
    res, info = _run(eff, CARDS, sale_price=100000, floor=Floor())

    assert info['mode'] == 'tagged'
    assert res['path']['pay_method'] == 'samsung_select'
    # 적립 1% → 100,000-1,000=99,000 / 청구할인 7% → 99,000-6,930=92,070 → 백원버림
    assert res['final_price'] == 92000
    assert [(s['name'], s['deduct'], s['base_after']) for s in res['steps']] == [
        ('삼성셀렉트 적립 1%', 1000, 99000),
        ('삼성카드 7% 청구할인', 6930, 92070),
    ]
    # 현대카드 플로어는 채택되지 않았지만 후보로는 존재했다
    assert HYUNDAI_FLOOR_KEY not in (res['path']['pay_method'],)


# ────────────────────────────────────────────────────────────────────────────
# ③ 대안이 불리하면 현대카드 채택 (플로어)
# ────────────────────────────────────────────────────────────────────────────

def test_worse_alternative_falls_back_to_hyundai_floor():
    """삼성 청구할인 0.5% → 적립 1% 포함해도 현대카드 2.73% 를 못 이긴다."""
    eff = [('tpl', Row(id=1, name='삼성카드 0.5% 청구할인', value=0.005,
                       apply_mode='payment', pay_method='samsung_select'))]
    res, info = _run(eff, CARDS, sale_price=100000, floor=Floor())

    assert info['mode'] == 'tagged'
    assert res['path']['pay_method'] == HYUNDAI_FLOOR_KEY
    # 플로어가 채택 = 기존 현대카드 단독일 때와 같은 금액
    assert res['final_price'] == 97200
    assert [(s['name'], s['deduct'], s['base_after']) for s in res['steps']] == [
        ('현대카드 2.73% (청구할인 fallback)', 2730, 97270),
    ]


def test_hyundai_floor_survives_even_with_no_billing_row_of_its_own():
    """현대카드는 자기 청구할인 행이 없어도 항상 후보로 남는다."""
    eff = [('tpl', Row(id=1, name='삼성카드 0.1% 청구할인', value=0.001,
                       apply_mode='payment', pay_method='samsung_select'))]
    _res, info = _run(eff, CARDS, sale_price=100000, floor=Floor())
    assert info['floor'] is True
    assert 'samsung_select' in info['candidates']


# ────────────────────────────────────────────────────────────────────────────
# ④ 적립율·청구할인 둘 다 차감
# ────────────────────────────────────────────────────────────────────────────

def test_accrual_and_billing_discount_are_both_deducted():
    """같은 카드의 적립율과 청구할인이 **함께**, 순차 누적으로 빠지는지."""
    eff = [('tpl', Row(id=1, name='삼성카드 10% 청구할인', value=0.10,
                       apply_mode='payment', pay_method='samsung_select'))]
    res, _info = _run(eff, [SAMSUNG], sale_price=200000, floor=None)

    names = [s['name'] for s in res['steps']]
    assert names == ['삼성셀렉트 적립 1%', '삼성카드 10% 청구할인'], (
        '적립이 먼저, 청구할인이 나중(직전 잔액 기준)이어야 한다')
    # 200,000 ×(1-0.01)=198,000 ×(1-0.10)=178,200
    assert [(s['deduct'], s['base_after']) for s in res['steps']] == [
        (2000, 198000), (19800, 178200),
    ]
    assert res['final_price'] == 178200


def test_card_without_billing_row_is_candidate_by_accrual_alone():
    """청구할인 행이 없는 카드도 적립율만으로 후보(청구할인 0)."""
    high = Card('kbank', '케이뱅크', 0.30)  # 적립율만으로 압도적
    eff = [('tpl', Row(id=1, name='삼성카드 1% 청구할인', value=0.01,
                       apply_mode='payment', pay_method='samsung_select'))]
    res, info = _run(eff, [SAMSUNG, high], sale_price=100000, floor=None)

    assert 'kbank' in info['candidates']
    assert res['path']['pay_method'] == 'kbank'
    assert res['final_price'] == 70000


# ────────────────────────────────────────────────────────────────────────────
# ⑤ 카드 후보 0개 — 안 터지는지
# ────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize('cards', [None, []], ids=['none', 'empty'])
def test_no_cards_does_not_explode(cards):
    """PurchaseCard 테이블이 비었거나 로드 실패해도 기존 계산이 그대로 돈다."""
    eff = [('tpl', Row(id=1, name='할인쿠폰', value=0.10))]
    res, info = _run(eff, cards, sale_price=100000, floor=Floor())

    assert info['mode'] == 'legacy'
    assert res['path'] is None
    # 100,000 -2,730(현대) ... 정렬상 '쿠폰'(할인)과 현대카드 모두 %할인 그룹
    assert res['final_price'] > 0
    assert len(res['steps']) == 2


def test_no_cards_and_no_floor_is_untouched():
    eff = [('tpl', Row(id=1, name='할인쿠폰', value=0.10))]
    res, info = _run(eff, [], sale_price=100000, floor=None)
    assert info == {'mode': 'legacy', 'candidates': [], 'floor': False}
    assert res['final_price'] == 90000


def test_orphan_pay_method_does_not_enter_tagged_mode():
    """PurchaseCard 에 없는 pay_method 값은 카드 청구할인으로 안 친다(오탐 방지)."""
    eff = [('tpl', Row(id=1, name='제휴카드결제', value=0.10,
                       apply_mode='payment', pay_method='affiliate_card'))]
    _res, info = apply_card_candidates(eff, CARDS, floor=Floor())
    assert info['mode'] == 'legacy'


# ────────────────────────────────────────────────────────────────────────────
# 입력 불변 — 공유 ORM 객체를 변형하지 않는다 (bulk 오염 방지)
# ────────────────────────────────────────────────────────────────────────────

def test_does_not_mutate_input_items():
    row = Row(id=1, name='SSG 카드혜택가', btype='amount', value=3000.0)
    billing = Row(id=2, name='삼성카드 7% 청구할인', value=0.07,
                  apply_mode='payment', pay_method='samsung_select')
    src = [('tpl', row), ('tpl', billing)]
    before = [(r.apply_mode, r.pay_method, r.enabled) for r in (row, billing)]

    out, info = apply_card_candidates(src, CARDS, floor=Floor())

    assert info['mode'] == 'tagged'
    assert [(r.apply_mode, r.pay_method, r.enabled) for r in (row, billing)] == before
    assert len(src) == 2, 'effective 원본 리스트도 그대로여야 한다'
    assert out is not src
