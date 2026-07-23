# -*- coding: utf-8 -*-
"""롯데온 — 최대혜택가 베이스 + 카드 경로 규칙 + 보유카드 가드 (스펙 §3-5, 사장님 확정 2026-07-22).

■ 입력 (크롤 T6/T7 — b33e4be6/0384fe55/85b7164c)
  · lotteon_max_price      : 「최대 할인혜택 적용하기」 체크 후 나의 혜택가
                             (스토어 즉시할인 + **사이트가 고른 최적 카드 즉시할인** 포함 총액)
  · lotteon_card_discounts : [{label, amount(원), rate(퍼센트)}] — None=수집실패, []=카드없음 확인

■ 계산 규칙 (사장님 확정 — 그대로 옮김)
  1. 카드-프리 베이스 = 최대혜택가 + 사이트 선반영 최적카드(amount 최대) 즉시할인 **가산**.
     즉시할인은 사이트가 자기 기준으로 계산한 **정액(원)**이라 가산/차감이 정확하다.
  2. 경로 열거(엔진 _compute_tagged 실측 비교):
       · 보유 카드 c 경로      = 즉시할인(c) 차감 (+ c 가 현대카드면 잔액에 2.73% 추가)
       · 현대카드 무-즉시할인  = 즉시할인 포기 + 현대카드 2.73% + 네이버페이 1%
     → 실제 최종매입가가 가장 낮은 경로 자동 채택.
  3. 보유카드 가드: PurchaseCard 마스터(17종)에 있는 카드만 후보. **미보유** 카드가
     최적으로 선반영된 최대혜택가는 그 할인분을 되돌린(가산) 베이스로 계산 —
     애매한 라벨 매칭은 미보유 취급(가산 유지 = 매입가 과대 = 안전 방향).
  4. fx(오너스 0.5% 크롤값·OK캐시백 1.1%×0.9 시드행·리뷰적립 50원 시드행·
     L.POINT 0.05% 시드행 — T8 후속 갭 해소)는 카드 선택과 무관하게
     **모든 경로에서** 계속 차감.
  5. 상호배타(돈 방향 최우선): 즉시할인 경로에는 2.73%(fallback)·N페이가 절대 없고,
     N페이는 무-즉시할인(현대카드) 경로에만 있다. 동시 차감 = 매입가 과소 = 금지.

■ 시드는 진짜 시드 함수를 부른다 (source_benefit_seed.seed_ok_cashback/seed_review_rewards)
  — 시드 형태가 바뀌면 이 테스트가 같이 깨져야 한다(사본 시드 금지).
"""
import json

import pytest

from shared.db import SessionLocal
from lemouton.sourcing.models import OptionBenefitOverride, SourceBenefitTemplate
from lemouton.sourcing.models_pricing import OptionSourceUrl, SourceRegistry
from lemouton.sources.models import SourceProduct
from lemouton.pricing.card_candidates import HYUNDAI_FLOOR_KEY
from webapp.routes.api_benefits import compute_breakdown

LOTTEON = 5           # 계산 번호(source_ids._SITE_BY_PRICING_ID) — 화면 id 와 다른 체계
PREFIX = 'LMAX-'


def _url(sku):
    return f'https://example.test/lmax/{sku}'


@pytest.fixture(scope='module', autouse=True)
def _tables():
    for m in ('lemouton.sourcing.models', 'lemouton.sourcing.models_pricing',
              'lemouton.sources.models', 'lemouton.templates.models',
              'lemouton.inventory.models', 'lemouton.mapping.models',
              'lemouton.margin.models'):
        try:
            __import__(m)
        except ImportError:
            pass
    from shared.db import Base, engine, _apply_lightweight_migrations
    Base.metadata.create_all(engine)
    _apply_lightweight_migrations()


def _wipe(s):
    s.query(OptionBenefitOverride).filter(
        OptionBenefitOverride.canonical_sku.like(PREFIX + '%')).delete(
        synchronize_session=False)
    s.query(OptionSourceUrl).filter(
        OptionSourceUrl.canonical_sku.like(PREFIX + '%')).delete(
        synchronize_session=False)
    s.query(SourceProduct).filter(
        SourceProduct.url.like('https://example.test/lmax/%')).delete(
        synchronize_session=False)
    # 이 파일이 시드한 롯데온(5) 템플릿 제거 — 다른 테스트 파일 오염 방지
    s.query(SourceBenefitTemplate).filter_by(source_id=LOTTEON).delete(
        synchronize_session=False)
    s.commit()


