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
    # [2026-07-19] 정렬이 분류(정액→정률)로 바뀌어 줄 순서만 뒤집힘 — 최종가 92,070 동일.
    #   청구할인 7% → 100,000-7,000=93,000 / 적립 1% → 93,000-930=92,070 → 백원버림
    assert res['final_price'] == 92000
    assert [(s['name'], s['deduct'], s['base_after']) for s in res['steps']] == [
        ('삼성카드 7% 청구할인', 7000, 93000),
        ('삼성셀렉트 적립 1%', 930, 92070),
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
    # [2026-07-19] 정렬을 이름('적립' 포함 여부)이 아니라 분류(정액→정률)로 바꿈.
    #   정률끼리는 순서가 최종가를 바꾸지 않는다 — 아래는 줄 순서만 갱신.
    assert names == ['삼성카드 10% 청구할인', '삼성셀렉트 적립 1%'], (
        '정률끼리는 등록 순서대로 — 이름은 순서에 관여하지 않는다')
    # [2026-07-19] 줄 순서만 뒤집힘 — 200,000 ×(1-0.10)=180,000 ×(1-0.01)=178,200 동일.
    assert [(s['deduct'], s['base_after']) for s in res['steps']] == [
        (20000, 180000), (1800, 178200),
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


# ────────────────────────────────────────────────────────────────────────────
# ⑥ 캐시백은 결제카드와 **별개 축** — 택1 그룹에 들어가면 안 된다
#
# 확정 계산 모델(2026-06-07 최종매입가 설계 §4):
#     표면가 → 정액 → 정률 → 네이버페이 적립
#       → 유입경로 택1: N쇼핑경유 ↔ OK캐시백
#       → 결제카드 택1: 카드 적립율 + 카드 청구할인
# 유입경로(캐시백)와 결제카드는 **다른 축**이고 둘 다 적용된다. 설계 §4 의 세트
# 제약은 ①결제수단 택1 ②naver_via ⟹ 캐시백 off **둘뿐**이다. 캐시백⟷카드 택1은 없다.
#
# 실측 사고: OK캐시백 2.5% 가 통째로 사라져 매입가가 2,500원 과대로 나왔다.
# ────────────────────────────────────────────────────────────────────────────

def test_cashback_and_card_are_both_deducted():
    """★핵심 RED — 캐시백 2.5% 와 카드 청구할인 7% 가 **둘 다** 빠져야 한다.

    하나만 빠지면 실패. 100,000 표면가에서
        -2,500(캐시백 2.5%)          → 97,500
        -975  (삼성셀렉트 적립 1%)    → 96,525
        -6,756(삼성카드 청구할인 7%)  → 89,769 → 백원버림 89,700
    캐시백이 결제 택1로 삼켜지면 92,000 이 나온다(= 2,300 과대).
    """
    eff = [
        ('tpl', Row(id=1, name='OK캐시백 적립', value=0.025, apply_mode='cashback')),
        ('tpl', Row(id=2, name='삼성카드 7% 청구할인', value=0.07,
                    apply_mode='payment', pay_method='samsung_select')),
    ]
    res, info = _run(eff, [SAMSUNG], sale_price=100000, floor=None)

    assert info['mode'] == 'tagged'
    names = [s['name'] for s in res['steps']]
    assert 'OK캐시백 적립' in names, '캐시백이 결제 택1에 삼켜졌다(매입가 과대)'
    assert '삼성카드 7% 청구할인' in names, '카드 청구할인이 빠졌다'
    # [2026-07-19] 정렬을 이름('적립' 포함 여부)이 아니라 분류(정액→정률)로 바꿈.
    #   정률끼리는 순서가 최종가를 바꾸지 않는다 — 아래는 줄 순서만 갱신.
    # [2026-07-19] 정렬이 이름 대신 분류(정액→정률) — 최종가 동일.
    assert names == ['OK캐시백 적립', '삼성카드 7% 청구할인', '삼성셀렉트 적립 1%']
    assert [(s['deduct'], s['base_after']) for s in res['steps']] == [
        (2500, 97500), (6825, 90675), (906, 89769),   # [2026-07-19] 줄 순서만 변경
    ]
    assert res['final_price'] == 89700


def test_cashback_by_category_tag_also_escapes_payment_group():
    """apply_mode 미태깅 legacy 행 — category='캐시백' 이 근거(backfill 과 동일 기준)."""
    eff = [
        ('tpl', Row(id=1, name='OK캐시백', value=0.025, category='캐시백')),
        ('tpl', Row(id=2, name='삼성카드 7% 청구할인', value=0.07,
                    apply_mode='payment', pay_method='samsung_select')),
    ]
    res, _info = _run(eff, [SAMSUNG], sale_price=100000, floor=None)
    names = [s['name'] for s in res['steps']]
    assert 'OK캐시백' in names and '삼성카드 7% 청구할인' in names


def test_cashback_by_name_only_escapes_payment_group():
    """태그·카테고리 둘 다 없는 legacy 행 — 이름에 '캐시백', 카드사 표기 없음."""
    eff = [
        ('tpl', Row(id=1, name='OK캐시백', value=0.025)),
        ('tpl', Row(id=2, name='삼성카드 7% 청구할인', value=0.07,
                    apply_mode='payment', pay_method='samsung_select')),
    ]
    res, _info = _run(eff, [SAMSUNG], sale_price=100000, floor=None)
    names = [s['name'] for s in res['steps']]
    assert 'OK캐시백' in names and '삼성카드 7% 청구할인' in names


def test_card_named_cashback_stays_in_payment_group():
    """경계 — 이름에 '캐시백' 이 있어도 **카드사 혜택**이면 결제 택1 유지.

    '현대카드 캐시백' 은 현대카드로 결제해야 받는다. 삼성카드 경로에서 같이
    적용하면 물리적으로 불가능한 조합이 되어 **매입가를 실제보다 낮게** 잡는다
    (= 마진 과대 → 판매가 오설정 → 금전 손실). 애매하면 안 깎는 쪽이 안전하다.
    """
    eff = [
        ('tpl', Row(id=1, name='현대카드 캐시백', value=0.025)),
        ('tpl', Row(id=2, name='삼성카드 7% 청구할인', value=0.07,
                    apply_mode='payment', pay_method='samsung_select')),
    ]
    res, _info = _run(eff, [SAMSUNG], sale_price=100000, floor=None)
    names = [s['name'] for s in res['steps']]
    assert not ('현대카드 캐시백' in names and '삼성카드 7% 청구할인' in names), (
        '카드사 캐시백과 타 카드 청구할인이 동시 적용됐다 — 불가능한 조합')


def test_cards_remain_mutually_exclusive():
    """② 카드끼리는 여전히 택1 — 두 카드의 청구할인이 동시에 빠지면 안 된다."""
    eff = [
        ('tpl', Row(id=1, name='삼성카드 7% 청구할인', value=0.07,
                    apply_mode='payment', pay_method='samsung_select')),
        ('tpl', Row(id=2, name='넥슨현대 5% 청구할인', value=0.05,
                    apply_mode='payment', pay_method='nexon_hyundai')),
    ]
    res, _info = _run(eff, CARDS, sale_price=100000, floor=None)
    names = [s['name'] for s in res['steps']]
    assert not ('삼성카드 7% 청구할인' in names and '넥슨현대 5% 청구할인' in names)
    assert res['path']['pay_method'] in ('samsung_select', 'nexon_hyundai')


def test_real_payment_items_still_exclusive_with_cards():
    """③ 진짜 결제수단(무신사머니·카드혜택가)은 카드와 택1 유지."""
    eff = [
        ('dyn', Row(id=-1, name='SSG 카드혜택가', btype='amount', value=3000.0)),
        ('tpl', Row(id=2, name='삼성카드 7% 청구할인', value=0.07,
                    apply_mode='payment', pay_method='samsung_select')),
    ]
    res, _info = _run(eff, [SAMSUNG], sale_price=100000, floor=None)
    names = [s['name'] for s in res['steps']]
    assert not ('SSG 카드혜택가' in names and '삼성카드 7% 청구할인' in names)

    eff2 = [
        ('dyn', Row(id=-1, name='무신사머니 결제 적립', btype='amount', value=2400.0)),
        ('tpl', Row(id=2, name='삼성카드 7% 청구할인', value=0.07,
                    apply_mode='payment', pay_method='samsung_select')),
    ]
    res2, _i2 = _run(eff2, [SAMSUNG], sale_price=100000, floor=None)
    names2 = [s['name'] for s in res2['steps']]
    assert not ('무신사머니 결제 적립' in names2 and '삼성카드 7% 청구할인' in names2)


def test_naver_via_still_disables_cashback():
    """④ 세트 제약② 유지 — naver_via 경로에서는 캐시백이 꺼진다."""
    eff = [
        ('tpl', Row(id=1, name='OK캐시백 적립', value=0.025, apply_mode='cashback')),
        ('tpl', Row(id=2, name='네이버경유 쿠폰', value=0.08, channel='naver_via')),
        ('tpl', Row(id=3, name='삼성카드 7% 청구할인', value=0.07,
                    apply_mode='payment', pay_method='samsung_select')),
    ]
    res, _info = _run(eff, [SAMSUNG], sale_price=100000, floor=None)

    assert res['path']['naver_via'] is True
    names = [s['name'] for s in res['steps']]
    assert 'OK캐시백 적립' not in names, 'naver_via 경로인데 캐시백이 살아있다'
    assert '네이버경유 쿠폰' in names
    assert res['final_price'] == 84700


def test_naver_via_disables_untagged_cashback_too():
    """legacy(태그 없는) 캐시백도 캐시백 축으로 정규화돼 제약②를 받는다."""
    eff = [
        ('tpl', Row(id=1, name='OK캐시백', value=0.025, category='캐시백')),
        ('tpl', Row(id=2, name='네이버경유 쿠폰', value=0.08, channel='naver_via')),
        ('tpl', Row(id=3, name='삼성카드 7% 청구할인', value=0.07,
                    apply_mode='payment', pay_method='samsung_select')),
    ]
    res, _info = _run(eff, [SAMSUNG], sale_price=100000, floor=None)
    if res['path']['naver_via']:
        assert 'OK캐시백' not in [s['name'] for s in res['steps']]


def test_cashback_with_no_card_candidates_is_untouched():
    """⑤ 카드 후보 0개 = legacy 경로 — 캐시백이 있어도 기존 동작 그대로."""
    eff = [('tpl', Row(id=1, name='OK캐시백 적립', value=0.025, apply_mode='cashback'))]
    res, info = _run(eff, [], sale_price=100000, floor=None)
    assert info == {'mode': 'legacy', 'candidates': [], 'floor': False}
    assert res['path'] is None
    assert res['final_price'] == 97500
