# -*- coding: utf-8 -*-
"""가공정책의 할인이 **가격 엔진까지 실제로 닿는지**.

🔴 왜 이 시험이 생겼나 — 할인 값은 가공정책(`rules['price']['discount_value']`)에
  저장된다. 그런데 가격 엔진이 읽는 `PriceTemplate` 에는 **할인 칸이 아예 없다**
  (실측: `PriceTemplate.__table__` 에 'discount' 가 들어간 컬럼 0개).

  둘을 잇는 것이 `_PolicyTemplate` 껍데기인데, 이 껍데기가 할인 이름을 모르면
  엔진은 늘 「할인 0」을 받는다. **에러 없이 판매가만 안 올라간다** —
  이 저장소가 반복해서 당한 「조용한 실패」 그대로다.

  스스 20% 기준으로 상품당 5,557원씩 계속 손해가 난다.
"""
import pytest

from lemouton.policy.as_template import _PolicyTemplate
from lemouton.pricing.unified import compute_market_price, resolve_market_policy


def _tpl(price: dict):
    """정책 하나(스마트스토어 판매가 항목만) → 엔진이 읽는 껍데기."""
    return _PolicyTemplate({'smartstore': {'price': price}})


기본 = {'sourcing_mode': 'margin_rate', 'sourcing_rate': 9.45, 'fee_rate': 6}


def test_껍데기가_할인_방식과_값을_알려_준다():
    """🔴 이게 없으면 엔진은 영영 「할인 없음」으로 계산한다."""
    tpl = _tpl({**기본, 'discount_unit': 'PERCENT', 'discount_value': 20})
    assert getattr(tpl, 'ss_discount_unit') == 'PERCENT'
    assert getattr(tpl, 'ss_discount_value') == 20


def test_껍데기가_부담_주체를_알려_준다():
    tpl = _tpl({**기본, 'discount_unit': 'PERCENT', 'discount_value': 20,
                'discount_burden': 'split', 'discount_burden_pct': 50})
    assert getattr(tpl, 'ss_discount_burden') == 'split'
    assert getattr(tpl, 'ss_discount_burden_pct') == 50


def test_정책의_할인이_판매가를_실제로_올린다():
    """🔴 껍데기만 고치고 끝나지 않게 — **끝에서 끝까지** 잰다."""
    없음 = compute_market_price(_tpl(기본), 'ss', 'sourcing', 50000).final_price
    있음 = compute_market_price(
        _tpl({**기본, 'discount_unit': 'PERCENT', 'discount_value': 20}),
        'ss', 'sourcing', 50000).final_price
    assert 있음 > 없음, f'정책에 할인을 걸었는데 판매가가 그대로다: {없음} → {있음}'
    # 고객이 내는 값은 원래 판매가와 같아야 한다(할인 뒤 값)
    assert abs(round(있음 * 0.8) - 없음) <= 100


def test_할인을_안_건_정책은_한_원도_안_바뀐다():
    """지금 저장된 정책 대부분이 이 경우다 — 영향이 없어야 한다."""
    pol = resolve_market_policy(_tpl(기본), 'smartstore', 'sourcing')
    assert not pol['seller_discount_value']


def test_마켓_부담이면_올리지_않는다():
    없음 = compute_market_price(_tpl(기본), 'ss', 'sourcing', 50000).final_price
    마켓 = compute_market_price(
        _tpl({**기본, 'discount_unit': 'PERCENT', 'discount_value': 20,
              'discount_burden': 'market'}), 'ss', 'sourcing', 50000).final_price
    assert 마켓 == 없음


def test_할인은_쓰던_템플릿으로_되받지_않는다():
    """🔴 PriceTemplate 에는 할인 칸이 없다 — 되받으려다 AttributeError 로 터지면 안 된다."""
    class 옛템플릿:
        rounding_unit = 100
        ss_fee_rate = 0.06

    tpl = _PolicyTemplate({'smartstore': {'price': 기본}}, fallback=옛템플릿())
    assert getattr(tpl, 'ss_discount_value', '못읽음') in (None, 0)


def test_여섯_마켓_모두_같은_다리를_탄다():
    """🔴 한 마켓만 이으면 나머지 5곳이 조용히 옛 계산으로 남는다."""
    from lemouton.policy.as_template import PREFIX_TO_MARKET
    for prefix, market in PREFIX_TO_MARKET.items():
        tpl = _PolicyTemplate({market: {'price': {
            **기본, 'discount_unit': 'PERCENT', 'discount_value': 20}}})
        pol = resolve_market_policy(tpl, market, 'sourcing')
        assert pol['seller_discount_value'] == 20, f'{market} 만 다리가 끊겼다'