@pytest.fixture
def sess():
    s = SessionLocal()
    _wipe(s)
    # ── 진짜 시드 함수가 롯데온을 id=5 로 해석하도록 SourceRegistry 를 정렬 ──
    #   resolve_registry_id 는 main_url 도메인 매칭(단일 히트만 인정)이므로,
    #   lotteon.com 을 물고 있는 행이 id=5 하나뿐이어야 한다(라이브와 같은 배치).
    for reg in s.query(SourceRegistry).all():
        if reg.id != LOTTEON and 'lotteon.com' in ((reg.main_url or '').lower()):
            reg.main_url = None
    reg5 = s.get(SourceRegistry, LOTTEON)
    if reg5 is None:
        s.add(SourceRegistry(id=LOTTEON, name='롯데온', main_url='https://lotteon.com'))
    else:
        reg5.main_url = 'https://lotteon.com'
    s.commit()
    # 카드 마스터(17종) — 보유 판정의 단일 진실 원천. 멱등(insert-if-missing).
    from lemouton.margin.purchase_card_store import seed_purchase_cards
    seed_purchase_cards(s)
    yield s
    _wipe(s)
    s.close()


def _seed(s, *, sku, dyn):
    """롯데온 시드 3종 — ①source-5 템플릿 초기화 후 **진짜 시드 함수** 호출
    ②OptionSourceUrl ③SourceProduct(dynamic_benefits_json)."""
    s.query(SourceBenefitTemplate).filter_by(source_id=LOTTEON).delete(
        synchronize_session=False)
    s.commit()
    from lemouton.sourcing.source_benefit_seed import (
        seed_ok_cashback, seed_review_rewards, seed_lpoint)
    seed_ok_cashback(s)
    seed_review_rewards(s)
    seed_lpoint(s)
    names = {t.benefit_name for t in
             s.query(SourceBenefitTemplate).filter_by(source_id=LOTTEON).all()}
    # 조용한 skip 방지 — 시드가 안 들어가면 아래 산식 전제가 무너진다(loud fail).
    assert ('OK캐시백' in names and '리뷰적립(텍스트)' in names
            and 'L.POINT 적립 0.05%' in names), (
        f'롯데온 시드 미적재(도메인 해석 실패 의심): {names}')
    s.add(OptionSourceUrl(canonical_sku=sku, source_id=LOTTEON, product_url=_url(sku)))
    s.add(SourceProduct(site='lotteon', url=_url(sku),
                        dynamic_benefits_json=json.dumps(dyn, ensure_ascii=False)))
    s.commit()


def _run(sku, sale_price=100000.0):
    s = SessionLocal()
    try:
        return compute_breakdown(s, sku=sku, source_id=LOTTEON,
                                 sale_price=sale_price)
    finally:
        s.rollback()
        s.close()


def _names(r):
    return [st['name'] for st in (r.get('steps') or [])]


def _assert_paths_exclusive(r):
    """경로 상호배타 단언 — 깨지면 이중 차감 = 매입가 과소(금전 위험 방향).

    · 즉시할인 step 은 최대 1개 (카드끼리 택1)
    · 즉시할인 ⟂ 네이버페이 / 즉시할인 ⟂ 현대카드 fallback (동시 금지)
    · 네이버페이 ⟹ 현대카드 fallback 동반 (무-즉시할인 경로의 짝)
    · 2.73% (카드결제 병행) ⟹ 현대카드 즉시할인 동반, fallback 과 동시 금지
    """
    names = _names(r)
    inst = [n for n in names if n.endswith(' 즉시할인')]
    npay = [n for n in names if '네이버페이' in n]
    floor = [n for n in names if '청구할인 fallback' in n]
    comp = [n for n in names if '카드결제 병행' in n]
    assert len(inst) <= 1, f'즉시할인 이중 차감: {names}'
    assert not (inst and npay), f'즉시할인+N페이 동시 차감(매입가 과소): {names}'
    assert not (inst and floor), f'즉시할인+현대fallback 동시 차감(매입가 과소): {names}'
    if npay:
        assert floor, f'N페이가 현대카드 무-즉시할인 경로 밖에서 차감됨: {names}'
    if comp:
        assert inst and '현대' in inst[0], (
            f'2.73% 병행이 현대카드 즉시할인 없이 차감됨: {names}')
        assert not floor, f'병행 2.73%+fallback 2.73% 이중 차감: {names}'


