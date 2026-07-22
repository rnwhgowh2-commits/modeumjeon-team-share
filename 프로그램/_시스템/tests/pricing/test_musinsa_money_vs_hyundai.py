# -*- coding: utf-8 -*-
"""무신사 — 무신사머니 vs 현대카드 2.73% 차감 큰 쪽 자동 택1 (스펙 §3-3, 사용자 확정 2026-07-22).

종전 규칙: "머니가 잡히면(금액>0) 무조건 머니, 현대카드 플로어는 하드 비활성".
새 규칙:   머니 경로와 현대카드 경로를 **둘 다 결제 후보**로 만들고, 엔진의
           tagged 경로 열거(_compute_tagged)가 실제 최종매입가가 낮은 쪽을 고른다.

돈 방향 주의(이 저장소 최우선 원칙):
  머니와 현대카드가 **동시에** 차감되면 매입가 과소(마진 과대 착각 → 언더프라이싱).
  반드시 정확히 하나만(또는 무결제 None) 차감돼야 한다 — 전 테스트에서 상호배타를 단언한다.

메커니즘(구현 트레이스):
  · 무신사머니 결제 적립 행 → apply_mode='payment', pay_method='mus_money'
    (PurchaseCard 마스터의 실제 key — accrual_rate 0.0 이라 카드적립 이중 주입 없음)
  · 현대카드 플로어 → enabled=True 상시 + (머니>0 일 때) pay_method=HYUNDAI_FLOOR_KEY
    선태깅 — purchase_cards 미시드 환경에서도 상호배타가 보장된다.
  · 머니 없음(0/None) → 아무 태그도 안 붙어 legacy 경로 그대로(현대카드 단독 차감).
"""
import json

import pytest

from shared.db import SessionLocal
from lemouton.sourcing.models import OptionBenefitOverride
from lemouton.sourcing.models_pricing import OptionSourceUrl
from lemouton.sources.models import SourceProduct
from lemouton.pricing.card_candidates import HYUNDAI_FLOOR_KEY
from webapp.routes.api_benefits import compute_breakdown

MUSINSA = 3           # 계산 번호(_SITE_BY_SRC) — 화면 소싱처 id 와 다른 체계
PREFIX = 'MVSH-'      # money-vs-hyundai
MONEY_NAME = '무신사머니 결제 적립'


def _url(sku):
    return f'https://example.test/mvsh/{sku}'


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
        SourceProduct.url.like('https://example.test/mvsh/%')).delete(
        synchronize_session=False)
    s.commit()


@pytest.fixture
def sess():
    s = SessionLocal()
    _wipe(s)
    yield s
    _wipe(s)
    s.close()


def _seed(s, *, sku, money):
    """표면가 100,000 · 다른 혜택 없음 — 머니 금액만 바꿔 두 경로를 정면 비교."""
    # 앞선 테스트 파일이 musinsa(3)에 남긴 소싱처 템플릿 제거 — 예: characterization 의
    # test_benefits_unavailable_keeps_full_price 가 심은 '등급적립' 5,000 은 그 파일
    # _wipe 대상이 아니라서 잔류한다(순서 오염). 이 비교 테스트는 머니 vs 현대카드
    # 두 항목만 있어야 산식이 성립하므로 여기서 직접 비운다.
    from lemouton.sourcing.models import SourceBenefitTemplate
    s.query(SourceBenefitTemplate).filter_by(source_id=MUSINSA).delete(
        synchronize_session=False)
    dyn = {'surface_price': 100000}
    if money is not None:
        dyn['money_reward_amount'] = money
        dyn['money_active'] = bool(money)
    s.add(OptionSourceUrl(canonical_sku=sku, source_id=MUSINSA, product_url=_url(sku)))
    s.add(SourceProduct(site='musinsa', url=_url(sku),
                        dynamic_benefits_json=json.dumps(dyn, ensure_ascii=False)))
    s.commit()


