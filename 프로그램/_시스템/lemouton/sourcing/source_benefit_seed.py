# -*- coding: utf-8 -*-
"""소싱처별 혜택 시드 — OK캐시백 적립율 + 카드 청구할인 (대량등록 Phase 1B M1-5).

■ 무엇을 넣나 / 신규 테이블은 만들지 않는다
  소싱처별 **OK캐시백 적립율**과 **카드 청구할인**은 기존
  ``source_benefit_templates`` (SourceBenefitTemplate) 행으로 표현한다.
  이 규약은 이 파일이 만든 게 아니라 M1-4(card_candidates.py) 가 이미 못 박은 설계다.

      카드 청구할인 : apply_mode='payment',  pay_method=<PurchaseCard.key>,
                     benefit_type='rate',   value=<율>
      OK캐시백      : apply_mode='cashback', pay_method=None,
                     benefit_type='rate',   value=<율>

  컬럼 의미는 sourcing/models.py:400~427 의 실제 정의를 확인하고 쓴 것이다
  (추측 아님). category 는 '정액|정률|결제|캐시백|기타' 중 하나이고, 캐시백에
  '캐시백' 을 넣으면 card_candidates._is_cashback 의 3번 근거(= backfill 스크립트와
  같은 진실 원천)와도 일치한다.

■ source_id 가 가리키는 표
  SourceBenefitTemplate.source_id 는 ``source_registry.id`` 다
  (models_pricing.SourceRegistry — SourcingSource 가 **아니다**). 이 표는 key 컬럼이
  없고 name/main_url 뿐이라, 소싱처 key → id 는 **main_url 도메인 매칭**으로 푼다.
  이건 매트릭스가 쓰는 것과 같은 방식이다(api_pricing.py:749 ``_key_domain``).
  도메인은 SOURCE_CATALOG 를 단일 진실 원천으로 읽어 이 파일에 복제하지 않는다.

■ 시드 멱등 방식: (source_id, benefit_name) 단위 insert-if-missing
  근거 ① 코드베이스 관례 — purchase_card_store.seed_purchase_cards 는 key 단위
        insert-if-missing, source_registry.seed_builtins 는 source_key 가 있으면
        skip, MarketRegistry 시드는 count()==0. upsert 시드는 이 저장소에 없다.
  근거 ② 사용자 수정 보존 — 소싱처 기본셋팅 화면에서 고친 적립율이 재부팅마다
        조용히 원복되면 그게 곧 '에러 없이 틀린 금액'이다.

■ 중복 캐시백 가드 (라이브 충돌 대비)
  이 워크트리는 SQLite 폴백이라 라이브(Supabase)의 기존 혜택 행을 볼 수 없다.
  라이브에 이미 이름만 다른 캐시백 행(예: 'OK캐시백 2%')이 있으면 이름 단위
  insert-if-missing 만으로는 **행이 2개**가 되어 캐시백이 이중 차감된다
  (= 매입가 과소 = 마진 과대 = 금전 손실 방향). 그래서 이름이 아니라
  **"그 소싱처에 캐시백성 행이 이미 하나라도 있으면 통째로 skip"** 한다.
  넣지 않아 생기는 손해는 매입가 과대(안전 방향)뿐이다.

■ 값의 출처
  영빈 「대량위탁」 관리엑셀에서 확정된 OK캐시백 사이트별 적립율. 지어내지 않는다.
  우리 소싱처 명부(source_registry.SOURCE_CATALOG)에 **확실히 대응되는 것만** 넣는다
  — 매핑 근거와 제외 사유는 docs/sources/소싱처별-캐시백-카드청구할인-시드표.md.
"""
from __future__ import annotations

import logging

