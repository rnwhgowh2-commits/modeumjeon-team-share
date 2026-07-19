# -*- coding: utf-8 -*-
"""[TEST] 소싱처별 OK캐시백 시드 — 저장 규약·멱등성 + 엔진 실반영 통합 검증.

대량등록 Phase 1B M1-5. 시드가 '들어갔다'로 끝나지 않고, compute_breakdown 을
실제로 태워 **엔진이 그 행을 어떻게 다루는지**까지 고정한다.

★ 이 테스트가 문서화하는 핵심 사실 (사장님 보고용)
  카드 청구할인 행이 하나도 없는 오늘, 롯데온·SSG 의 OK캐시백은 legacy 결제 택1
  그룹에 들어가 **현대카드 2.73% 플로어에 져서 차감되지 않는다**
  (final_price._is_payment 가 이름의 '캐시백' 을 결제수단으로 보기 때문).
  즉 시드는 데이터로는 들어가지만 가격은 오늘 1원도 움직이지 않는다.
  카드 청구할인 행이 1건이라도 생기면 tagged 경로로 넘어가면서
  캐시백이 결제 택1에서 빠져나와 카드와 **함께** 차감된다.
"""
import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

os.environ.setdefault("ENVIRONMENT", "test")

for _m in (
    "lemouton.sourcing.models", "lemouton.sourcing.models_pricing",
    "lemouton.sourcing.models_v2", "lemouton.pricing.settings",
    "lemouton.uploader.models", "lemouton.templates.models",
    "lemouton.inventory.models", "lemouton.sources.models",
    "lemouton.multitenancy.models", "lemouton.audit.models",
    "lemouton.mapping.models", "lemouton.margin.models",
):
    try:
        __import__(_m)
    except ImportError:
        pass

from shared.db import Base
from lemouton.sourcing.models import SourceBenefitTemplate
from lemouton.sourcing.models_pricing import SourceRegistry
from lemouton.sourcing.source_benefit_seed import (
    OK_CASHBACK_SEED, CARD_DISCOUNT_SEED,
    resolve_registry_id, seed_ok_cashback, seed_source_card_discounts,
)

# api_benefits._SITE_BY_SRC 는 SourceRegistry.id 를 사이트 키로 **하드코딩** 한다
#   {1:'lemouton', 2:'ss_lemouton', 3:'musinsa', 4:'ssf', 5:'lotteon', 6:'ssg'}
# → 테스트 DB 도 라이브와 같은 id 로 만들어야 현대카드 플로어 경로가 재현된다.
LOTTEON_ID = 5
SSG_ID = 6

SKU = "LT-블랙-260"
SALE_PRICE = 100_000


@pytest.fixture
def db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = Session(eng)
    # 라이브와 같은 id 배치 (migrate_pricing_v3 의 등록 순서)
    s.add_all([
        SourceRegistry(id=1, name="르무통 공홈", main_url="https://www.lemouton.co.kr"),
        SourceRegistry(id=2, name="스스 르무통", main_url="https://smartstore.naver.com/lemouton"),
        SourceRegistry(id=3, name="무신사", main_url="https://musinsa.com"),
        SourceRegistry(id=4, name="SSF", main_url="https://ssfshop.com"),
        SourceRegistry(id=LOTTEON_ID, name="롯데온", main_url="https://lotteon.com"),
        SourceRegistry(id=SSG_ID, name="SSG", main_url="https://www.ssg.com"),
    ])
    s.commit()
    yield s
    s.close()


def _tpl(s, source_id):
    return (s.query(SourceBenefitTemplate)
            .filter_by(source_id=source_id).all())


# ════════════════════════════════════════════════════════════
#  1. 저장 규약 — 어떤 컬럼에 무엇이 들어가나
# ════════════════════════════════════════════════════════════

def test_registry_id_resolved_by_domain(db):
    assert resolve_registry_id(db, 'lotteon') == LOTTEON_ID
    assert resolve_registry_id(db, 'ssg') == SSG_ID


def test_seed_writes_expected_columns(db):
    assert seed_ok_cashback(db) == 2

    lo = _tpl(db, LOTTEON_ID)
    assert len(lo) == 1
    row = lo[0]
    assert row.benefit_name == 'OK캐시백'
    assert row.benefit_type == 'rate'
    assert row.value == pytest.approx(0.011)
    assert row.apply_mode == 'cashback'
    assert row.pay_method is None        # 캐시백은 결제카드 축이 아니다
    assert row.category == '캐시백'
    assert row.channel is None
    assert row.enabled is True

    # 적립율은 원본 그대로 — 0.9 를 미리 곱해 넣지 않는다(영수증에 1.1% 가 1.1% 로 보여야).
    assert row.base_ratio == pytest.approx(0.9)

    sg = _tpl(db, SSG_ID)
    assert len(sg) == 1
    assert sg[0].value == pytest.approx(0.02)
    # SSG 는 **전액 기준 예외 3사**(SSG·신세계쇼핑·CJ) — 계수 1.0
    assert sg[0].base_ratio == pytest.approx(1.0)


def test_only_mapped_sources_are_seeded(db):
    """보류(hmall·lotteimall)·판매처(11번가·옥션·지마켓)·미보유(더현대 등)는 시드 대상 아님."""
    keys = {k for k, _n, _v, _r in OK_CASHBACK_SEED}
    assert keys == {'ssg', 'lotteon'}
    seed_ok_cashback(db)
    # 매핑되지 않은 소싱처에는 단 한 행도 붙지 않는다
    for sid in (1, 2, 3, 4):
        assert _tpl(db, sid) == []


