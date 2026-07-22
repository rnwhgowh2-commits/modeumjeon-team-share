# -*- coding: utf-8 -*-
"""캐시백(유입경로 축) ⟂ 결제카드 축 — 둘은 택1이 아니라 **둘 다 차감**된다.

■ 무엇을 고정하나
  `final_price._compute_legacy` 의 결제 택1 후보 선정에서 **캐시백 항목을 제외**한다.
  기존엔 `_is_payment()` 가 이름의 '캐시백' 을 결제수단으로 판정해, OK캐시백이
  결제카드와 택1로 경합하다 **져서 통째로 안 깎였다**(= 매입가 과대).

■ 근거 (확정 설계)
  docs/superpowers/specs/2026-06-07-최종매입가-계산엔진-design.md §4 의 세트 제약은
  둘뿐이다:
     ① 결제수단 택1 (affiliate_card ⟷ naver_pay)
     ② channel='naver_via' ⟹ 캐시백 비활성
  **캐시백 ⟷ 결제카드 택1은 없다.** 유입경로와 결제카드는 별개 축이고 둘 다 누적 차감.

■ 경계 (일부러 안 고치는 것)
  '현대카드 캐시백' 처럼 **이름에 '카드' 가 붙은** 항목은 캐시백 축으로 빼지 않는다.
  현대카드로 결제해야 받는 혜택이라, 캐시백 축으로 빼면 삼성카드 경로에서도 적용돼
  물리적으로 불가능한 조합이 되고 매입가를 실제보다 낮게 잡는다(= 마진 과대 = 손실).
"""
import pytest

from lemouton.pricing.final_price import compute_final_price


class B:
    """legacy 아이템 (pay_method/channel 없음 → _is_tagged False)."""

    def __init__(self, *, id=1, name='', btype='rate', value=0.0,
                 enabled=True, category=None, apply_mode=None, base_ratio=None):
        self.id = id
        self.benefit_name = name
        self.benefit_type = btype
        self.value = value
        self.enabled = enabled
        self.category = category
        if apply_mode is not None:
            self.apply_mode = apply_mode
        if base_ratio is not None:
            self.base_ratio = base_ratio


class T:
    """tagged 아이템."""

    def __init__(self, *, id=1, name='', btype='rate', value=0.0,
                 enabled=True, category=None, apply_mode=None,
                 pay_method=None, channel=None):
        self.id = id
        self.benefit_name = name
        self.benefit_type = btype
        self.value = value
        self.enabled = enabled
        self.category = category
        self.apply_mode = apply_mode
        self.pay_method = pay_method
        self.channel = channel


def _names(res):
    return [s['name'] for s in res['steps']]


# ────────────────────────────────────────────────────────────────────────────
# ① 캐시백 + 결제카드가 **둘 다** 차감된다 (핵심 — 이번 수정의 RED)
# ────────────────────────────────────────────────────────────────────────────

def test_cashback_and_card_both_deducted():
    """롯데온 실전 형태 — OK캐시백 1.1% + 현대카드 2.73% 가 순차 누적 차감.

    기대 계산 (둘 다 rate·둘 다 '적립' 아님 → 입력 순서 유지):
        100000 → OK캐시백 1.1%  : 1100 차감 → 98900
               → 현대카드 2.73% : int(98900*0.0273)=2699 차감 → 96201
        백원 버림 → 96200
    수정 전에는 택1에서 OK캐시백이 져서 97270 → 96200 이 아니라 97200 이 나온다.
    """
    res = compute_final_price(100000, [
        ('tpl', B(id=1, name='OK캐시백', btype='rate', value=0.011)),
        ('dyn', B(id=-1, name='현대카드 2.73% (청구할인 fallback)',
                  btype='rate', value=0.0273)),
    ])
    assert _names(res) == ['OK캐시백', '현대카드 2.73% (청구할인 fallback)'], (
        '캐시백과 결제카드는 별개 축 — 둘 다 steps 에 남아야 한다. '
        f'실제: {_names(res)}'
    )
    assert res['final_price'] == 96200