_log = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════════════════
#  1) OK캐시백 사이트별 적립율 — (소싱처 key, 혜택 이름, 적립율)
#
#  엑셀 12행 중 **우리 소싱처 key 에 확실히 대응되는 2건만**. 나머지는 시드하지
#  않는다(엉뚱한 소싱처에 붙이면 그게 곧 가격 오류다):
#    · 더현대 3% / GS샵 1.6% / CJ 1.5% / 롯데백화점 1.1% — 우리 소싱처 명부에 없음
#    · 11번가 0.8% / 옥션 0.5% / 지마켓 0.5% — 우리 시스템에서 **판매처**(마켓)다.
#      소싱처가 아니므로 SourceRegistry 행 자체가 없다.
#    · H몰(현대H몰) 2.7% / 롯데홈쇼핑 2.5%(=롯데아이몰) — 사장님 **보류 지시**.
#      (덧붙여 이 둘은 매트릭스가 'key:hmall' 같은 문자열 source_id 를 쓰는
#       카탈로그 소싱처라 정수 source_id 컬럼에 넣을 방법 자체가 없다.)
#    · 해당없음 0% — 시드할 대상이 아니다(행을 만들면 0원 차감 항목만 늘어난다).
#
#  ■ base_ratio (기준금액 계수) — 2026-07-19 사장님 확정
#    캐시백 사이트는 결제 전액이 아니라 **부가세를 뺀 공급가**에 적립해 준다.
#        캐시백 적립 = 기준금액 × 0.9 × 적립율      ← 기본
#        캐시백 적립 = 기준금액 × 1.0 × 적립율      ← SSG · 신세계쇼핑 · CJ (전액 기준 예외 3사)
#    적립율에 0.9 를 미리 곱해 넣지 않는다(1.1% → 0.99% 로 뭉개면 영수증에서 근거가
#    사라진다). 계수는 별도 컬럼(base_ratio)으로 두고 엔진이 **기준금액 쪽**에 건다.
#    · 신세계쇼핑(3%) · CJ(1.5%) 도 예외 3사지만 우리 소싱처 명부에 없어 시드 대상이
#      아니다 — 기록만 남긴다(docs/sources/소싱처별-OK캐시백-카드청구할인-시드표.md).
# ════════════════════════════════════════════════════════════════════════════
OK_CASHBACK_SEED: list[tuple[str, str, float, float]] = [
    # SSG 2% — 크롤가이드(scripts/populate_ssg_guide.py) 의
    #          {"name": "OK캐시백", "apply": "cashback", "rule": "베이스금액② × 2%"} 와 일치.
    #          base_ratio 1.0 — SSG 는 **전액 기준 예외 3사**다.
    ('ssg',     'OK캐시백', 0.02,  1.0),
    # 롯데온 1.1% — 예외가 아니므로 공급가 기준 0.9
    ('lotteon', 'OK캐시백', 0.011, 0.9),
]


# ════════════════════════════════════════════════════════════════════════════
#  2) 카드 청구할인 — (소싱처 key, PurchaseCard.key, 혜택 이름, 할인율)
#
#  ⚠ 지금은 **의도적으로 비어 있다**. 라이브에서 확인된 건은 롯데홈쇼핑 삼성카드 7%
#    한 건뿐인데 그 소싱처(lotteimall)가 보류 대상이다. 나머지 소싱처(무신사·SSF·
#    롯데온·SSG·르무통·스스)의 청구할인은 **모른다** — 추정치를 넣으면 매입가가
#    실제보다 낮아지고(마진 과대) 그대로 판매가 오설정 = 금전 손실이다.
#
#    보류 해제 시 넣을 값(문서용 기록, 시드 아님):
#        lotteimall × samsung_select ... 0.07   (라이브 확인 2026-07)
#
#    한 건이라도 채워지면 그 소싱처는 final_price 의 tagged 경로로 넘어가
#    (카드 적립 + 청구할인) 최유리 카드 자동 선택이 켜진다.
#    [정정 2026-07-22 — 스펙 §4-1] OK캐시백의 동시 차감은 tagged 를 기다리지
#    않는다 — legacy 경로도 _compute_legacy 가 택1 후보에서 캐시백을 제외하므로
#    (final_price.py:241~242) 시드가 들어가는 순간 현대카드 플로어와 **함께**
#    차감된다. 아래 seed_source_card_discounts 의 docstring 과 시드표 문서를
#    반드시 같이 읽을 것.
# ════════════════════════════════════════════════════════════════════════════
CARD_DISCOUNT_SEED: list[tuple[str, str, str, float]] = [
    # 예시 형식 (주석 — 실행되지 않는다):
    # ('lotteimall', 'samsung_select', '삼성카드 청구할인 7%', 0.07),
]