# ════════════════════════════════════════════════════════════════════════════
# 1. 베이스 교체 — 최대혜택가가 있으면 sale_price(매트릭스 표면가)는 무시된다
# ════════════════════════════════════════════════════════════════════════════

def test_max_price_overrides_sale_price_base(sess):
    """max_price 75,630 · 카드 [] · sale_price 99,999(무시) → 베이스 75,630.

    카드 없음 → 현대카드 2.73% + N페이 1% 경로 (스펙 표 3행):
        75,630 − 리뷰50                          = 75,580
        − L.POINT int(75,580×0.0005)=37          = 75,543
        − OK캐시백 int(75,543×0.9×0.011)=747     = 74,796
        − 오너스   int(74,796×0.005)=373         = 74,423
        − N페이    int(74,423×0.01)=744          = 73,679
        − 현대2.73% int(73,679×0.0273)=2,011     = 71,668 → 백원버림 71,600
    [T8 후속] L.POINT 0.05% 시드 추가로 71,700 → 71,600 (스펙 §3-5 fx 갭 해소 —
    구 산식: 75,580 −748 −374 −744 −2,012 = 71,702 → 71,700).
    """
    sku = PREFIX + 'base'
    _seed(sess, sku=sku, dyn={
        'lotteon_max_price': 75630,
        'lotteon_card_discounts': [],
        'lotte_member_discount_rate': 0.005,
    })
    r = _run(sku, sale_price=99999.0)
    assert r['sale_price'] == 75630.0, 'sale_price 가 아니라 최대혜택가가 베이스여야 한다'
    _assert_paths_exclusive(r)
    assert r['final_price'] == 71600


# ════════════════════════════════════════════════════════════════════════════
# 2. 선반영 최적 카드 = 현대카드 (보유) → 2.73% 추가 차감, N페이 없음
# ════════════════════════════════════════════════════════════════════════════

def test_best_card_hyundai_owned_deducts_273_on_top(sess):
    """사이트 라벨 '현대카드'(즉시할인 3,000) — 마스터 '넥슨현대카드' 에 매칭(보유).

    카드-프리 베이스 = 100,000 + 3,000 = 103,000.
    ① 현대 즉시할인 경로 (승자):
        103,000 − 리뷰50 = 102,950 − 즉시할인3,000 = 99,950
        − L.POINT int(99,950×0.0005)=49    = 99,901
        − OK캐시백 int(99,901×0.0099)=989  = 98,912
        − 오너스   int(98,912×0.005)=494   = 98,418
        − 병행2.73% int(98,418×0.0273)=2,686 = 95,732 → 백원버림 95,700
    ② 현대 무-즉시할인(N페이) 경로: 102,950 −51 −1,018 −509 −1,013 −2,739 = 97,620 (진다)
    스펙 §3-5 표 1행: 현대카드 선반영이면 **즉시할인 + 2.73% 둘 다** — N페이는 없다.
    [T8 후속] L.POINT 시드 추가 — 버림 전 95,779 → 95,732 이나 백원버림 최종가는
    95,700 그대로 (구 산식: 99,950 −989 −494 −2,688 = 95,779).
    """
    sku = PREFIX + 'hyun'
    _seed(sess, sku=sku, dyn={
        'lotteon_max_price': 100000,
        'lotteon_card_discounts': [{'label': '현대카드', 'amount': 3000, 'rate': 3}],
        'lotte_member_discount_rate': 0.005,
    })
    r = _run(sku)
    names = _names(r)
    assert r['sale_price'] == 103000.0, '가산(add-back) 베이스가 아니다'
    assert '현대카드 즉시할인' in names
    assert any('카드결제 병행' in n for n in names), '현대카드 자체 2.73% 추가 차감 누락'
    assert not any('네이버페이' in n for n in names)
    _assert_paths_exclusive(r)
    assert r['final_price'] == 95700


# ════════════════════════════════════════════════════════════════════════════
# 3. 미보유 카드 가드 — '카카오페이 카드' 는 마스터 '카카오뱅크(머니)' 와 매칭 금지
# ════════════════════════════════════════════════════════════════════════════