def test_cashback_by_category_also_deducted():
    """category='캐시백' (백필 스크립트의 진실 원천) 도 택1에서 빠진다."""
    res = compute_final_price(100000, [
        ('tpl', B(id=1, name='제휴 리워드', btype='rate', value=0.02,
                  category='캐시백')),
        ('dyn', B(id=-1, name='현대카드 2.73%', btype='rate', value=0.0273)),
    ])
    assert _names(res) == ['제휴 리워드', '현대카드 2.73%']


def test_cashback_by_apply_mode_also_deducted():
    """apply_mode='cashback' 명시 태그 — 이름이 무엇이든 캐시백."""
    res = compute_final_price(100000, [
        ('tpl', B(id=1, name='카드 제휴 캐시백', btype='rate', value=0.02,
                  apply_mode='cashback')),
        ('dyn', B(id=-1, name='현대카드 2.73%', btype='rate', value=0.0273)),
    ])
    assert _names(res) == ['카드 제휴 캐시백', '현대카드 2.73%'], (
        '명시 태그(apply_mode=cashback)가 이름 추측보다 우선해야 한다'
    )


# ────────────────────────────────────────────────────────────────────────────
# ② '현대카드 캐시백' 은 택1에 남는다 (물리적으로 불가능한 조합 방지)
# ────────────────────────────────────────────────────────────────────────────

def test_card_named_cashback_stays_in_payment_pick_one():
    """이름에 '카드' 가 있으면 캐시백 축으로 빼지 않는다 — 결제 택1 유지."""
    res = compute_final_price(10000, [
        ('tpl', B(id=1, name='현대카드 캐시백', btype='rate', value=0.10)),
        ('tpl', B(id=2, name='카드 청구할인', btype='amount', value=900.0)),
    ])
    assert _names(res) == ['현대카드 캐시백'], (
        "'현대카드 캐시백' 은 현대카드로 결제해야 받는다 = 결제 택1 그룹. "
        f'실제: {_names(res)}'
    )
    assert res['final_price'] == 9000


@pytest.mark.parametrize('name', [
    '현대카드 캐시백',        # 카드
    '무신사머니 캐시백',      # 무신사머니 — 그 수단으로 결제해야 받는다
    '토스페이 캐시백',        # 페이
    '청구할인 캐시백',        # 청구할인
])
def test_payment_means_named_cashback_stays_in_pick_one(name):
    """이름에 **결제수단 표기**가 있으면 캐시백 축으로 빼지 않는다.

    '무신사머니 캐시백' 을 캐시백으로 빼면 현대카드 결제 경로에서도 함께 적용돼
    물리적으로 불가능한 조합이 된다 → 매입가 과소 → 마진 과대 → 금전 손실.
    """
    res = compute_final_price(10000, [
        ('tpl', B(id=1, name=name, btype='rate', value=0.10)),
        ('tpl', B(id=2, name='카드 청구할인', btype='amount', value=900.0)),
    ])
    assert _names(res) == [name], (
        f"'{name}' 은 결제 택1 그룹에 남아야 한다 — 실제: {_names(res)}"
    )


def test_explicit_payment_tag_beats_cashback_name():
    """apply_mode 가 'cashback' 이 아닌 다른 값이면 이름에 '캐시백' 이 있어도 캐시백 아님."""
    res = compute_final_price(10000, [
        ('tpl', B(id=1, name='제휴 캐시백', btype='rate', value=0.10,
                  apply_mode='deduct')),
        ('tpl', B(id=2, name='카드 청구할인', btype='amount', value=900.0)),
    ])
    # apply_mode='deduct' → 캐시백 아님 → 택1 그룹에 남아 경합, 1000 > 900 이라 승
    assert _names(res) == ['제휴 캐시백']