# ════════════════════════════════════════════════════════════════════════════
#  3) 리뷰적립 — 사장님 확정 2026-07-22 (스펙 §5). 르무통·스스=포토(금액 큼),
#     나머지=텍스트. 리뷰를 쓰면 돌려받는 **정액**이라 benefit_type='amount',
#     매입가에서 빼는 방향이라 apply_mode='deduct'.
#
#  Hmall(현대H몰)·롯데아이몰은 정수 SourceRegistry id 가 없는 카탈로그 소싱처라
#  이 시드의 대상이 아니다 (별도 처리 — 여기 넣으면 안 들어가는 게 아니라 못 들어간다).
#
#  (source_key, benefit_name, amount원)
# ════════════════════════════════════════════════════════════════════════════
REVIEW_REWARD_SEED: list[tuple[str, str, int]] = [
    ('lemouton',    '리뷰적립(포토)',   5000),
    ('ss_lemouton', '리뷰적립(포토)',   5000),
    ('musinsa',     '후기 적립',         500),   # 라이브에 수동 행 실존 — 가드로 skip
    ('ssf',         '리뷰적립(텍스트)',  200),
    ('lotteon',     '리뷰적립(텍스트)',   50),
    ('ssg',         '리뷰적립(텍스트)',   50),
]


# ════════════════════════════════════════════════════════════════════════════
#  3-b) L.POINT 적립 0.05% — 사장님 확정 2026-07-22 (스펙 §3-5 fx 목록, T8 후속 갭 해소).
#     롯데온 전용. 카드 경로 선택과 무관하게 **전 경로에서** 차감되는 적립이라
#     apply_mode='accrue'(네이버페이 시드와 같은 계열 — 결제 택1 밖).
#
#     ⚠ 크롤 인젝션과의 이중차감 방지 (검증 2026-07-23):
#       api_benefits 의 point_rewards 동적 블록은 자기 행('구매적립 L.POINT …')을
#       넣기 **전에** 이름에 'L.POINT'/'구매적립'/'LPOINT' 가 든 기존 행을 끈다.
#       이 시드 이름('L.POINT 적립 0.05%')은 'L.POINT' 에 걸리므로, 크롤이
#       point_rewards 를 내보내는 날에도 정확히 한 행만 차감된다(테스트
#       test_lpoint_seed_vs_point_rewards_injection_tripwire 가 못 박음).
#       → 이 시드 이름을 바꿀 때 'L.POINT' 를 빼면 그 가드가 풀린다 — 금지.
# ════════════════════════════════════════════════════════════════════════════
LPOINT_SEED: list[tuple[str, str, float]] = [
    ('lotteon', 'L.POINT 적립 0.05%', 0.0005),
]


# ════════════════════════════════════════════════════════════════════════════
#  4) 네이버페이 적립 1% — 사장님 확정 2026-07-22 (스펙 §4-3). 카드와 동시 적용(택1 아님).
#
#  ⚠ apply_mode='payment' 금지 — 택1에 들어가면 카드와 상호배타가 돼 스펙 위반.
#    엔진 _is_payment(pricing/final_price.py) 가 이름의 '네이버' 를 보고 택1에서
#    제외한다(이름 계약 — test_naver_pay_not_in_payment_pick_one 이 못 박음).
#
#  대상: 르무통·스스·SSF 3곳뿐.
#    · hmall(현대H몰)   = 엔진 주입으로 처리 (Task 3) — 카탈로그 소싱처라 정수 id 없음
#    · lotteon(롯데온)  = 조건부 로직 (Task 8)
#    · ssg·lotteimall   = N페이 미적용 — 사장님 확정
# ════════════════════════════════════════════════════════════════════════════
NAVER_PAY_SEED: list[str] = ['lemouton', 'ss_lemouton', 'ssf']


def _domain_for(source_key: str) -> str | None:
    """소싱처 key → 카탈로그 도메인. 단일 진실 원천은 SOURCE_CATALOG."""
    from lemouton.sourcing.source_registry import get_catalog_entry
    entry = get_catalog_entry(source_key)
    return (entry or {}).get('domain') or None


def resolve_registry_id(session, source_key: str) -> int | None:
    """소싱처 key → SourceRegistry.id (main_url 도메인 매칭). 못 찾으면 None.

    후보가 **2개 이상이면 None** — 애매하면 붙이지 않는다. 엉뚱한 소싱처에 혜택을
    붙이는 것보다 안 붙이는 쪽이 안전하다(매입가 과대 = 안전 방향).
    """
    from lemouton.sourcing.models_pricing import SourceRegistry
    dom = _domain_for(source_key)
    if not dom:
        return None
    hits = [r.id for r in session.query(SourceRegistry).all()
            if dom in ((r.main_url or '').lower())]
    if len(hits) != 1:
        return None
    return hits[0]


