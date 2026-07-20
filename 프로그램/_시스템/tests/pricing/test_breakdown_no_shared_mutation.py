# -*- coding: utf-8 -*-
"""계산이 공유 혜택 행을 건드리면 안 된다.

계산 중 "이 혜택 끔"을 ORM 행에 직접 쓰면, 그 행은 여러 SKU 가 공유하는 캐시에
있어서 먼저 계산한 상품이 나중 상품의 혜택을 지운다. 한 건만 볼 땐 안 보이고
여러 건일 때만 틀린다(순서 의존). 세션 flush 시 DB 에까지 써질 수 있다.

이 저장소는 같은 사고를 두 번 겪었다 — final_price.py:228 주석 참고.
"""
import json

import pytest

from shared.db import SessionLocal
from lemouton.sourcing.models import OptionBenefitOverride
from lemouton.sourcing.models_pricing import OptionSourceUrl
from lemouton.sources.models import SourceProduct
from webapp.routes.api_benefits import compute_breakdown

PFX = 'SHAREDTEST-'
MUSINSA = 3          # 계산 번호(SourceRegistry). 화면 번호 5 와 다르다.


def _url(sku):
    return f'https://example.test/shared/{sku}'


@pytest.fixture
def two_skus():
    s = SessionLocal()
    try:
        for sku in (PFX + 'a', PFX + 'b'):
            s.add(OptionSourceUrl(canonical_sku=sku, source_id=MUSINSA,
                                  product_url=_url(sku)))
            s.add(SourceProduct(site='musinsa', url=_url(sku),
                                dynamic_benefits_json=json.dumps(
                                    {'surface_price': 100000,
                                     'money_reward_amount': 4000,
                                     'money_active': True})))
            # 이름에 '무신사머니 fallback' 이 들어간 행 — 계산이 끄려고 드는 대상
            s.add(OptionBenefitOverride(
                canonical_sku=sku, source_id=MUSINSA,
                benefit_name='현대카드 (무신사머니 fallback)',
                benefit_type='rate', value=0.0273, enabled=True, sort_order=0))
        s.commit()
    finally:
        s.close()
    yield [PFX + 'a', PFX + 'b']
    s = SessionLocal()
    try:
        s.query(OptionBenefitOverride).filter(
            OptionBenefitOverride.canonical_sku.like(PFX + '%')).delete(
            synchronize_session=False)
        s.query(OptionSourceUrl).filter(
            OptionSourceUrl.canonical_sku.like(PFX + '%')).delete(
            synchronize_session=False)
        s.query(SourceProduct).filter(
            SourceProduct.url.like('https://example.test/shared/%')).delete(
            synchronize_session=False)
        s.commit()
    finally:
        s.close()


def test_orm_rows_keep_enabled_after_compute(two_skus):
    """★ 계산은 DB 행의 enabled 를 건드리지 않는다."""
    sku = two_skus[0]
    s = SessionLocal()
    try:
        compute_breakdown(s, sku=sku, source_id=MUSINSA, sale_price=100000.0)
        rows = s.query(OptionBenefitOverride).filter_by(canonical_sku=sku).all()
        assert all(r.enabled for r in rows), '계산이 혜택 행을 껐다'
    finally:
        s.rollback()
        s.close()


def test_repeated_compute_is_stable(two_skus):
    """★ 여러 번·여러 상품을 계산해도 같은 값. 앞 계산이 뒤를 오염시키면 안 된다."""
    a, b = two_skus
    s = SessionLocal()
    try:
        first = compute_breakdown(s, sku=a, source_id=MUSINSA, sale_price=100000.0)
        compute_breakdown(s, sku=b, source_id=MUSINSA, sale_price=100000.0)
        again = compute_breakdown(s, sku=a, source_id=MUSINSA, sale_price=100000.0)
        assert again['final_price'] == first['final_price']
        assert [x['name'] for x in again['steps']] == [x['name'] for x in first['steps']]
    finally:
        s.rollback()
        s.close()
