# -*- coding: utf-8 -*-
"""[TEST] 소싱처별 OK캐시백 시드 — 저장 규약·멱등성 + 엔진 실반영 통합 검증.

대량등록 Phase 1B M1-5. 시드가 '들어갔다'로 끝나지 않고, compute_breakdown 을
실제로 태워 **엔진이 그 행을 어떻게 다루는지**까지 고정한다.

★ 이 테스트가 문서화하는 핵심 사실 (사장님 보고용)
  [정정 2026-07-22 — 스펙 §4-1 사용자 확정] 캐시백은 유입경로 축이라 결제카드와
  택1이 **아니다**. 카드 청구할인 행이 하나도 없는 오늘(legacy 경로)도
  `_compute_legacy` 가 택1 후보에서 캐시백을 제외하므로(final_price.py:241~242)
  롯데온·SSG 의 OK캐시백은 현대카드 2.73% 플로어와 **함께 차감된다** —
  즉 시드가 들어가는 순간 가격이 실제로 내려간다(아래
  test_cashback_applies_alongside_hyundai_floor 가 그 증거).
  종전 문구("택1에서 현대카드에 져서 미차감")는 그 제외가 들어가기 전의
  낡은 동작 기록이었다. 카드 청구할인 행이 1건이라도 생기면 tagged 경로로
  넘어가되, 캐시백 동시 차감이라는 사실 자체는 두 경로에서 동일하다.
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
    OK_CASHBACK_SEED, CARD_DISCOUNT_SEED, REVIEW_REWARD_SEED, NAVER_PAY_SEED,
    resolve_registry_id, seed_ok_cashback, seed_source_card_discounts,
    seed_review_rewards, seed_naver_pay,
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


# ════════════════════════════════════════════════════════════
#  4. 리뷰적립 시드 — 사장님 확정 2026-07-22 (스펙 §5)
# ════════════════════════════════════════════════════════════

# 사장님 확정 금액 — SourceRegistry.id → 차감액(원).
# 르무통·스스 = 포토(금액 큼), 무신사·SSF·롯데온·SSG = 텍스트.
REVIEW_EXPECTED_AMOUNTS = {
    1: 5000,          # 르무통 공홈 (포토)
    2: 5000,          # 스스 르무통 (포토)
    3: 500,           # 무신사 (텍스트)
    4: 200,           # SSF (텍스트)
    LOTTEON_ID: 50,   # 롯데온 (텍스트)
    SSG_ID: 50,       # SSG (텍스트)
}


def _review_rows(s, source_id):
    return [r for r in _tpl(s, source_id)
            if '리뷰' in (r.benefit_name or '') or '후기' in (r.benefit_name or '')]


def test_review_reward_seed_idempotent(db):
    """2회 호출 → 두 번째는 0 (멱등). 저장 규약 = amount/deduct/정액."""
    assert seed_review_rewards(db) == 6
    assert seed_review_rewards(db) == 0
    for sid, amount in REVIEW_EXPECTED_AMOUNTS.items():
        rows = _review_rows(db, sid)
        assert len(rows) == 1, f'source_id={sid} 리뷰 행은 정확히 1개여야'
        row = rows[0]
        assert row.benefit_type == 'amount'
        assert row.apply_mode == 'deduct'
        assert row.category == '정액'
        assert row.value == pytest.approx(amount)
        assert row.pay_method is None
        assert row.enabled is True


def test_review_seed_covers_confirmed_sources_only(db):
    """시드 대상 = 정수 registry id 가 있는 6곳뿐 (Hmall·롯데아이몰은 카탈로그 소싱처 — 대상 아님)."""
    keys = {k for k, _n, _v in REVIEW_REWARD_SEED}
    assert keys == {'lemouton', 'ss_lemouton', 'musinsa', 'ssf', 'lotteon', 'ssg'}


def test_review_seed_skips_existing_review_row(db):
    """이름에 '후기'/'리뷰' 포함 행이 이미 있으면 그 소싱처는 통째로 skip — 이중 차감 원천 차단.

    라이브 DB 에 수동으로 만든 무신사 '후기 적립' 500원 행이 실존한다 —
    거기에 시드가 또 얹으면 리뷰적립이 2번 차감된다(매입가 과소 = 금전 손실 방향).
    """
    db.add(SourceBenefitTemplate(
        source_id=3, benefit_name='후기 적립',
        benefit_type='amount', value=500, apply_mode='deduct', enabled=True))
    db.commit()
    assert seed_review_rewards(db) == 5       # 무신사 뺀 5곳만
    assert len(_tpl(db, 3)) == 1              # 무신사는 기존 1행 그대로


def test_review_seed_missing_registry_row_is_skipped(db):
    """SourceRegistry 행이 없으면 만들지 않고 건너뛴다 (seed_ok_cashback 과 동일 원칙)."""
    db.query(SourceRegistry).filter_by(id=SSG_ID).delete()
    db.commit()
    assert seed_review_rewards(db) == 5
    # skip 은 '안 넣는' 것이다 — 없는 소싱처에 행을 만들어 붙이지 않는다
    assert _tpl(db, SSG_ID) == []


def test_review_user_edited_value_survives_reseed(db):
    """사용자가 화면에서 고친 금액은 재부팅 시드가 덮지 않는다 (캐시백과 동일 원칙)."""
    seed_review_rewards(db)
    row = _review_rows(db, LOTTEON_ID)[0]
    row.value = 9999          # 사용자가 화면에서 수정
    db.commit()
    seed_review_rewards(db)   # 재부팅 시드
    rows = _review_rows(db, LOTTEON_ID)
    assert len(rows) == 1                       # 중복 행 없음
    assert rows[0].value == pytest.approx(9999)  # 수정값 보존


# ════════════════════════════════════════════════════════════
#  4-b. L.POINT 시드 — T8 후속 (스펙 §3-5 fx 갭 해소, 2026-07-23)
# ════════════════════════════════════════════════════════════

def test_lpoint_seed_columns_and_idempotent(db):
    """롯데온 전용 L.POINT 0.05% — 저장 규약 + 멱등.

    accrue = 결제 택1 밖·캐시백 축도 아님 → 카드 경로 선택과 무관하게
    (legacy·maxprice 두 경로 모두) 항상 차감된다. 계산 반영 자체는
    test_breakdown_lotteon_maxprice.py 가 경로별로 못 박는다.
    """
    from lemouton.sourcing.source_benefit_seed import seed_lpoint
    assert seed_lpoint(db) == 1
    assert seed_lpoint(db) == 0               # 멱등
    rows = [r for r in _tpl(db, LOTTEON_ID) if 'L.POINT' in (r.benefit_name or '')]
    assert len(rows) == 1
    row = rows[0]
    assert row.benefit_name == 'L.POINT 적립 0.05%'
    assert row.benefit_type == 'rate'
    assert row.value == pytest.approx(0.0005)
    assert row.category == '정률'
    assert row.apply_mode == 'accrue'
    assert row.pay_method is None
    assert row.enabled is True
    assert row.sort_order == 45


def test_lpoint_seed_skips_existing_lpointish_row(db):
    """이름에 'L.POINT'/'구매적립'/'LPOINT' 포함 행이 있으면 통째로 skip.

    가드 어휘 = api_benefits point_rewards 인젝션 turn-off 와 같은 3종 —
    가드가 더 좁으면 이름만 다른 기존 행과 공존해 L.POINT 가 이중 차감된다
    (매입가 과소 = 금전 손실 방향).
    """
    from lemouton.sourcing.source_benefit_seed import seed_lpoint
    db.add(SourceBenefitTemplate(
        source_id=LOTTEON_ID, benefit_name='구매적립 L.POINT (L.CLUB)',
        benefit_type='amount', value=633, enabled=True))
    db.commit()
    assert seed_lpoint(db) == 0               # 롯데온 skip → 넣을 곳 없음
    assert len(_tpl(db, LOTTEON_ID)) == 1     # 기존 1행 그대로


# ════════════════════════════════════════════════════════════
#  5. 네이버페이 1% 시드 — 사장님 확정 2026-07-22 (스펙 §4-3)
#     카드와 **동시 적용** (택1 아님) — apply_mode='accrue'
# ════════════════════════════════════════════════════════════

# 대상 = 르무통·스스·SSF 3곳뿐.
# (hmall=엔진주입 T3 / lotteon=조건부 T8 / ssg·lotteimall=N페이 미적용 — 사장님 확정)
NAVER_EXPECTED_IDS = {1, 2, 4}   # lemouton / ss_lemouton / ssf


def _naver_rows(s, source_id):
    return [r for r in _tpl(s, source_id) if '네이버' in (r.benefit_name or '')]


def test_naver_pay_seed_idempotent(db):
    """정확히 르무통·스스·SSF 3곳에만 생성. 2회 호출 → 두 번째는 0 (멱등)."""
    keys = set(NAVER_PAY_SEED)
    assert keys == {'lemouton', 'ss_lemouton', 'ssf'}

    assert seed_naver_pay(db) == 3
    assert seed_naver_pay(db) == 0

    for sid in NAVER_EXPECTED_IDS:
        rows = _naver_rows(db, sid)
        assert len(rows) == 1, f'source_id={sid} 네이버페이 행은 정확히 1개여야'
        row = rows[0]
        assert row.benefit_name == '네이버페이 적립 1%'
        assert row.benefit_type == 'rate'
        assert row.value == pytest.approx(0.01)
        assert row.category == '정률'
        assert row.apply_mode == 'accrue'   # ⚠ 'payment' 금지 — 택1이면 카드와 상호배타 = 스펙 위반
        assert row.enabled is True
        assert row.sort_order == 55
        assert row.pay_method is None

    # 대상 외 소싱처(무신사·롯데온·SSG)에는 단 한 행도 붙지 않는다
    for sid in (3, LOTTEON_ID, SSG_ID):
        assert _naver_rows(db, sid) == []


def test_naver_pay_seed_skips_existing_naver_row(db):
    """이름에 '네이버' 포함 행이 이미 있으면 그 소싱처는 통째로 skip — 이중 차감 원천 차단."""
    db.add(SourceBenefitTemplate(
        source_id=1, benefit_name='네이버페이 적립',
        benefit_type='rate', value=0.01, apply_mode='accrue', enabled=True))
    db.commit()
    assert seed_naver_pay(db) == 2            # 르무통 뺀 2곳만
    assert len(_naver_rows(db, 1)) == 1       # 르무통은 기존 1행 그대로


def test_naver_pay_not_in_payment_pick_one():
    """★ 금전 안전 계약 — 시드 행이 결제 택1 그룹에 절대 들어가면 안 된다.

    네이버페이 1% 는 카드 청구할인과 **동시 적용**이다 (사장님 확정, 스펙 §4-3).
    엔진 `_is_payment` 는 이름의 '네이버' 를 보고 택1에서 제외한다 (이름 계약).
    이 테스트는 그 계약을 못 박는다 — 엔진 헬퍼가 개명/개조되면 여기서 크게 깨진다.
    """
    from lemouton.pricing.final_price import _is_payment
    assert _is_payment('네이버페이 적립 1%') is False


def test_naver_pay_deducts_concurrently_with_card_row():
    """N페이 시드행 + 카드 payment 행 동시 존재 → compute_final_price 에서 둘 다 차감.

    (카드와 동시 적용 스펙 §4-3 의 엔드투엔드 고정 — 위 _is_payment 계약 테스트의
    통합판. Task 2 리뷰 이월분.)
    카드 행에 pay_method 태그가 있으므로 _is_tagged → tagged 경로. 경로 열거에서
    apply_mode='accrue' 인 네이버페이 행은 어느 결제 경로에서도 활성이라
    카드 7% 차감 **직후 잔액** 기준 1% 가 함께 빠져야 한다.
    """
    from lemouton.pricing.final_price import compute_final_price

    card_row = SourceBenefitTemplate(
        source_id=LOTTEON_ID, benefit_name='삼성카드 청구할인 7%(가정)',
        benefit_type='rate', value=0.07, category='결제',
        apply_mode='payment', pay_method='samsung_select', enabled=True)
    naver_row = SourceBenefitTemplate(   # 시드(seed_naver_pay)와 같은 모양
        source_id=LOTTEON_ID, benefit_name='네이버페이 적립 1%',
        benefit_type='rate', value=0.01, category='정률',
        apply_mode='accrue', sort_order=55, enabled=True)

    res = compute_final_price(SALE_PRICE, [('tpl', card_row), ('tpl', naver_row)])

    steps = {st['name']: st for st in res['steps']}
    assert '삼성카드 청구할인 7%(가정)' in steps, f"steps={list(steps)}"
    assert '네이버페이 적립 1%' in steps, f"steps={list(steps)}"
    # 카드 7% 먼저: int(100,000×0.07)=7,000 → 잔액 93,000
    assert steps['삼성카드 청구할인 7%(가정)']['deduct'] == 7_000
    # 네이버 차감 = int(직전잔액 93,000 × 0.01) = 930 — 동시 적용의 직접 증거
    assert steps['네이버페이 적립 1%']['deduct'] == int(93_000 * 0.01) == 930
    # 승자 경로 = 삼성카드 (무결제 경로 99,000 보다 92,070 이 낮다)
    assert res['path'] == {'pay_method': 'samsung_select', 'naver_via': False}
    assert res['final_price'] == 92_000   # 92,070 → 백원 버림