def test_unowned_card_added_back_falls_to_hyundai_npay(sess):
    """미보유 카드(카카오페이 카드, 5,000)가 선반영된 최대혜택가 → 가산 후 현대+N페이.

    보수 매칭 핀: '카카오페이카드' ↔ '카카오뱅크(머니)' 는 양방향 부분일치가 아니다
    → 미보유. (오매칭 = 없는 카드 할인 반영 = 매입가 과소 — 절대 금지 방향.)
    베이스 = 70,000 + 5,000 = 75,000. 보유 후보 없음 → 현대카드 2.73% + N페이 1%:
        75,000 − 50 = 74,950
        − L.POINT int(74,950×0.0005)=37     = 74,913
        − OK캐시백 int(74,913×0.0099)=741   = 74,172
        − 오너스   int(74,172×0.005)=370    = 73,802
        − N페이    int(73,802×0.01)=738     = 73,064
        − 현대2.73% int(73,064×0.0273)=1,994 = 71,070 → 백원버림 71,000
    [T8 후속] L.POINT 시드 추가로 71,100 → 71,000
    (구 산식: 74,950 −742 −371 −738 −1,995 = 71,104 → 71,100).
    """
    sku = PREFIX + 'kakao'
    _seed(sess, sku=sku, dyn={
        'lotteon_max_price': 70000,
        'lotteon_card_discounts': [{'label': '카카오페이 카드', 'amount': 5000, 'rate': 7}],
        'lotte_member_discount_rate': 0.005,
    })
    r = _run(sku)
    names = _names(r)
    assert r['sale_price'] == 75000.0, '미보유 카드 할인분이 가산(되돌림)되지 않았다'
    assert not any('카카오' in n for n in names), '미보유 카드 즉시할인이 차감됨(매입가 과소)'
    assert any('네이버페이' in n for n in names)
    assert any('청구할인 fallback' in n for n in names)
    _assert_paths_exclusive(r)
    assert r['final_price'] == 71000


# ════════════════════════════════════════════════════════════════════════════
# 4. 보유 타카드 즉시할인이 크면 그 카드 경로 승리 — 2.73%·N페이 둘 다 없음
# ════════════════════════════════════════════════════════════════════════════

def test_owned_other_card_big_instant_wins(sess):
    """신한카드(마스터 정확일치 = 보유) 즉시할인 6,000 > 현대 대안 → 신한 경로 승리.

    베이스 = 100,000 + 6,000 = 106,000.
    ① 신한 즉시할인 경로 (승자):
        106,000 − 50 = 105,950 − 6,000 = 99,950
        − L.POINT 49 = 99,901 − OK캐시백 989 = 98,912 − 오너스 494 = 98,418
        → 백원버림 98,400
    ② 현대 무-즉시할인 경로: 105,950 −52 −1,048 −524 −1,043 −2,819 = 100,464 (진다)
    스펙 §3-5 표 2행: 타 카드(보유) 결제 가정 → 2.73%·N페이 1% 차감 **안 함**.
    [T8 후속] L.POINT 시드 추가 — 버림 전 98,467 → 98,418 이나 최종가 98,400 그대로
    (구 산식: 99,950 −989 −494 = 98,467).
    """
    sku = PREFIX + 'shinhan-big'
    _seed(sess, sku=sku, dyn={
        'lotteon_max_price': 100000,
        'lotteon_card_discounts': [{'label': '신한카드', 'amount': 6000, 'rate': 6}],
        'lotte_member_discount_rate': 0.005,
    })
    r = _run(sku)
    names = _names(r)
    assert '신한카드 즉시할인' in names
    assert not any('현대카드' in n for n in names)
    assert not any('네이버페이' in n for n in names)
    _assert_paths_exclusive(r)
    assert r['final_price'] == 98400


# ════════════════════════════════════════════════════════════════════════════
# 5. 작은 즉시할인(2%) vs 현대 2.73%+N페이 → 현대 경로 자동 승리 (열거 증명)
# ════════════════════════════════════════════════════════════════════════════

