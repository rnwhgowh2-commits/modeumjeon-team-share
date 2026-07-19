"""회귀 스냅샷 하네스 — lemouton.pricing.final_price.compute_final_price.

목적
----
`compute_final_price` 는 모음전 전 매트릭스 가격·최저소싱처 선정·fx영수증의
단일 진실 원천이다. 곧 api_benefits.py 의 '현대카드 2.73% 하드코딩'을
다중 카드 후보 주입으로 바꾼다(M1-4). blast radius 가 전 상품 가격이므로,
**바꾸기 전 현재 출력**을 여기에 못 박아 둔다.

규칙
----
- EXPECTED 값은 "이론상 이래야 한다"가 아니라 **현재 코드를 실제로 실행해 얻은 출력**이다.
  (그게 회귀 기준선의 정의다. 값이 이상해 보여도 여기서 고치지 않는다.)
- 스냅샷 항목: final_price / path / steps 의 (name, deduct, base_after).
- 각 케이스는 make() 로 **매번 새 아이템을 만든다** — legacy 경로가 결제 택1에서
  `it.enabled = False` 로 아이템을 실제로 변형(mutate)하기 때문에 재사용 금지.
"""
import pytest

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


class T:
    """tagged 아이템 (apply_mode/pay_method/channel)."""

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


def _case(cid, doc, make):
    return {'id': cid, 'doc': doc, 'make': make}