def test_card_discount_seed_is_empty_today(db):
    """확인된 카드 청구할인이 없으므로 오늘은 완전 no-op (지어낸 값 없음)."""
    assert CARD_DISCOUNT_SEED == []
    assert seed_source_card_discounts(db) == 0


# ════════════════════════════════════════════════════════════
#  2. 멱등성 — 사용자가 고친 값을 덮지 않는다
# ════════════════════════════════════════════════════════════

def test_seed_is_idempotent(db):
    assert seed_ok_cashback(db) == 2
    assert seed_ok_cashback(db) == 0
    assert len(_tpl(db, LOTTEON_ID)) == 1


def test_user_edited_value_survives_reseed(db):
    seed_ok_cashback(db)
    row = _tpl(db, LOTTEON_ID)[0]
    row.value = 0.05          # 사용자가 화면에서 수정
    db.commit()
    seed_ok_cashback(db)      # 재부팅 시드
    assert _tpl(db, LOTTEON_ID)[0].value == pytest.approx(0.05)


def test_existing_cashback_row_under_other_name_blocks_seed(db):
    """라이브에 이름만 다른 캐시백 행이 있으면 시드 skip — 이중 차감 원천 차단."""
    db.add(SourceBenefitTemplate(
        source_id=LOTTEON_ID, benefit_name='OK캐시백 1.1%',
        benefit_type='rate', value=0.011, apply_mode='cashback', enabled=True))
    db.commit()
    assert seed_ok_cashback(db) == 1          # SSG 만 들어간다
    assert len(_tpl(db, LOTTEON_ID)) == 1     # 롯데온은 기존 1행 그대로


def test_missing_registry_row_is_skipped_not_invented(db):
    """SourceRegistry 행이 없으면 만들지 않고 건너뛴다 (엉뚱한 소싱처 부착 방지)."""
    db.query(SourceRegistry).filter_by(id=LOTTEON_ID).delete()
    db.commit()
    assert seed_ok_cashback(db) == 1
    assert resolve_registry_id(db, 'lotteon') is None


# ════════════════════════════════════════════════════════════
#  3. 통합 — 엔진(compute_breakdown)이 실제로 어떻게 다루나
# ════════════════════════════════════════════════════════════

def _breakdown(db, source_id):
    from webapp.routes.api_benefits import compute_breakdown
    return compute_breakdown(db, sku=SKU, source_id=source_id,
                             sale_price=SALE_PRICE)


def _item(res, name_part):
    for it in res['items_used']:
        if name_part in (it['name'] or ''):
            return it
    return None


def test_engine_sees_the_seeded_row(db):
    """시드 행이 계산 항목(items_used)에 실제로 들어온다 = 배선 확인."""
    seed_ok_cashback(db)
    res = _breakdown(db, LOTTEON_ID)
    assert _item(res, 'OK캐시백') is not None


def test_cashback_applies_alongside_hyundai_floor(db):
    """캐시백과 결제카드는 **별개 축** — 둘 다 차감된다.

    ★ 이 테스트는 원래 그 반대("캐시백이 결제 택1에서 현대카드에 진다")를 오늘의
      실제 동작으로 못박고 있었다. 그게 곧 버그였다 — `_is_payment` 가 이름의
      '캐시백' 을 결제수단으로 봐서 OK캐시백 1.1% 가 현대카드 2.73% 에 택1로 졌다.
      확정 설계(2026-06-07 §4)의 세트 제약은 ①결제수단 택1(제휴카드⟷네이버페이)
      ②naver_via ⟹ 캐시백 off **둘뿐**이고, 캐시백⟷카드 택1은 없다.
      `_compute_legacy` 의 택1 후보에서 캐시백을 빼는 것으로 교정했다.

    ⇒ 시드가 이제 실제로 가격을 낮춘다(= 그동안 캐시백을 못 먹고 있었다는 뜻).
    """
    before = _breakdown(db, LOTTEON_ID)['final_price']
    seed_ok_cashback(db)
    after = _breakdown(db, LOTTEON_ID)
    assert _item(after, 'OK캐시백')['enabled'] is True
    assert _item(after, '현대카드')['enabled'] is True
    assert after['final_price'] < before, '캐시백이 차감되면 매입가가 내려가야 한다'


def test_card_discount_row_flips_to_tagged_and_cashback_applies(db):
    """카드 청구할인 행이 1건 생기면 tagged 경로 → 캐시백이 카드와 **함께** 차감.

    ⚠ 여기 쓰는 삼성카드 7% 는 **가정값**이다(테스트 픽스처). 시드에는 넣지 않았다 —
      확인된 청구할인이 없기 때문. 이 테스트는 "값이 채워지면 무슨 일이 일어나는가"를
      고정하는 용도다.
    """
    from lemouton.margin.purchase_card_store import seed_purchase_cards
    seed_purchase_cards(db)
    seed_ok_cashback(db)

    db.add(SourceBenefitTemplate(
        source_id=LOTTEON_ID, benefit_name='삼성카드 청구할인 7%(가정)',
        benefit_type='rate', value=0.07, category='결제',
        apply_mode='payment', pay_method='samsung_select', enabled=True))
    db.commit()

    res = _breakdown(db, LOTTEON_ID)
    # 캐시백이 결제 택1에서 빠져나와 활성
    assert _item(res, 'OK캐시백')['enabled'] is True
    # 카드 후보(적립 항목)가 주입됐다
    assert any('적립' in (it['name'] or '') for it in res['items_used'])
    # 최유리 카드 = 삼성셀렉트(청구 7% + 적립 1%) 가 채택돼 현대카드 플로어를 이긴다
    assert _item(res, '삼성카드 청구할인')['enabled'] is True
    assert res['final_price'] < _breakdown(db, SSG_ID)['final_price']