def _has_cashback_row(session, source_id: int) -> bool:
    """그 소싱처에 이미 '캐시백성' 템플릿 행이 있는가 (이름 무관).

    판정 근거 순서는 card_candidates._is_cashback 과 동일한 계열이다:
      apply_mode='cashback' | category='캐시백' | 이름에 '캐시백'.
    하나라도 걸리면 시드하지 않는다 → 이중 차감 원천 차단.
    """
    from lemouton.sourcing.models import SourceBenefitTemplate
    rows = (session.query(SourceBenefitTemplate)
            .filter_by(source_id=source_id).all())
    for r in rows:
        if (r.apply_mode or '') == 'cashback':
            return True
        if (r.category or '').strip() == '캐시백':
            return True
        if '캐시백' in (r.benefit_name or ''):
            return True
    return False


def seed_ok_cashback(session) -> int:
    """OK캐시백 적립율을 소싱처별로 멱등 시드. 새로 넣은 행 수를 반환.

    skip 조건 (전부 '안 넣는' 방향 = 안전):
      · SourceRegistry 에 그 소싱처 행이 없음 / 도메인 매칭 모호
      · 이미 캐시백성 행이 있음 (이름이 달라도) — 이중 차감 방지
    """
    from lemouton.sourcing.models import SourceBenefitTemplate
    added = 0
    for source_key, name, rate, base_ratio in OK_CASHBACK_SEED:
        sid = resolve_registry_id(session, source_key)
        if sid is None:
            _log.info('[benefit-seed] SourceRegistry 미해결 → skip: %s', source_key)
            continue
        if _has_cashback_row(session, sid):
            _log.info('[benefit-seed] 캐시백 행 이미 존재 → skip: %s(id=%s)',
                      source_key, sid)
            continue
        session.add(SourceBenefitTemplate(
            source_id=sid,
            benefit_name=name,
            benefit_type='rate',
            value=float(rate),
            category='캐시백',
            apply_mode='cashback',
            # 적립 기준금액 계수 — 0.9(공급가) / 1.0(전액: SSG·신세계쇼핑·CJ).
            # 적립율(value)은 원본 그대로 둔다 → 영수증에 1.1% 가 1.1% 로 보인다.
            base_ratio=float(base_ratio),
            pay_method=None,   # 캐시백은 결제카드 축이 아니다 (유입경로 축)
            channel=None,
            enabled=True,
            sort_order=50,
        ))
        added += 1
    if added:
        session.commit()
    return added


def _has_review_row(session, source_id: int) -> bool:
    """그 소싱처에 이름에 '후기' 또는 '리뷰' 포함 행이 있으면 True — 이중차감 원천차단.

    라이브 DB 에 수동으로 만든 무신사 '후기 적립' 500원 행이 실존한다.
    이름 단위 insert-if-missing 만으로는 이름이 다르면('후기 적립' vs '후기 적립(텍스트)')
    행이 2개가 되어 리뷰적립이 이중 차감된다(매입가 과소 = 금전 손실 방향).
    _has_cashback_row 와 같은 계열의 "있으면 통째로 skip" 가드다.

    ⚠ 알려진 한계 (개명 취약성): 이 가드는 **이름 기반**('후기'/'리뷰')이다.
    사장님이 시드된 행의 이름을 그 두 단어가 없는 이름으로 바꾸면 다음 부팅 시드가
    행을 또 넣는다 → 이중 차감. 리뷰적립 행은 **개명 대신 비활성/삭제를 쓸 것**.
    (구조적 마커 컬럼 도입은 별도 후속 작업 범위.)
    """
    from lemouton.sourcing.models import SourceBenefitTemplate
    rows = (session.query(SourceBenefitTemplate)
            .filter_by(source_id=source_id).all())
    for r in rows:
        name = r.benefit_name or ''
        if '후기' in name or '리뷰' in name:
            return True
    return False