# ────────────────────────────────────────────────────────────────────────────
# ③ 진짜 결제수단끼리는 여전히 택1
# ────────────────────────────────────────────────────────────────────────────

def test_real_payment_methods_still_mutually_exclusive():
    """무신사머니 vs 카드혜택가 — 캐시백이 아니므로 택1 그대로."""
    res = compute_final_price(100000, [
        ('dyn', B(id=1, name='무신사머니 결제 적립', btype='amount', value=2400.0)),
        ('dyn', B(id=2, name='SSG 카드혜택가', btype='amount', value=3000.0)),
    ])
    assert _names(res) == ['SSG 카드혜택가'], (
        f'결제수단 택1 이 깨졌다 — 실제: {_names(res)}'
    )
    assert res['final_price'] == 97000


def test_naver_pay_still_excluded_from_pick_one():
    """네이버페이는 원래 택1 그룹 밖(카드와 동시 적용) — 이번 수정과 무관하게 유지."""
    res = compute_final_price(10000, [
        ('tpl', B(id=1, name='카드A 캐시백', btype='rate', value=0.05)),
        ('tpl', B(id=2, name='카드B 캐시백', btype='rate', value=0.10)),
        ('tpl', B(id=3, name='네이버페이 적립', btype='rate', value=0.01)),
    ])
    # 카드A/카드B 는 이름에 '카드' 가 있어 캐시백 축이 아님 → 택1 유지, B 승
    assert _names(res) == ['카드B 캐시백', '네이버페이 적립']


# ────────────────────────────────────────────────────────────────────────────
# ④ 세트 제약② — naver_via 경로에서는 캐시백이 꺼진다
# ────────────────────────────────────────────────────────────────────────────

def test_naver_via_disables_cashback():
    """네이버경유 8% 가 캐시백 2% 보다 유리 → 경유 경로 승, 캐시백은 꺼짐."""
    res = compute_final_price(10000, [
        ('tpl', T(id=1, name='캐시백', btype='rate', value=0.02,
                  apply_mode='cashback')),
        ('tpl', T(id=2, name='네이버경유쿠폰', btype='rate', value=0.08,
                  channel='naver_via')),
    ])
    assert res['path'] == {'pay_method': None, 'naver_via': True}
    assert _names(res) == ['네이버경유쿠폰'], (
        f'제약②(naver_via ⟹ 캐시백 off)가 깨졌다 — 실제: {_names(res)}'
    )


def test_naver_via_off_keeps_cashback_with_card():
    """경유를 안 타는 경로에서는 캐시백과 결제카드가 **함께** 적용된다."""
    res = compute_final_price(100000, [
        ('tpl', T(id=1, name='OK캐시백', btype='rate', value=0.10,
                  apply_mode='cashback')),
        ('tpl', T(id=2, name='네이버경유쿠폰', btype='rate', value=0.01,
                  channel='naver_via')),
        ('tpl', T(id=3, name='현대카드 청구할인', btype='rate', value=0.0273,
                  apply_mode='payment', pay_method='hyundai')),
    ])
    assert res['path'] == {'pay_method': 'hyundai', 'naver_via': False}
    assert _names(res) == ['OK캐시백', '현대카드 청구할인']


# ────────────────────────────────────────────────────────────────────────────
# ⑤ 캐시백만 있고 결제 항목이 없을 때
# ────────────────────────────────────────────────────────────────────────────

def test_cashback_only_no_payment_item():
    """단독 캐시백 — 택1 그룹이 비어도 그대로 차감(기존 동작 보존)."""
    res = compute_final_price(10000, [
        ('tpl', B(id=1, name='OK캐시백', btype='rate', value=0.02)),
    ])
    assert _names(res) == ['OK캐시백']
    assert res['final_price'] == 9800