def test_small_instant_loses_to_hyundai_enumeration(sess):
    """신한카드 즉시할인 2,000(2%) < 현대 2.73%+N페이 1% → 현대 경로 자동 채택.

    베이스 = 100,000 + 2,000 = 102,000.
    ① 신한 경로: 101,950 −2,000 = 99,950 −49 −989 −494 = 98,418 (진다)
    ② 현대 무-즉시할인 경로 (승자):
        101,950 − L.POINT int(101,950×0.0005)=50     = 101,900
        − OK캐시백 int(101,900×0.0099)=1,008         = 100,892
        − 오너스 int(100,892×0.005)=504              = 100,388
        − N페이 int(100,388×0.01)=1,003              = 99,385
        − 현대2.73% int(99,385×0.0273)=2,713         = 96,672 → 백원버림 96,600
    스펙 열거 정밀화 예시 그대로: 「타 카드 즉시할인 2% < 현대 2.73% → 현대 경로 자동 승리」.
    [T8 후속] L.POINT 시드 추가로 96,700 → 96,600
    (구 산식: 101,950 −1,009 −504 −1,004 −2,714 = 96,719 → 96,700).
    """
    sku = PREFIX + 'shinhan-small'
    _seed(sess, sku=sku, dyn={
        'lotteon_max_price': 100000,
        'lotteon_card_discounts': [{'label': '신한카드', 'amount': 2000, 'rate': 2}],
        'lotte_member_discount_rate': 0.005,
    })
    r = _run(sku)
    names = _names(r)
    assert '신한카드 즉시할인' not in names, '즉시할인 경로가 현대 대안을 이겨선 안 되는 케이스'
    assert any('네이버페이' in n for n in names)
    assert any('청구할인 fallback' in n for n in names)
    _assert_paths_exclusive(r)
    assert (r.get('path') or {}).get('pay_method') == HYUNDAI_FLOOR_KEY
    assert r['final_price'] == 96600


# ════════════════════════════════════════════════════════════════════════════
# 6. 카드 없음 — [](카드없음 확인) 과 None(수집실패) 모두 현대 2.73% + N페이 1%
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize('cards', [[], None], ids=['empty-list', 'null'])
def test_no_cards_hyundai_plus_npay(sess, cards):
    """카드 즉시할인 없는 상품(스펙 표 3행) → 현대카드 2.73% + N페이 1% 둘 다 차감.

    베이스 = 100,000 (가산할 카드 없음):
        100,000 − 50 = 99,950
        − L.POINT 49 = 99,901 − OK캐시백 989 = 98,912 − 오너스 494 = 98,418
        − N페이 int(98,418×0.01)=984 = 97,434
        − 현대2.73% int(97,434×0.0273)=2,659 = 94,775 → 백원버림 94,700
    [T8 후속] L.POINT 시드 추가로 94,800 → 94,700
    (구 산식: 99,950 −989 −494 −984 −2,661 = 94,822 → 94,800).
    """
    sku = PREFIX + ('nocard-e' if cards == [] else 'nocard-n')
    dyn = {'lotteon_max_price': 100000, 'lotte_member_discount_rate': 0.005}
    if cards is not None:
        dyn['lotteon_card_discounts'] = cards
    _seed(sess, sku=sku, dyn=dyn)
    r = _run(sku)
    names = _names(r)
    assert any('네이버페이' in n for n in names)
    assert any('청구할인 fallback' in n for n in names)
    assert not any(n.endswith(' 즉시할인') for n in names)
    _assert_paths_exclusive(r)
    assert r['final_price'] == 94700


# ════════════════════════════════════════════════════════════════════════════
# 7. max_price 없음(수집실패/구데이터) → 기존 동작 그대로 (박제 — 무회귀)
# ════════════════════════════════════════════════════════════════════════════

def test_max_price_absent_legacy_unchanged(sess):
    """lotteon_max_price 가 없으면 종전 legacy 경로 그대로 (path=None·베이스=sale_price).

    T8 구현 **전** 실측 박제(characterization first)는 95,700 이었고, T8 후속의
    L.POINT 0.05% 시드(스펙 §3-5 fx 갭 해소 — 의도된 금액 변경)로 legacy 경로에도
    L.POINT 한 단계가 추가된다:
        sale_price 100,000 이 그대로 베이스.
        100,000 − 리뷰50 = 99,950
        − L.POINT int(99,950×0.0005)=49      = 99,901
        − OK캐시백 int(99,901×0.9×0.011)=989 = 98,912
        − 오너스   int(98,912×0.005)=494     = 98,418
        − 현대2.73%(fallback) int(98,418×0.0273)=2,686 = 95,732 → 백원버림 95,700
    (구 산식: 99,950 −989 −494 −2,688 = 95,779 → 같은 95,700 — 버림 전만 다르다.)
    태그 0건 → path=None (legacy). N페이 없음(롯데온은 NAVER_PAY_SEED 대상 아님).
    """
    sku = PREFIX + 'legacy'
    _seed(sess, sku=sku, dyn={'lotte_member_discount_rate': 0.005})
    r = _run(sku)
    names = _names(r)
    assert r['sale_price'] == 100000.0
    assert any('청구할인 fallback' in n for n in names)
    assert 'L.POINT 적립 0.05%' in names, 'L.POINT 시드는 legacy 경로에서도 차감'
    assert not any('네이버페이' in n for n in names)
    assert r.get('path') is None, 'max_price 없는 상품이 tagged 로 끌려가면 회귀'
    assert r['final_price'] == 95700


