# -*- coding: utf-8 -*-
"""소싱처 매입가 — 결제카드 다중 후보 조립 (대량등록 Phase 1B M1-4).

■ 무엇을 바꾸나
  기존엔 api_benefits.py 가 롯데온·SSG·무신사에 '현대카드 2.73%' **한 장만**
  하드코딩해 넣었다. 그래서 롯데홈쇼핑 삼성카드 7% 청구할인(현대카드의 2.5배)
  같은 실제 조건을 매입가에 반영할 방법이 없었다.
  이 모듈은 카드 후보를 **여러 장** 만들어 엔진(final_price)이 최유리 카드를
  자동 선택하게 한다.

■ 계산 모델 (사용자 확정)
  카드 1장을 고르면 그 카드의 **적립율**과 그 소싱처에서의 **청구할인** 두 개가
  함께 차감된다. 카드끼리는 택1.
      잔액 ×= (1 − 카드 적립율)      # PurchaseCard.accrual_rate (소싱처 무관)
      잔액 ×= (1 − 카드 청구할인율)   # 소싱처×카드별 (SourceBenefitTemplate 행)

■ 청구할인을 어떻게 표현하나 (신규 테이블 없음)
  기존 ``source_benefit_templates`` / ``option_benefit_overrides`` 행에
      apply_mode = 'payment'
      pay_method = <PurchaseCard.key>   (예: 'samsung_select')
  를 세팅한다. 이 규약은 이 파일이 새로 만든 게 아니라 M1-2 가 이미 못 박아 둔
  설계다 — lemouton/margin/models.py 의 PurchaseCard docstring:
      "소싱처별 혜택은 ``pay_method`` 로 이 표의 ``key`` 를 가리키기만 한다(배선은 M1-4)"
  컬럼 자체도 이미 존재한다(sourcing/models.py:418·474, shared/db.py:220·223).

■ 왜 엔진의 tagged 경로로 태우나
  final_price 의 legacy 경로는 결제 택1 승자를 ``_approx_deduct`` = **항상 표면가
  기준 근사**로 고른다. 카드가 여러 장이면 실제 차감(정액 차감 뒤 잔액 기준)과
  교차점이 어긋나 **승자를 잘못 고른다**. tagged 경로는 경로를 열거해 **실제
  최종가**로 비교하므로 우리가 원하는 동작이 정확히 이것이다.

■ 진입 게이트 — 왜 '청구할인 행이 1건이라도 있을 때만' tagged 인가
  tagged 로 넘어가면 결제 택1 판정 방식 자체가 바뀐다(근사 → 실측). 이건 개선이지만
  전 상품 가격에 닿는 변경이다. 그런데 **오늘 라이브 DB 에는 pay_method 값을 쓰는
  코드·UI 가 한 곳도 없다**(전수 grep: 복사만 하고 쓰지 않는다 = 전부 NULL).
  그래서 "카드 태그된 청구할인 행이 있는 소싱처만" tagged 로 보내면
    · 데이터가 없는 오늘 = 전 소싱처 기존 legacy 동작 그대로 (blast radius 0)
    · 사용자가 카드 행을 넣은 소싱처만 = 다중 카드 모델 가동
  이 된다. 사고 없이 켜지는 유일한 순서다.
"""
from __future__ import annotations

# legacy 가 결제 택1 그룹을 판정하던 바로 그 함수. tagged 로 넘어갈 때 같은 그룹이
# 계속 상호배타로 남게 하려면 판정 기준이 동일해야 한다(이름 기반, '네이버' 제외).
#
# _is_cashback 도 **엔진에 단 하나만** 정의돼 있다. 예전엔 이 파일이 사본을 들고
# 있었는데, legacy(_compute_legacy)는 캐시백을 결제 택1로 잡아먹고 tagged 는 안
# 잡아먹어 **같은 소싱처가 태그 유무에 따라 다른 매입가**를 냈다. 정의를 한 곳으로
# 모아 그 분기 자체를 없앴다 — 여기서 재정의하지 말 것.
from lemouton.pricing.final_price import _is_payment, _is_cashback  # noqa: F401

# 레거시 '현대카드 2.73%' 플로어가 차지하는 결제 경로 키. 실제 PurchaseCard.key 와
# 겹치지 않게 __ 로 감싼다(카드 키는 소문자·영숫자·_ 만 쓴다).
#
# ⚠️ 이 값(18자)과 아래 __other{n}__ 합성 태그는 **메모리 전용**이다 — 경로 열거용
#   TaggedProxy 에만 실리고 DB 로 나가지 않는다. pay_method 컬럼은 VARCHAR(16) 이라
#   만약 누가 이걸 저장하게 배선하면 **라이브(Supabase PG)에서만** 저장이 깨진다
#   (SQLite 개발기는 길이를 강제하지 않아 조용히 통과 → 개발기에서 안 잡힘).
#   저장 경로를 만들 거면 먼저 16자 이하로 줄일 것.
HYUNDAI_FLOOR_KEY = '__hyundai_floor__'