# ────────────────────────────────────────────────────────────────────────────
# 케이스 정의 — make() 는 (sale_price, effective, kwargs) 를 돌려준다
# ────────────────────────────────────────────────────────────────────────────
CASES = [
    # ── legacy 경로 (태그 없음 → path=None) ────────────────────────────────
    _case('legacy_amount_only',
          '정액 3000 한 건만 — 정액 차감이 그대로 빠지는지',
          lambda: (10000, [('tpl', B(id=1, name='즉시할인쿠폰', btype='amount', value=3000.0))], {})),

    _case('legacy_rate_only',
          '정률 10% 한 건만 — 정률 차감 기본형',
          lambda: (10000, [('tpl', B(id=1, name='할인A', btype='rate', value=0.10))], {})),

    _case('legacy_rate_sequential',
          '정률 10% 두 건 — 두 번째가 직전 잔액 기준으로 깎이는지(순차 누적)',
          lambda: (10000, [('tpl', B(id=1, name='할인A', btype='rate', value=0.10)),
                           ('tpl', B(id=2, name='할인B', btype='rate', value=0.10))], {})),

    _case('legacy_category_sort',
          '입력 순서를 뒤집어도 정액 → %적립 → %할인 순으로 정렬되는지',
          lambda: (10000, [('tpl', B(id=3, name='카드할인', btype='rate', value=0.05)),
                           ('tpl', B(id=2, name='등급적립', btype='rate', value=0.10)),
                           ('tpl', B(id=1, name='즉시할인쿠폰', btype='amount', value=1000.0))], {})),

    _case('legacy_payment_pick_best',
          '결제 택1 — 카드 2개 중 차감 큰 쪽만 남고 나머지는 enabled=False 로 변형됨',
          lambda: (10000, [('tpl', B(id=1, name='카드A 캐시백', btype='rate', value=0.05)),
                           ('tpl', B(id=2, name='카드B 캐시백', btype='rate', value=0.10))], {})),

    _case('legacy_payment_naver_excluded',
          '네이버페이는 택1 그룹에서 제외 — 카드 승자와 동시 적용되는지',
          lambda: (10000, [('tpl', B(id=1, name='카드A 캐시백', btype='rate', value=0.05)),
                           ('tpl', B(id=2, name='카드B 캐시백', btype='rate', value=0.10)),
                           ('tpl', B(id=3, name='네이버페이 적립', btype='rate', value=0.01))], {})),

    _case('legacy_payment_amount_vs_rate',
          '결제 택1 비교가 정액 vs 정률 혼합일 때 (approx_deduct: 정액=값, 정률=sale×값)',
          lambda: (10000, [('tpl', B(id=1, name='카드 청구할인', btype='amount', value=900.0)),
                           ('tpl', B(id=2, name='현대카드 2.73% (청구할인 fallback)',
                                     btype='rate', value=0.0273))], {})),

    _case('legacy_cashback_named',
          '이름에 "캐시백"이 든 항목 — legacy 에서는 결제 택1 그룹으로 취급됨',
          lambda: (10000, [('tpl', B(id=1, name='OK캐시백', btype='rate', value=0.02))], {})),

    _case('legacy_reward_accrual',
          '적립(이름에 "적립") — 정률 할인보다 먼저 차감되는 카테고리 1',
          lambda: (50000, [('tpl', B(id=1, name='할인쿠폰', btype='rate', value=0.10)),
                           ('tpl', B(id=2, name='등급적립', btype='rate', value=0.03))], {})),

    _case('legacy_card_off_issuer_match',
          'card_enabled=False + card_issuer="현대카드" → 이름에 현대카드 든 항목만 죽음',
          lambda: (10000, [('tpl', B(id=1, name='현대카드 캐시백', btype='rate', value=0.10)),
                           ('tpl', B(id=2, name='등급적립', btype='rate', value=0.05))],
                   {'card_enabled': False, 'card_issuer': '현대카드'})),

    _case('legacy_card_off_issuer_mismatch',
          'card_enabled=False 라도 issuer 이름이 안 맞으면 그대로 적용되는지',
          lambda: (10000, [('tpl', B(id=1, name='삼성카드 캐시백', btype='rate', value=0.10))],
                   {'card_enabled': False, 'card_issuer': '현대카드'})),

    _case('legacy_card_off_issuer_none',
          'card_enabled=False 인데 card_issuer=None → card-off 룰 자체가 안 걸림',
          lambda: (10000, [('tpl', B(id=1, name='현대카드 캐시백', btype='rate', value=0.10))],
                   {'card_enabled': False, 'card_issuer': None})),

    _case('legacy_base_override',
          'base_override 가 sale_price 를 대체 — 계산·반환 sale_price 모두 override 기준',
          lambda: (50000, [('tpl', B(id=1, name='할인', btype='rate', value=0.10))],
                   {'base_override': 39000})),

    _case('legacy_negative_guard',
          '정액이 잔액보다 커도 음수 안 됨 — deduct 는 base 로 캡',
          lambda: (10000, [('tpl', B(id=1, name='대형쿠폰', btype='amount', value=99999.0))], {})),

    _case('legacy_value_zero',
          'value=0 — 활성이지만 차감 0 (steps 에는 기록됨)',
          lambda: (10000, [('tpl', B(id=1, name='빈쿠폰', btype='amount', value=0.0))], {})),

    _case('legacy_value_none',
          'value=None — float(it.value or 0) 로 0 처리되는지 (크래시 없이)',
          lambda: (10000, [('tpl', B(id=1, name='값없음쿠폰', btype='rate', value=None))], {})),

    _case('legacy_disabled_item',
          'enabled=False 항목 — 차감 안 되고 steps 에도 안 들어감',
          lambda: (10000, [('tpl', B(id=1, name='꺼진할인', btype='rate', value=0.10, enabled=False)),
                           ('tpl', B(id=2, name='켜진할인', btype='rate', value=0.05))], {})),

    _case('legacy_preapplied_skip',
          '선반영(apply_mode=preapplied) — 태그 판정에는 안 걸려 legacy 인데 차감은 스킵',
          lambda: (10000, [('tpl', B(id=1, name='선반영쿠폰', btype='amount', value=5000.0,
                                     apply_mode='preapplied')),
                           ('tpl', B(id=2, name='일반할인', btype='rate', value=0.10))], {})),

    _case('legacy_floor_exact_boundary',
          '백원 버림 경계 — 버림 전이 정확히 9000 (버림해도 그대로여야)',
          lambda: (10000, [('tpl', B(id=1, name='할인', btype='rate', value=0.10))], {})),

    _case('legacy_floor_just_above',
          '백원 버림 경계 — 버림 전 9099 류 (99원이 잘려나가는지)',
          lambda: (10000, [('tpl', B(id=1, name='할인', btype='amount', value=901.0))], {})),

    _case('legacy_floor_hyundai_only',
          '★ 현대카드 2.73% 단독 = 지금 롯데온·SSG 가 만드는 형태 (M1-4 가 바꿀 지점)',
          lambda: (100000, [('tpl', B(id=1, name='현대카드 2.73% (청구할인 fallback)',
                                      btype='rate', value=0.0273))], {})),

    _case('legacy_lotteon_shape',
          '★ 롯데온 실전 형태 — 롯데오너스 적립 + 네이버페이 + 현대카드 2.73% fallback',
          lambda: (129000, [('tpl', B(id=1, name='롯데오너스 적립', btype='rate', value=0.05)),
                            ('tpl', B(id=2, name='네이버페이 적립', btype='rate', value=0.01)),
                            ('dyn', B(id=-1, name='현대카드 2.73% (청구할인 fallback)',
                                      btype='rate', value=0.0273))], {})),

    _case('legacy_musinsa_shape',
          '★ 무신사 실전 형태 — 상품쿠폰 정액 + 등급적립 정액 + 현대카드 2.73%(머니 미적용 시)',
          lambda: (89000, [('dyn', B(id=-1, name='상품쿠폰', btype='amount', value=5000.0)),
                           ('dyn', B(id=-1, name='등급적립', btype='amount', value=1780.0)),
                           ('dyn', B(id=-1, name='현대카드 2.73% (무신사머니 미적용 시)',
                                     btype='rate', value=0.0273))], {})),

    _case('legacy_musinsa_money_active',
          '★ 무신사 — 무신사머니 적립이 잡혀 현대카드 fallback 이 enabled=False 인 형태',
          lambda: (89000, [('dyn', B(id=-1, name='무신사머니 결제 적립', btype='amount', value=2400.0)),
                           ('dyn', B(id=-1, name='현대카드 2.73% (무신사머니 미적용 시)',
                                     btype='rate', value=0.0273, enabled=False))], {})),

    _case('legacy_ssg_card_benefit_shape',
          '★ SSG 형태 — SSG MONEY 적립 + 카드혜택가 정액 + 현대카드 2.73% (결제 택1 경합)',
          lambda: (98000, [('dyn', B(id=-1, name='SSG MONEY 적립', btype='rate', value=0.01)),
                           ('dyn', B(id=-1, name='SSG 카드혜택가', btype='amount', value=3000.0)),
                           ('dyn', B(id=-1, name='현대카드 2.73% (청구할인 fallback)',
                                     btype='rate', value=0.0273))], {})),

    _case('legacy_empty',
          '혜택 0건 — 표면가가 그대로 (백원 버림만 적용)',
          lambda: (12345, [], {})),

    # ── tagged 경로 (pay_method/channel 있음 → 경로 열거 최저가) ────────────
    _case('tagged_payment_affiliate_vs_naverpay',
          'tagged 결제 택1 — 제휴카드 10% vs 네이버페이 5%, 최저가 경로 선택',
          lambda: (10000, [('tpl', T(id=1, name='제휴카드결제', btype='rate', value=0.10,
                                     apply_mode='payment', pay_method='affiliate_card')),
                           ('tpl', T(id=2, name='네이버페이결제', btype='rate', value=0.05,
                                     apply_mode='payment', pay_method='naver_pay'))], {})),

    _case('tagged_naver_via_vs_cashback',
          '네이버경유 ↔ 캐시백 상호배제 — 경유 8% 가 캐시백 2% 보다 싸 경유 경로 승',
          lambda: (10000, [('tpl', T(id=1, name='캐시백', btype='rate', value=0.02,
                                     apply_mode='cashback')),
                           ('tpl', T(id=2, name='네이버경유쿠폰', btype='rate', value=0.08,
                                     channel='naver_via'))], {})),

    _case('tagged_cashback_wins_over_via',
          '반대 방향 — 캐시백 10% 가 경유 3% 보다 싸면 경유 안 타는지',
          lambda: (10000, [('tpl', T(id=1, name='캐시백', btype='rate', value=0.10,
                                     apply_mode='cashback')),
                           ('tpl', T(id=2, name='네이버경유쿠폰', btype='rate', value=0.03,
                                     channel='naver_via'))], {})),

    _case('tagged_no_payment_path',
          '무결제(None) 경로도 후보에 포함 — 결제 태우는 게 더 싸면 그쪽',
          lambda: (10000, [('tpl', T(id=1, name='제휴카드결제', btype='rate', value=0.10,
                                     apply_mode='payment', pay_method='affiliate_card')),
                           ('tpl', T(id=2, name='일반할인', btype='rate', value=0.05))], {})),

    _case('tagged_preapplied_skip',
          'tagged 경로의 선반영 — 차감 없이 items_used 에만 preapplied=True',
          lambda: (10000, [('tpl', T(id=1, name='선반영쿠폰', btype='amount', value=5000.0,
                                     apply_mode='preapplied')),
                           ('tpl', T(id=2, name='제휴카드결제', btype='rate', value=0.10,
                                     apply_mode='payment', pay_method='affiliate_card'))], {})),

    _case('tagged_card_off',
          'tagged + card_enabled=False + issuer 매칭 — 경로 열거 안에서도 card-off 가 먹는지',
          lambda: (10000, [('tpl', T(id=1, name='현대카드 결제', btype='rate', value=0.10,
                                     apply_mode='payment', pay_method='affiliate_card')),
                           ('tpl', T(id=2, name='등급적립', btype='rate', value=0.05))],
                   {'card_enabled': False, 'card_issuer': '현대카드'})),

    _case('tagged_payment_all_disabled',
          '결제 항목이 전부 enabled=False → pay_choices 는 [None] 뿐',
          lambda: (10000, [('tpl', T(id=1, name='제휴카드결제', btype='rate', value=0.10,
                                     apply_mode='payment', pay_method='affiliate_card',
                                     enabled=False)),
                           ('tpl', T(id=2, name='일반할인', btype='rate', value=0.05))], {})),

    _case('tagged_full_combo',
          '결제 2종 × 네이버경유 × 캐시백 × 정액쿠폰 전조합 — 경로 열거 최저가 종합',
          lambda: (120000, [('tpl', T(id=1, name='제휴카드결제', btype='rate', value=0.07,
                                      apply_mode='payment', pay_method='affiliate_card')),
                            ('tpl', T(id=2, name='네이버페이결제', btype='rate', value=0.03,
                                      apply_mode='payment', pay_method='naver_pay')),
                            ('tpl', T(id=3, name='캐시백', btype='rate', value=0.02,
                                      apply_mode='cashback')),
                            ('tpl', T(id=4, name='네이버경유쿠폰', btype='rate', value=0.05,
                                      channel='naver_via')),
                            ('tpl', T(id=5, name='즉시할인쿠폰', btype='amount', value=4000.0))], {})),

    _case('tagged_base_override',
          'tagged + base_override — override 기준으로 경로 열거되는지',
          lambda: (200000, [('tpl', T(id=1, name='제휴카드결제', btype='rate', value=0.10,
                                      apply_mode='payment', pay_method='affiliate_card'))],
                   {'base_override': 39000})),

    _case('tagged_negative_guard',
          'tagged + 잔액 초과 정액 — 0 밑으로 안 내려가는지',
          lambda: (10000, [('tpl', T(id=1, name='대형쿠폰', btype='amount', value=99999.0)),
                           ('tpl', T(id=2, name='제휴카드결제', btype='rate', value=0.10,
                                     apply_mode='payment', pay_method='affiliate_card'))], {})),
]