# ════════════════════════════════════════════════════════════════════════════
# 8. fx(오너스·캐시백·리뷰)는 어느 경로에서도 계속 차감 — 두 경로 스팟체크
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize('cards, sku_tag', [
    ([{'label': '현대카드', 'amount': 3000, 'rate': 3}], 'fx-hyun'),   # 즉시할인 경로
    ([], 'fx-nocard'),                                                  # 무-즉시할인 경로
], ids=['hyundai-instant-path', 'no-card-path'])
def test_fx_rows_deduct_in_every_path(sess, cards, sku_tag):
    """오너스 0.5% + OK캐시백 1.1%(×0.9) + 리뷰 50원 + L.POINT 0.05% —
    카드 경로와 독립, 전 경로 차감 (L.POINT 는 sweep 비대상: 결제 토큰 없음)."""
    sku = PREFIX + sku_tag
    _seed(sess, sku=sku, dyn={
        'lotteon_max_price': 100000,
        'lotteon_card_discounts': cards,
        'lotte_member_discount_rate': 0.005,
    })
    r = _run(sku)
    names = _names(r)
    assert any('오너스' in n or '회원' in n for n in names), f'오너스 누락: {names}'
    assert 'OK캐시백' in names, f'OK캐시백 누락: {names}'
    assert '리뷰적립(텍스트)' in names, f'리뷰적립 누락: {names}'
    assert 'L.POINT 적립 0.05%' in names, f'L.POINT 누락(sweep 오폭 의심): {names}'
    _assert_paths_exclusive(r)
    # OK캐시백은 공급가 기준(×0.9) — 시드 base_ratio 가 tagged 경로에서도 유지되는지
    cb = next(st for st in r['steps'] if st['name'] == 'OK캐시백')
    assert cb['base_ratio'] == pytest.approx(0.9), '캐시백 공급가 계수 유실(10% 과다 차감)'


# ════════════════════════════════════════════════════════════════════════════
# 8-b. 보유카드 라벨 매처 핀 — 주석이 약속한 매칭 표를 함수 단위로 못 박는다
# ════════════════════════════════════════════════════════════════════════════

_MASTER_LABELS = ['넥슨현대카드', '롯데프로페셔널', '카카오뱅크(머니)', '국민카드']


@pytest.mark.parametrize('site_label, expected', [
    ('현대카드', True),          # '현대카드' ⊂ '넥슨현대카드' (짧은 쪽 4자)
    ('KB국민카드', True),        # 'KB국민카드' ⊃ '국민카드'
    ('카카오페이 카드', False),  # '카카오페이카드' ↔ '카카오뱅크(머니)' 비매칭 (보수)
    ('롯데카드', False),         # '롯데카드' ↔ '롯데프로페셔널' 비매칭 (애매=미보유)
    ('카드', False),             # 3자 미만 일반명사 — 어느 방향도 매칭 금지
], ids=['hyundai-substr', 'kb-superstr', 'kakao-no', 'lotte-no', 'too-short'])
def test_match_owned_card_label_pins(site_label, expected):
    """match_owned_card_label 보수 매칭 규칙 핀.

    오매칭(가짜 보유) = 없는 카드 즉시할인 반영 = 매입가 과소 — 절대 금지 방향.
    미보유 오판은 가산 유지(매입가 과대 = 안전)뿐이라, 애매하면 전부 False 다.
    """
    from lemouton.pricing.card_candidates import match_owned_card_label
    assert match_owned_card_label(site_label, _MASTER_LABELS) is expected


# ════════════════════════════════════════════════════════════════════════════
# 8-c. L.POINT 시드 ↔ point_rewards 크롤 인젝션 — 정확히 한 행만 차감 (트립와이어)
# ════════════════════════════════════════════════════════════════════════════