def seed_review_rewards(session) -> int:
    """리뷰적립(정액 차감)을 소싱처별로 멱등 시드. 새로 넣은 행 수를 반환.

    skip 조건 (전부 '안 넣는' 방향 = 안전):
      · SourceRegistry 에 그 소싱처 행이 없음 / 도메인 매칭 모호
      · 이미 후기/리뷰성 행이 있음 (이름이 달라도) — 이중 차감 방지
    """
    from lemouton.sourcing.models import SourceBenefitTemplate
    added = 0
    for source_key, name, amount in REVIEW_REWARD_SEED:
        sid = resolve_registry_id(session, source_key)
        if sid is None:
            _log.info('[benefit-seed] SourceRegistry 미해결 → skip: %s', source_key)
            continue
        if _has_review_row(session, sid):
            _log.info('[benefit-seed] 후기/리뷰 행 이미 존재 → skip: %s(id=%s)',
                      source_key, sid)
            continue
        session.add(SourceBenefitTemplate(
            source_id=sid,
            benefit_name=name,
            benefit_type='amount',
            value=float(amount),
            category='정액',
            apply_mode='deduct',
            pay_method=None,
            channel=None,
            enabled=True,
            sort_order=40,
        ))
        added += 1
    if added:
        session.commit()
    return added


def _has_lpoint_row(session, source_id: int) -> bool:
    """그 소싱처에 L.POINT 성 행이 있으면 True — 이중차감 원천차단.

    어휘는 api_benefits point_rewards 인젝션의 turn-off 와 **같은 3종**
    ('L.POINT' / '구매적립' / 대소문자 무관 'LPOINT')이다 — 가드가 인젝션보다
    좁으면 이름만 다른 기존 행과 시드가 공존해 행이 2개가 된다(매입가 과소 방향).
    _has_cashback_row / _has_review_row 와 같은 계열의 "있으면 통째로 skip" 가드.
    """
    from lemouton.sourcing.models import SourceBenefitTemplate
    rows = (session.query(SourceBenefitTemplate)
            .filter_by(source_id=source_id).all())
    for r in rows:
        name = r.benefit_name or ''
        if 'L.POINT' in name or '구매적립' in name or 'LPOINT' in name.upper():
            return True
    return False


def seed_lpoint(session) -> int:
    """L.POINT 적립 0.05%(전 경로 차감 — accrue)를 멱등 시드. 새 행 수를 반환.

    skip 조건 (전부 '안 넣는' 방향 = 안전):
      · SourceRegistry 에 그 소싱처 행이 없음 / 도메인 매칭 모호
      · 이미 L.POINT/구매적립성 행이 있음 (이름이 달라도) — 이중 차감 방지
    """
    from lemouton.sourcing.models import SourceBenefitTemplate
    added = 0
    for source_key, name, rate in LPOINT_SEED:
        sid = resolve_registry_id(session, source_key)
        if sid is None:
            _log.info('[benefit-seed] SourceRegistry 미해결 → skip: %s', source_key)
            continue
        if _has_lpoint_row(session, sid):
            _log.info('[benefit-seed] L.POINT 행 이미 존재 → skip: %s(id=%s)',
                      source_key, sid)
            continue
        session.add(SourceBenefitTemplate(
            source_id=sid,
            benefit_name=name,
            benefit_type='rate',
            value=float(rate),
            category='정률',
            # 결제 택1 밖 · 캐시백 축도 아님 — 카드 경로와 무관하게 항상 차감.
            apply_mode='accrue',
            pay_method=None,
            channel=None,
            enabled=True,
            sort_order=45,
        ))
        added += 1
    if added:
        session.commit()
    return added


def _has_naver_row(session, source_id: int) -> bool:
    """그 소싱처에 이름에 '네이버' 포함 행이 있으면 True — 이중차감 원천차단.

    _has_cashback_row / _has_review_row 와 같은 계열의 "있으면 통째로 skip" 가드다.
    이름 단위 insert-if-missing 만으로는 이름이 조금 다른 기존 행('네이버페이 적립' vs
    '네이버페이 적립 1%')과 공존해 행이 2개가 되고, 네이버페이가 이중 차감된다
    (매입가 과소 = 금전 손실 방향).

    ⚠ 알려진 한계 (개명 취약성): 이 가드는 **이름 기반**('네이버')이다.
    사장님이 시드된 행의 이름을 그 단어가 없는 이름으로 바꾸면 다음 부팅 시드가
    행을 또 넣는다 → 이중 차감. 네이버페이 행은 **개명 대신 비활성/삭제를 쓸 것**.
    (구조적 마커 컬럼 도입은 별도 후속 작업 범위.)

    덧붙여 이 이름은 엔진 계약이기도 하다 — final_price._is_payment 가 '네이버' 를
    보고 결제 택1에서 제외한다. 개명하면 카드와 택1이 돼 스펙(동시 적용) 위반.
    """
    from lemouton.sourcing.models import SourceBenefitTemplate
    rows = (session.query(SourceBenefitTemplate)
            .filter_by(source_id=source_id).all())
    for r in rows:
        if '네이버' in (r.benefit_name or ''):
            return True
    return False


