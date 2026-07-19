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
# ════════════════════════════════════════════════════════════════════════════
OK_CASHBACK_SEED: list[tuple[str, str, float]] = [
    # SSG 2% — 크롤가이드(scripts/populate_ssg_guide.py) 의
    #          {"name": "OK캐시백", "apply": "cashback", "rule": "베이스금액② × 2%"} 와 일치.
    ('ssg',     'OK캐시백', 0.02),
    # 롯데온 1.1%
    ('lotteon', 'OK캐시백', 0.011),
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
#    (카드 적립 + 청구할인) 최유리 카드 자동 선택이 켜지고, 같은 순간
#    OK캐시백도 결제 택1에서 빠져나와 카드와 **함께** 차감된다
#    (card_candidates._is_cashback). 아래 seed_source_card_discounts 의
#    docstring 과 시드표 문서를 반드시 같이 읽을 것.
# ════════════════════════════════════════════════════════════════════════════
CARD_DISCOUNT_SEED: list[tuple[str, str, str, float]] = [
    # 예시 형식 (주석 — 실행되지 않는다):
    # ('lotteimall', 'samsung_select', '삼성카드 청구할인 7%', 0.07),
]


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
    for source_key, name, rate in OK_CASHBACK_SEED:
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
            pay_method=None,   # 캐시백은 결제카드 축이 아니다 (유입경로 축)
            channel=None,
            enabled=True,
            sort_order=50,
        ))
        added += 1
    if added:
        session.commit()
    return added


def seed_source_card_discounts(session) -> int:
    """소싱처×카드 청구할인을 멱등 시드. 새로 넣은 행 수를 반환.

    CARD_DISCOUNT_SEED 가 비어 있으면 **완전 no-op** — 오늘이 그렇다.
    한 건이라도 들어오는 순간 그 소싱처의 가격 계산 경로가 legacy → tagged 로
    바뀐다(결제 택1 승자를 근사가 아니라 실제 최종가로 고름 + 캐시백이 카드와
    분리되어 함께 차감). 즉 **값을 채우는 것 자체가 가격 변경**이다. 반드시
    실제 확인된 값만 넣을 것.

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
    """OK캐시백 + 카드 청구할인 시드를 한 번에. {'cashback': n, 'card': m}."""
    return {
        'cashback': seed_ok_cashback(session),
        'card': seed_source_card_discounts(session),
    }