def test_lpoint_seed_vs_point_rewards_injection_tripwire(sess):
    """크롤이 point_rewards 를 내보내면 시드 L.POINT 행은 꺼지고 인젝션 행만 남는다.

    api_benefits 의 point_rewards 블록은 자기 행('구매적립 L.POINT (L.CLUB)')을
    넣기 전에 이름에 'L.POINT'/'구매적립'/'LPOINT' 가 든 기존 행을 끈다 — 시드
    이름('L.POINT 적립 0.05%')이 그 turn-off 에 걸리는지를 여기서 못 박는다.
    깨지면(시드 개명 등) L.POINT 가 **이중 차감** = 매입가 과소 = 금전 위험.

    산식 (legacy — max_price 없음, club_point 633):
        100,000 − 리뷰50 = 99,950 − 구매적립633 = 99,317
        − OK캐시백 int(99,317×0.0099)=983 = 98,334
        − 오너스   int(98,334×0.005)=491  = 97,843
        − 현대2.73% int(97,843×0.0273)=2,671 = 95,172 → 백원버림 95,100
    """
    sku = PREFIX + 'lpoint-trip'
    _seed(sess, sku=sku, dyn={
        'lotte_member_discount_rate': 0.005,
        'point_rewards': {'label': 'L.POINT', 'default_point': 316,
                          'club_point': 633},
    })
    r = _run(sku)
    names = _names(r)
    lpointish = [n for n in names
                 if 'L.POINT' in n or '구매적립' in n or 'LPOINT' in n.upper()]
    assert lpointish == ['구매적립 L.POINT (L.CLUB)'], (
        f'L.POINT 성 차감은 정확히 1행(인젝션)이어야 한다 — 실제: {lpointish}')
    assert 'L.POINT 적립 0.05%' not in names, '시드 행이 인젝션과 이중 차감됨(매입가 과소)'
    assert r['final_price'] == 95100


# ════════════════════════════════════════════════════════════════════════════
# 9. 조립부 가드 — 선태깅 합성키를 tagged 조립이 재태깅하지 않는다 (짝 분해 방지)
# ════════════════════════════════════════════════════════════════════════════

def test_card_candidates_preserve_pretagged_synthetic_keys():
    """(향후 롯데온 청구할인 시드 대비) master 키 청구할인 행이 등장해 tagged 조립이
    켜져도, 롯데온 maxprice 모드가 선태깅한 짝 행('현대카드 즉시할인' + '2.73% 병행',
    같은 합성키)은 재태깅(__otherN__)되면 안 된다 — 짝이 서로 다른 키로 갈라지면
    「즉시할인만 차감」·「2.73%만 차감」 경로로 분해된다(차감 축소 = 매입가 과대
    방향이긴 하나 스펙과 다른 비의도 계산).
    """
    from lemouton.pricing.card_candidates import apply_card_candidates

    class Row:
        def __init__(self, *, name, btype='rate', value=0.0,
                     apply_mode=None, pay_method=None):
            self.id = -1
            self.benefit_name = name
            self.benefit_type = btype
            self.value = value
            self.enabled = True
            self.category = None
            self.apply_mode = apply_mode
            self.pay_method = pay_method
            self.channel = None
            self.sort_order = 0
            self.template_id = None

    class Card:
        key = 'samsung_select'
        label = '삼성셀렉트'
        accrual_rate = 0.01
        is_hyundai_default = False
        active = True

    eff = [
        ('dyn', Row(name='현대카드 즉시할인', btype='amount', value=3000.0,
                    apply_mode='payment', pay_method='__lo_card1__')),
        ('dyn', Row(name='현대카드 2.73% (카드결제 병행)', value=0.0273,
                    apply_mode='payment', pay_method='__lo_card1__')),
        ('tpl', Row(name='삼성카드 청구할인', value=0.07,
                    apply_mode='payment', pay_method='samsung_select')),
    ]
    out, info = apply_card_candidates(eff, [Card()], floor=None)
    assert info['mode'] == 'tagged'
    kept = {it.benefit_name: getattr(it, 'pay_method', None) for _k, it in out}
    assert kept['현대카드 즉시할인'] == '__lo_card1__'
    assert kept['현대카드 2.73% (카드결제 병행)'] == '__lo_card1__'