def _snapshot(result):
    """스냅샷 대상만 뽑는다 — final_price / path / steps(name·deduct·base_after)."""
    return {
        'final_price': result['final_price'],
        'path': result['path'],
        'steps': [(s['name'], s['deduct'], s['base_after']) for s in result['steps']],
    }


# ────────────────────────────────────────────────────────────────────────────
# 기준선 — 아래 값은 **현재 코드를 실행해 얻은 실제 출력**이다 (이론값 아님).
# 코드 변경 후 이 값이 달라지면 = 전 상품 가격이 달라진다는 뜻.
# ────────────────────────────────────────────────────────────────────────────
EXPECTED = {
    # 정액 3000 한 건만 — 정액 차감이 그대로 빠지는지
    'legacy_amount_only': {
        'final_price': 7000,
        'path': None,
        'steps': [
            ('즉시할인쿠폰', 3000, 7000),
        ],
    },
    # 정률 10% 한 건만 — 정률 차감 기본형
    'legacy_rate_only': {
        'final_price': 9000,
        'path': None,
        'steps': [
            ('할인A', 1000, 9000),
        ],
    },
    # 정률 10% 두 건 — 두 번째가 직전 잔액 기준으로 깎이는지(순차 누적)
    'legacy_rate_sequential': {
        'final_price': 8100,
        'path': None,
        'steps': [
            ('할인A', 1000, 9000),
            ('할인B', 900, 8100),
        ],
    },
    # 입력 순서를 뒤집어도 정액 → %적립 → %할인 순으로 정렬되는지
    'legacy_category_sort': {
        'final_price': 7600,
        'path': None,
        'steps': [
            ('즉시할인쿠폰', 1000, 9000),
            ('등급적립', 900, 8100),
            ('카드할인', 405, 7695),
        ],
    },
    # 결제 택1 — 카드 2개 중 차감 큰 쪽만 남고 나머지는 enabled=False 로 변형됨
    'legacy_payment_pick_best': {
        'final_price': 9000,
        'path': None,
        'steps': [
            ('카드B 캐시백', 1000, 9000),
        ],
    },
    # 네이버페이는 택1 그룹에서 제외 — 카드 승자와 동시 적용되는지
    'legacy_payment_naver_excluded': {
        'final_price': 8900,
        'path': None,
        'steps': [
            ('네이버페이 적립', 100, 9900),
            ('카드B 캐시백', 990, 8910),
        ],
    },
    # 결제 택1 비교가 정액 vs 정률 혼합일 때 (approx_deduct: 정액=값, 정률=sale×값)
    'legacy_payment_amount_vs_rate': {
        'final_price': 9100,
        'path': None,
        'steps': [
            ('카드 청구할인', 900, 9100),
        ],
    },
    # 이름에 "캐시백"이 든 항목 — legacy 에서는 결제 택1 그룹으로 취급됨
    'legacy_cashback_named': {
        'final_price': 9800,
        'path': None,
        'steps': [
            ('OK캐시백', 200, 9800),
        ],
    },
    # 적립(이름에 "적립") — 정률 할인보다 먼저 차감되는 카테고리 1
    'legacy_reward_accrual': {
        'final_price': 43600,
        'path': None,
        'steps': [
            ('등급적립', 1500, 48500),
            ('할인쿠폰', 4850, 43650),
        ],
    },
    # card_enabled=False + card_issuer="현대카드" → 이름에 현대카드 든 항목만 죽음
    'legacy_card_off_issuer_match': {
        'final_price': 9500,
        'path': None,
        'steps': [
            ('등급적립', 500, 9500),
        ],
    },
    # card_enabled=False 라도 issuer 이름이 안 맞으면 그대로 적용되는지
    'legacy_card_off_issuer_mismatch': {
        'final_price': 9000,
        'path': None,
        'steps': [
            ('삼성카드 캐시백', 1000, 9000),
        ],
    },
    # card_enabled=False 인데 card_issuer=None → card-off 룰 자체가 안 걸림
    'legacy_card_off_issuer_none': {
        'final_price': 9000,
        'path': None,
        'steps': [
            ('현대카드 캐시백', 1000, 9000),
        ],
    },
    # base_override 가 sale_price 를 대체 — 계산·반환 sale_price 모두 override 기준
    'legacy_base_override': {
        'final_price': 35100,
        'path': None,
        'steps': [
            ('할인', 3900, 35100),
        ],
    },
    # 정액이 잔액보다 커도 음수 안 됨 — deduct 는 base 로 캡
    'legacy_negative_guard': {
        'final_price': 0,
        'path': None,
        'steps': [
            ('대형쿠폰', 10000, 0),
        ],
    },
    # value=0 — 활성이지만 차감 0 (steps 에는 기록됨)
    'legacy_value_zero': {
        'final_price': 10000,
        'path': None,
        'steps': [
            ('빈쿠폰', 0, 10000),
        ],
    },
    # value=None — float(it.value or 0) 로 0 처리되는지 (크래시 없이)
    'legacy_value_none': {
        'final_price': 10000,
        'path': None,
        'steps': [
            ('값없음쿠폰', 0, 10000),
        ],
    },
    # enabled=False 항목 — 차감 안 되고 steps 에도 안 들어감
    'legacy_disabled_item': {
        'final_price': 9500,
        'path': None,
        'steps': [
            ('켜진할인', 500, 9500),
        ],
    },
    # 선반영(apply_mode=preapplied) — 태그 판정에는 안 걸려 legacy 인데 차감은 스킵
    'legacy_preapplied_skip': {
        'final_price': 9000,
        'path': None,
        'steps': [
            ('일반할인', 1000, 9000),
        ],
    },
    # 백원 버림 경계 — 버림 전이 정확히 9000 (버림해도 그대로여야)
    'legacy_floor_exact_boundary': {
        'final_price': 9000,
        'path': None,
        'steps': [
            ('할인', 1000, 9000),
        ],
    },
    # 백원 버림 경계 — 버림 전 9099 류 (99원이 잘려나가는지)
    'legacy_floor_just_above': {
        'final_price': 9000,
        'path': None,
        'steps': [
            ('할인', 901, 9099),
        ],
    },
    # ★ 현대카드 2.73% 단독 = 지금 롯데온·SSG 가 만드는 형태 (M1-4 가 바꿀 지점)
    'legacy_floor_hyundai_only': {
        'final_price': 97200,
        'path': None,
        'steps': [
            ('현대카드 2.73% (청구할인 fallback)', 2730, 97270),
        ],
    },
    # ★ 롯데온 실전 형태 — 롯데오너스 적립 + 네이버페이 + 현대카드 2.73% fallback
    'legacy_lotteon_shape': {
        'final_price': 118000,
        'path': None,
        'steps': [
            ('롯데오너스 적립', 6450, 122550),
            ('네이버페이 적립', 1225, 121325),
            ('현대카드 2.73% (청구할인 fallback)', 3312, 118013),
        ],
    },
    # ★ 무신사 실전 형태 — 상품쿠폰 정액 + 등급적립 정액 + 현대카드 2.73%(머니 미적용 시)
    'legacy_musinsa_shape': {
        'final_price': 79900,
        'path': None,
        'steps': [
            ('상품쿠폰', 5000, 84000),
            ('등급적립', 1780, 82220),
            ('현대카드 2.73% (무신사머니 미적용 시)', 2244, 79976),
        ],
    },
    # ★ 무신사 — 무신사머니 적립이 잡혀 현대카드 fallback 이 enabled=False 인 형태
    'legacy_musinsa_money_active': {
        'final_price': 86600,
        'path': None,
        'steps': [
            ('무신사머니 결제 적립', 2400, 86600),
        ],
    },
    # ★ SSG 형태 — SSG MONEY 적립 + 카드혜택가 정액 + 현대카드 2.73% (결제 택1 경합)
    'legacy_ssg_card_benefit_shape': {
        'final_price': 94000,
        'path': None,
        'steps': [
            ('SSG 카드혜택가', 3000, 95000),
            ('SSG MONEY 적립', 950, 94050),
        ],
    },
    # 혜택 0건 — 표면가가 그대로 (백원 버림만 적용)
    'legacy_empty': {
        'final_price': 12300,
        'path': None,
        'steps': [],
    },
    # tagged 결제 택1 — 제휴카드 10% vs 네이버페이 5%, 최저가 경로 선택
    'tagged_payment_affiliate_vs_naverpay': {
        'final_price': 9000,
        'path': {'pay_method': 'affiliate_card', 'naver_via': False},
        'steps': [
            ('제휴카드결제', 1000, 9000),
        ],
    },
    # 네이버경유 ↔ 캐시백 상호배제 — 경유 8% 가 캐시백 2% 보다 싸 경유 경로 승
    'tagged_naver_via_vs_cashback': {
        'final_price': 9200,
        'path': {'pay_method': None, 'naver_via': True},
        'steps': [
            ('네이버경유쿠폰', 800, 9200),
        ],
    },
    # 반대 방향 — 캐시백 10% 가 경유 3% 보다 싸면 경유 안 타는지
    'tagged_cashback_wins_over_via': {
        'final_price': 9000,
        'path': {'pay_method': None, 'naver_via': False},
        'steps': [
            ('캐시백', 1000, 9000),
        ],
    },
    # 무결제(None) 경로도 후보에 포함 — 결제 태우는 게 더 싸면 그쪽
    'tagged_no_payment_path': {
        'final_price': 8500,
        'path': {'pay_method': 'affiliate_card', 'naver_via': False},
        'steps': [
            ('제휴카드결제', 1000, 9000),
            ('일반할인', 450, 8550),
        ],
    },
    # tagged 경로의 선반영 — 차감 없이 items_used 에만 preapplied=True
    'tagged_preapplied_skip': {
        'final_price': 9000,
        'path': {'pay_method': 'affiliate_card', 'naver_via': False},
        'steps': [
            ('제휴카드결제', 1000, 9000),
        ],
    },
    # tagged + card_enabled=False + issuer 매칭 — 경로 열거 안에서도 card-off 가 먹는지
    'tagged_card_off': {
        'final_price': 9500,
        'path': {'pay_method': 'affiliate_card', 'naver_via': False},
        'steps': [
            ('등급적립', 500, 9500),
        ],
    },
    # 결제 항목이 전부 enabled=False → pay_choices 는 [None] 뿐
    'tagged_payment_all_disabled': {
        'final_price': 9500,
        'path': {'pay_method': None, 'naver_via': False},
        'steps': [
            ('일반할인', 500, 9500),
        ],
    },
    # 결제 2종 × 네이버경유 × 캐시백 × 정액쿠폰 전조합 — 경로 열거 최저가 종합
    'tagged_full_combo': {
        'final_price': 102400,
        'path': {'pay_method': 'affiliate_card', 'naver_via': True},
        'steps': [
            ('즉시할인쿠폰', 4000, 116000),
            ('제휴카드결제', 8120, 107880),
            ('네이버경유쿠폰', 5394, 102486),
        ],
    },
    # tagged + base_override — override 기준으로 경로 열거되는지
    'tagged_base_override': {
        'final_price': 35100,
        'path': {'pay_method': 'affiliate_card', 'naver_via': False},
        'steps': [
            ('제휴카드결제', 3900, 35100),
        ],
    },
    # tagged + 잔액 초과 정액 — 0 밑으로 안 내려가는지
    'tagged_negative_guard': {
        'final_price': 0,
        'path': {'pay_method': 'affiliate_card', 'naver_via': False},
        'steps': [
            ('대형쿠폰', 10000, 0),
            ('제휴카드결제', 0, 0),
        ],
    },
}


@pytest.mark.parametrize('case', CASES, ids=[c['id'] for c in CASES])
def test_final_price_snapshot(case):
    sale_price, effective, kwargs = case['make']()
    got = _snapshot(compute_final_price(sale_price, effective, **kwargs))
    want = EXPECTED[case['id']]
    assert got == want, (
        f"\n[회귀 감지] {case['id']} — {case['doc']}\n"
        f"  기준선: {want}\n"
        f"  현재값: {got}\n"
    )


def test_all_cases_have_baseline():
    """케이스를 추가하고 기준선을 안 넣는 조용한 실패 방지."""
    missing = [c['id'] for c in CASES if c['id'] not in EXPECTED]
    assert not missing, f'기준선 없는 케이스: {missing}'


def test_case_ids_unique():
    ids = [c['id'] for c in CASES]
    assert len(ids) == len(set(ids)), 'CASES id 중복'