def test_two_cashbacks_both_deducted():
    """캐시백 항목이 둘이면 서로 택1이 **아니다** — 캐시백 택1 제약은 설계에 없다.

    (화면에서 캐시백 사이트를 택1로 고르는 건 webapp/routes/bulk/margin.py 의
     조립 단계 책임이고, 계산 엔진의 제약이 아니다.)
    """
    res = compute_final_price(100000, [
        ('tpl', B(id=1, name='OK캐시백', btype='rate', value=0.011)),
        ('tpl', B(id=2, name='네이트캐시백', btype='rate', value=0.02)),
    ])
    assert _names(res) == ['OK캐시백', '네이트캐시백']


# ────────────────────────────────────────────────────────────────────────────
# ⑥ tagged 경로와 legacy 경로가 **같은 입력에서 같은 답**을 준다 (정합성)
# ────────────────────────────────────────────────────────────────────────────

CONSISTENCY_CASES = [
    # (id, sale_price, [(name, btype, value, is_cashback, pay_method)])
    ('lotteon_okcash_hyundai', 100000, [
        ('OK캐시백', 'rate', 0.011, True, None),
        ('현대카드 청구할인', 'rate', 0.0273, False, 'hyundai'),
    ]),
    ('ssg_okcash_hyundai', 98000, [
        ('OK캐시백', 'rate', 0.02, True, None),
        ('현대카드 청구할인', 'rate', 0.0273, False, 'hyundai'),
    ]),
    ('cashback_only', 129000, [
        ('OK캐시백', 'rate', 0.011, True, None),
    ]),
    ('cashback_with_amount_card', 89000, [
        ('OK캐시백', 'rate', 0.02, True, None),
        ('카드 청구할인', 'amount', 3000.0, False, 'hyundai'),
    ]),
]


@pytest.mark.parametrize('case', CONSISTENCY_CASES, ids=[c[0] for c in CONSISTENCY_CASES])
def test_tagged_and_legacy_agree(case):
    """같은 혜택을 태그 없이(legacy) / 태그 붙여서(tagged) 계산하면 결과가 같아야 한다.

    이게 이번 수정의 핵심 가치다. 수정 전에는 legacy 만 캐시백을 택1로 잡아먹어
    같은 소싱처가 태그 유무에 따라 **다른 매입가**를 냈다.

    ※ tagged 쪽 pay_choices 에는 무결제(None) 경로도 있어 '카드를 안 쓰는' 답이
      더 쌀 수 있지만, 여기 케이스는 카드 차감이 양수라 항상 카드 경로가 이긴다.
    """
    _cid, sale, rows = case

    legacy = compute_final_price(sale, [
        ('tpl', B(id=i, name=nm, btype=bt, value=v))
        for i, (nm, bt, v, _cb, _pm) in enumerate(rows, 1)
    ])
    tagged = compute_final_price(sale, [
        ('tpl', T(id=i, name=nm, btype=bt, value=v,
                  apply_mode=('cashback' if cb else ('payment' if pm else None)),
                  pay_method=pm))
        for i, (nm, bt, v, cb, pm) in enumerate(rows, 1)
    ])
    assert legacy['final_price'] == tagged['final_price'], (
        f'tagged↔legacy 불일치 — legacy={legacy["final_price"]} '
        f'tagged={tagged["final_price"]}\n'
        f'  legacy steps: {[(s["name"], s["deduct"]) for s in legacy["steps"]]}\n'
        f'  tagged steps: {[(s["name"], s["deduct"]) for s in tagged["steps"]]}'
    )
    assert _names(legacy) == _names(tagged)


