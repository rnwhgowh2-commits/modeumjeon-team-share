# -*- coding: utf-8 -*-
"""「우리 수입 기준가」와 「고객이 내는 값」은 **다른 숫자**다.

🔴 왜 이 시험이 생겼나 — 엔진 breakdown 에 `exposed_price`(고객이 보는 값) 라는
  이름을 붙여 놓고, 실제로는 **판매자 부담 몫만** 뺀 값을 담고 있었다.

  · 판매자 100% 부담이면 둘이 우연히 같다 → 못 알아챈다
  · **마켓이 같이 부담하면 갈린다** — 고객은 전체 할인만큼 싸게 사고,
    마켓이 낸 몫은 우리에게 들어온다

  마진은 「판매가 − 판매자부담」으로 재야 맞고(그 값이 곧 우리 수입 기준),
  화면에 「고객이 내는 값」으로 보여 줄 땐 **전체 할인**을 빼야 맞다.
  이름이 뜻을 배신하면 다음 사람이 반드시 틀린 칸을 쓴다.
"""
import pytest

from lemouton.policy.discount import discount_of, exposed_price
from lemouton.pricing.unified import compute_sale_price_unified

매입 = 50000


def _r(**kw):
    return compute_sale_price_unified(매입, 0.0945, 0.06, **kw)


def test_우리_수입_기준가라는_이름으로_준다():
    """🔴 `exposed_price` 라는 이름은 거짓말이었다."""
    b = _r(seller_discount_unit='PERCENT', seller_discount_value=20).breakdown
    assert 'net_basis_price' in b, '우리 수입 기준가를 안 알려 준다'
    assert b['net_basis_price'] < b['final_price'] if 'final_price' in b else True


def test_기준가는_판매가에서_판매자_몫만_뺀_값():
    r = _r(seller_discount_unit='PERCENT', seller_discount_value=20)
    assert r.breakdown['net_basis_price'] == round(r.final_price * 0.8)


def test_마켓이_같이_부담하면_고객가와_갈린다():
    """전체 20% 중 우리가 10%만 낼 때 — 두 숫자가 달라야 한다."""
    r = _r(seller_discount_unit='PERCENT', seller_discount_value=10)   # 우리 몫만
    우리기준 = r.breakdown['net_basis_price']
    고객가 = exposed_price(r.final_price,
                           discount_of({'price': {'discount_unit': 'PERCENT',
                                                  'discount_value': 20}}))
    assert 고객가 < 우리기준, f'고객이 더 싸게 사야 한다: 고객 {고객가} vs 기준 {우리기준}'


def test_거짓말하던_이름은_사라졌다():
    """🔴 남겨 두면 다음 사람이 그 칸을 「고객가」로 알고 쓴다."""
    b = _r(seller_discount_unit='PERCENT', seller_discount_value=20).breakdown
    assert 'exposed_price' not in b


def test_할인이_없으면_기준가는_판매가_그대로():
    r = _r()
    assert r.breakdown['net_basis_price'] == r.final_price


def test_모든_모드가_기준가를_알려_준다():
    """🔴 한 모드만 넣으면 다른 경로가 조용히 표시가로 잰다."""
    for kw in ({}, {'mode': 'amount', 'margin_amount': 5000},
               {'mode': 'fixed', 'fixed_price': 70000}):
        b = compute_sale_price_unified(매입, 0.0945, 0.06, **kw).breakdown
        assert b.get('net_basis_price', 0) > 0, f'{kw} 모드에 기준가가 없다'