def seed_naver_pay(session) -> int:
    """네이버페이 적립 1%(카드와 동시 차감 — accrue)를 멱등 시드. 새 행 수를 반환.

    skip 조건 (전부 '안 넣는' 방향 = 안전):
      · SourceRegistry 에 그 소싱처 행이 없음 / 도메인 매칭 모호
      · 이미 '네이버' 포함 행이 있음 (이름이 달라도) — 이중 차감 방지
    """
    from lemouton.sourcing.models import SourceBenefitTemplate
    added = 0
    for source_key in NAVER_PAY_SEED:
        sid = resolve_registry_id(session, source_key)
        if sid is None:
            _log.info('[benefit-seed] SourceRegistry 미해결 → skip: %s', source_key)
            continue
        if _has_naver_row(session, sid):
            _log.info('[benefit-seed] 네이버 행 이미 존재 → skip: %s(id=%s)',
                      source_key, sid)
            continue
        session.add(SourceBenefitTemplate(
            source_id=sid,
            benefit_name='네이버페이 적립 1%',
            benefit_type='rate',
            value=0.01,
            category='정률',
            # ⚠ 'payment' 금지 — 결제 택1에 넣으면 카드와 상호배타 = 스펙 위반.
            apply_mode='accrue',
            pay_method=None,   # 네이버페이 적립은 결제카드 축이 아니다
            channel=None,
            enabled=True,
            sort_order=55,
        ))
        added += 1
    if added:
        session.commit()
    return added


def seed_source_card_discounts(session) -> int:
    """소싱처×카드 청구할인을 멱등 시드. 새로 넣은 행 수를 반환.

    CARD_DISCOUNT_SEED 가 비어 있으면 **완전 no-op** — 오늘이 그렇다.
    한 건이라도 들어오는 순간 그 소싱처의 가격 계산 경로가 legacy → tagged 로
    바뀐다(결제 택1 승자를 근사가 아니라 실제 최종가로 고름). 즉 **값을 채우는
    것 자체가 가격 변경**이다. 반드시 실제 확인된 값만 넣을 것.
    (캐시백↔카드 동시 차감은 tagged 전환과 무관하게 legacy 에서도 성립한다 —
    스펙 §4-1 · final_price.py:241~242 택1 후보 제외.)

    pay_method 는 VARCHAR(16) 이다 — PurchaseCard.key 는 이미 16자 이하로
    맞춰져 있으니 그대로 쓴다. 새 키를 만들지 않는다.
    """
    from lemouton.sourcing.models import SourceBenefitTemplate
    from lemouton.margin.purchase_card_store import get_card
    added = 0
    for source_key, card_key, name, rate in CARD_DISCOUNT_SEED:
        sid = resolve_registry_id(session, source_key)
        if sid is None:
            _log.info('[benefit-seed] SourceRegistry 미해결 → skip: %s', source_key)
            continue
        if get_card(session, card_key) is None:
            # 없는 카드를 가리키는 pay_method 는 card_candidates 가 후보로 인정하지
            # 않아 조용히 무시된다 → 넣지 않고 경고한다(조용한 실패 방지).
            _log.warning('[benefit-seed] 없는 카드 key → skip: %s × %s',
                         source_key, card_key)
            continue
        exists = (session.query(SourceBenefitTemplate)
                  .filter_by(source_id=sid, benefit_name=name).first())
        if exists is not None:
            continue
        session.add(SourceBenefitTemplate(
            source_id=sid,
            benefit_name=name,
            benefit_type='rate',
            value=float(rate),
            category='결제',
            apply_mode='payment',
            pay_method=card_key,
            channel=None,
            enabled=True,
            sort_order=60,
        ))
        added += 1
    if added:
        session.commit()
    return added


def seed_source_benefits(session) -> dict:
    """OK캐시백 + 카드 청구할인 + 리뷰적립 + L.POINT + 네이버페이 시드를 한 번에.

    {'cashback': n, 'card': m, 'review': k, 'lpoint': j, 'naver_pay': p}
    """
    return {
        'cashback': seed_ok_cashback(session),
        'card': seed_source_card_discounts(session),
        'review': seed_review_rewards(session),
        'lpoint': seed_lpoint(session),
        'naver_pay': seed_naver_pay(session),
    }