# ────────────────────────────────────────────────────────────────────────────
# ⑦ 시드 실물 형태 — apply_card_candidates 의 legacy 단락 경로에서도 동시 차감
# ────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize('label, rate, base_ratio, exp_cb, exp_card, exp_final', [
    # lotteon: int(100000×0.9×0.011)=989 → 99011 → int(99011×0.0273)=2703 → 96308 → 96300
    ('lotteon', 0.011, 0.9, 989, 2703, 96300),
    # ssg:     int(100000×1.0×0.02)=2000 → 98000 → int(98000×0.0273)=2675 → 95325 → 95300
    ('ssg', 0.02, 1.0, 2000, 2675, 95300),
])
def test_cashback_coexists_with_hyundai_floor(label, rate, base_ratio,
                                              exp_cb, exp_card, exp_final):
    """OK캐시백 시드행 + 현대카드 플로어 → 둘 다 steps에 존재 (택1 경쟁 금지).
    스펙 §4-1 (2026-07-22): 캐시백은 유입경로 축 — 카드와 동시 차감.

    청구할인(pay_method) 행이 0건인 오늘의 실물 형태다 —
    `apply_card_candidates` 는 legacy 로 단락하고(effective+floor, 태그 없음),
    `_compute_legacy` 의 택1 후보 제외(final_price.py:241~242)가 캐시백을
    현대카드 플로어와 **동시에** 차감시킨다. 엔진 수정 없이 이미 성립하는
    동작을 여기서 못 박는다(회귀 방지 핀).

    검증 3중:
      · 둘 다 steps 에 존재(택1로 삼켜지지 않음)
      · 캐시백 step 이 정확히 1개(이중 차감 아님 — 매입가 과소 방향 차단)
      · 차감액 = int(잔액×base_ratio×적립율) 정확값 (ssg 1.0 / lotteon 0.9)
    """
    from lemouton.pricing.card_candidates import apply_card_candidates

    class Card:
        key = 'nexon_hyundai'
        label = '넥슨현대카드'
        accrual_rate = 0.027
        is_hyundai_default = True
        active = True

    seeded_cashback = B(id=1, name='OK캐시백', btype='rate', value=rate,
                        category='캐시백', apply_mode='cashback',
                        base_ratio=base_ratio)
    floor = B(id=-1, name='현대카드 2.73% (청구할인 fallback)',
              btype='rate', value=0.0273)

    eff, info = apply_card_candidates([('tpl', seeded_cashback)], [Card()],
                                      floor=floor)
    assert info['mode'] == 'legacy', (
        '청구할인 행 0건 = legacy 단락 — 이 경로에서 동시 차감이 성립해야 한다')

    res = compute_final_price(100_000, eff)
    names = _names(res)
    assert names == ['OK캐시백', '현대카드 2.73% (청구할인 fallback)'], (
        f'{label}: 캐시백과 현대카드 플로어는 둘 다 차감돼야 한다 — 실제: {names}')
    assert names.count('OK캐시백') == 1, '캐시백이 두 번 차감됐다(매입가 과소 = 위험)'

    steps = {s['name']: s for s in res['steps']}
    assert steps['OK캐시백']['deduct'] == exp_cb
    assert steps['OK캐시백']['base_ratio'] == pytest.approx(base_ratio)
    assert steps['현대카드 2.73% (청구할인 fallback)']['deduct'] == exp_card
    assert res['final_price'] == exp_final


# ────────────────────────────────────────────────────────────────────────────
# 단일 정의 보증 — 판정 함수가 두 벌로 갈라지면 tagged/legacy 가 다시 어긋난다
# ────────────────────────────────────────────────────────────────────────────

def test_is_cashback_is_single_definition():
    """final_price / card_candidates / bulk.margin 이 **같은 객체**를 가리켜야 한다."""
    from lemouton.pricing.final_price import _is_cashback as engine_fn
    from lemouton.pricing.card_candidates import _is_cashback as cards_fn
    from webapp.routes.bulk.margin import _is_cashback as margin_fn

    assert cards_fn is engine_fn, 'card_candidates 가 사본을 들고 있다'
    assert margin_fn is engine_fn, 'bulk.margin 이 사본을 들고 있다'