class CardBenefit:
    """카드 적립율을 엔진에 넣기 위한 항목 (DB 행 아님).

    이름에 '적립' 이 들어가야 카테고리 정렬(_benefit_priority)에서 %할인보다 **먼저**
    차감된다 = 사용자 확정 순서(적립 먼저, 청구할인 나중).
    """

    __slots__ = ('id', 'benefit_name', 'benefit_type', 'value', 'enabled',
                 'category', 'apply_mode', 'pay_method', 'channel',
                 'sort_order', 'template_id')

    def __init__(self, *, name, value, pay_method, enabled=True, btype='rate'):
        self.id = -1
        self.benefit_name = name
        self.benefit_type = btype
        self.value = value
        self.enabled = enabled
        self.category = '결제'
        self.apply_mode = 'payment'
        self.pay_method = pay_method
        self.channel = None
        self.sort_order = 998
        self.template_id = None


class TaggedProxy:
    """기존 혜택 항목에 결제 태그만 덧씌우는 **복사** 프록시.

    원본을 절대 변형하지 않는다. tpl/ovr 은 ORM 행이고 bulk_breakdowns 의 _cache 로
    여러 SKU 가 **같은 객체를 공유**한다. 여기서 apply_mode 를 써 넣으면 뒤따르는
    SKU 계산이 통째로 오염된다 — M1-3 에서 잡은 '입력 객체 변형' 사고와 같은 클래스.
    """

    __slots__ = ('id', 'benefit_name', 'benefit_type', 'value', 'enabled',
                 'category', 'apply_mode', 'pay_method', 'channel',
                 'sort_order', 'template_id', 'base_ratio')

    def __init__(self, inner, *, pay_method, apply_mode='payment'):
        self.id = getattr(inner, 'id', -1)
        self.benefit_name = getattr(inner, 'benefit_name', '')
        self.benefit_type = getattr(inner, 'benefit_type', 'rate')
        self.value = getattr(inner, 'value', 0.0)
        self.enabled = getattr(inner, 'enabled', True)
        self.category = getattr(inner, 'category', None)
        self.channel = getattr(inner, 'channel', None)
        self.apply_mode = apply_mode
        self.pay_method = pay_method
        self.sort_order = getattr(inner, 'sort_order', 0)
        self.template_id = getattr(inner, 'template_id', None)
        # [2026-07-22 Task 4] 캐시백 공급가 계수 — 안 옮기면 tagged 경로에서
        # 캐시백이 전액 기준으로 계산돼 10% **과다 차감**(매입가 과소 = 위험 방향).
        # 엔진 _base_ratio 는 캐시백이 아닌 항목엔 어차피 1.0 을 돌려주므로
        # 복사 자체는 전 항목에 안전하다.
        self.base_ratio = getattr(inner, 'base_ratio', None)


def _fmt_rate(r: float) -> str:
    return f'{r * 100:g}%'