def _run(sku):
    s = SessionLocal()
    try:
        r = compute_breakdown(s, sku=sku, source_id=MUSINSA, sale_price=100000.0)
        return r
    finally:
        s.rollback()
        s.close()


def _step_names(r):
    return [st['name'] for st in (r.get('steps') or [])]


def _assert_mutually_exclusive(r):
    """머니·현대카드가 같은 영수증에 동시에 차감되면 매입가 과소 — 절대 금지."""
    names = _step_names(r)
    money_on = MONEY_NAME in names
    hyundai_on = any('현대카드' in n for n in names)
    assert not (money_on and hyundai_on), (
        f'머니와 현대카드가 동시 차감됨(매입가 과소 위험): steps={names}')


def test_money_small_hyundai_wins(sess):
    """머니 1,000 < 현대 2.73%(표면 100,000 기준 2,730) → 현대카드 경로 승리.

    현대카드 경로: 100,000 − int(100,000×0.0273)=2,730 → 97,270 → 백원버림 97,200
    머니 경로:     100,000 − 1,000 = 99,000 (진다)
    """
    sku = PREFIX + 'small'
    _seed(sess, sku=sku, money=1000)
    r = _run(sku)
    names = _step_names(r)
    assert any('현대카드' in n for n in names)
    assert MONEY_NAME not in names
    _assert_mutually_exclusive(r)
    assert r['final_price'] == 97200
    assert (r.get('path') or {}).get('pay_method') == HYUNDAI_FLOOR_KEY


def test_money_large_money_wins(sess):
    """머니 4,000 > 2,730 → 머니 경로 승리.

    머니 경로:     100,000 − 4,000 = 96,000
    현대카드 경로: 100,000 − 2,730 = 97,270 (진다)
    """
    sku = PREFIX + 'large'
    _seed(sess, sku=sku, money=4000)
    r = _run(sku)
    names = _step_names(r)
    assert MONEY_NAME in names
    assert not any('현대카드' in n for n in names)
    _assert_mutually_exclusive(r)
    assert r['final_price'] == 96000
    assert (r.get('path') or {}).get('pay_method') == 'mus_money'


def test_no_money_hyundai_floor_still_deducts(sess):
    """money_reward_amount 0 → 종전과 동일: legacy 경로, 현대카드 2.73% 단독 차감.

    100,000 − 2,730 = 97,270 → 백원버림 97,200. 태그가 하나도 안 붙으므로
    path=None(legacy) 이어야 한다 — 머니 없는 기존 상품의 계산 경로가 바뀌면 안 된다.
    """
    sku = PREFIX + 'zero'
    _seed(sess, sku=sku, money=0)
    r = _run(sku)
    names = _step_names(r)
    assert any('현대카드' in n for n in names)
    assert MONEY_NAME not in names
    _assert_mutually_exclusive(r)
    assert r['final_price'] == 97200
    assert r.get('path') is None


def test_money_absent_key_hyundai_floor_still_deducts(sess):
    """money_reward_amount 키 자체가 없어도(None) 동일 — legacy + 현대카드."""
    sku = PREFIX + 'none'
    _seed(sess, sku=sku, money=None)
    r = _run(sku)
    names = _step_names(r)
    assert any('현대카드' in n for n in names)
    assert MONEY_NAME not in names
    _assert_mutually_exclusive(r)
    assert r['final_price'] == 97200
    assert r.get('path') is None


def test_money_equal_boundary(sess):
    """동액(머니 2,730 = 현대 2,730) → 어느 경로든 final 동일. 승자는 안 고정한다.

    100,000 − 2,730 = 97,270 → 백원버림 97,200 (양 경로 동일).
    """
    sku = PREFIX + 'tie'
    _seed(sess, sku=sku, money=2730)
    r = _run(sku)
    _assert_mutually_exclusive(r)
    assert r['final_price'] == 97200