def apply_card_candidates(effective, cards, *, floor=None):
    """결제카드 후보를 주입한 새 effective 리스트를 만든다.

    Args:
        effective: [(kind, item)] — 이미 조립된 혜택 목록(템플릿+override+동적).
                   **변형하지 않는다** (새 리스트를 돌려준다).
        cards:     PurchaseCard 유사 객체 목록 (key/label/accrual_rate/
                   is_hyundai_default/active). None·빈 리스트 허용.
        floor:     레거시 '현대카드 2.73%' 항목(있으면). 현대카드 플로어 역할 —
                   대안 카드가 이걸 못 이기면 이게 자동 채택된다.

    Returns:
        (new_effective, info)
        info = {'mode': 'legacy'|'tagged', 'candidates': [카드키...], 'floor': bool}

    동작:
        · 청구할인 행(pay_method=카드키)이 **하나도 없으면** → legacy 유지.
          기존 effective + floor 를 태그 없이 그대로 돌려준다 = 오늘 동작 100% 보존.
        · 하나라도 있으면 → tagged.
          - 후보 카드 = 청구할인 행이 있는 카드 ∪ 적립율>0 인 활성 카드
            (청구할인 행이 없는 카드도 적립율만으로 후보 = 청구할인 0)
          - 카드마다 적립 항목 주입 (pay_method=카드키)
          - 청구할인 행은 apply_mode='payment' 로 보정(pay_method 는 DB 값 그대로)
          - floor 는 전용 경로 키로 태그 → 항상 후보로 남는다
          - 그 밖의 '결제성' 항목(이름 기반 legacy 판정)은 서로 다른 경로 키를 받아
            legacy 와 똑같이 **상호배타**로 남는다
    """
    effective = list(effective)
    cards = [c for c in (cards or []) if getattr(c, 'active', True)]
    keys = {c.key for c in cards}

    # ── 청구할인 행 탐지 ────────────────────────────────────────────────
    billed_keys = {
        getattr(it, 'pay_method', None)
        for _k, it in effective
        if getattr(it, 'pay_method', None) in keys
    }

    if not billed_keys:
        # 데이터 없음 → 다중 카드 모델을 켤 근거가 없다. 기존 경로 그대로.
        out = list(effective)
        if floor is not None:
            out.append(('dyn', floor))
        return out, {'mode': 'legacy', 'candidates': [], 'floor': floor is not None}

    # ── 후보 카드 확정 ──────────────────────────────────────────────────
    candidates = [c for c in cards
                  if c.key in billed_keys or float(c.accrual_rate or 0) > 0]

    out = []
    other_n = 0
    for kind, it in effective:
        pm = getattr(it, 'pay_method', None)
        if pm in keys:
            # 카드 청구할인 행 — 엔진이 경로로 열거하려면 apply_mode='payment' 필요.
            out.append((kind, TaggedProxy(it, pay_method=pm)))
        elif pm is not None:
            # [2026-07-23 Task 8] 이미 다른 경로 키로 **선태깅**된 행 — 예: 롯데온
            # 최대혜택가 모드의 짝 행('○○카드 즉시할인' + '현대카드 2.73% (카드결제
            # 병행)', 같은 합성키 __lo_cardN__). 여기서 이름('카드')만 보고 __otherN__
            # 로 재태깅하면 짝이 서로 다른 키로 갈라져 「즉시할인만 차감」·「2.73%만
            # 차감」 경로로 분해된다(차감 축소 = 매입가 과대 방향이긴 하나 비의도).
            # 조립부는 기존 태그를 존중하고 그대로 통과시킨다. 마스터 키 행은 위
            # 분기가 이미 처리했으므로 여기 오는 pm 은 전부 합성/외부 키다.
            out.append((kind, it))
        elif getattr(it, 'apply_mode', None) == 'preapplied':
            # 선반영 = 표면가에 이미 들어있어 차감 자체가 없는 항목.
            # 결제 택1 경로로 만들면 '아무것도 안 깎는 경로'가 되어 카드 후보를
            # 이유 없이 이긴다(= 매입가 과대). 택1 대상에서 뺀다.
            out.append((kind, it))
        elif _is_cashback(it):
            # 캐시백 = 유입경로 축. 결제 택1 그룹에 넣으면 카드를 고른 경로에서
            # 통째로 꺼진다(= 매입가 과대). 카드와 **함께** 적용돼야 한다.
            # apply_mode='cashback' 으로 정규화해 세트 제약②(naver_via ⟹ 캐시백 off)를
            # 태그 없는 legacy 행에도 똑같이 적용한다. pay_method 는 None —
            # 결제 경로 열거 대상이 아니라는 뜻.
            out.append((kind, TaggedProxy(it, pay_method=None, apply_mode='cashback')))
        elif _is_payment(getattr(it, 'benefit_name', '')):
            # legacy 가 택1 그룹으로 보던 항목(캐시백·카드혜택가 등).
            # 각자 다른 경로 키를 줘 서로 배타 유지 — 다만 승자는 근사가 아니라
            # 실제 최종가로 고른다(legacy 대비 이게 이 작업의 개선점).
            other_n += 1
            out.append((kind, TaggedProxy(it, pay_method=f'__other{other_n}__')))
        else:
            out.append((kind, it))

    # ── 카드별 적립율 항목 주입 ────────────────────────────────────────
    for c in candidates:
        r = float(c.accrual_rate or 0)
        if r <= 0:
            continue  # 적립 0 = 넣어도 차감 0. 영수증만 지저분해진다.
        out.append(('card', CardBenefit(
            name=f'{c.label} 적립 {_fmt_rate(r)}',
            value=r, pay_method=c.key,
        )))

    # ── 현대카드 플로어 ────────────────────────────────────────────────
    # musinsa 플로어는 route 층에서 이미 선태깅되어 올 수 있음(카드마스터가 빈
    # 환경에서의 머니+현대 이중차감 방지) — api_benefits.py 무신사 플로어 주석 참조.
    # 여기서 다시 감싸도 같은 키/모드라 무해하다.
    if floor is not None:
        out.append(('dyn', TaggedProxy(floor, pay_method=HYUNDAI_FLOOR_KEY)))

    return out, {
        'mode': 'tagged',
        'candidates': sorted(billed_keys | {c.key for c in candidates}),
        'floor': floor is not None,
    }
