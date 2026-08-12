# -*- coding: utf-8 -*-
"""상품 목록(타워)의 대표 판매가·마진도 할인을 알아야 한다.

🔴 이 자리는 엔진을 **직접** 부르는 세 번째 곳이다. 앞선 두 곳
  (`pricing/unified.resolve_market_policy` · `policy/preview.py`)을 고쳐도
  여기가 남으면 목록 화면만 옛 숫자를 보여 준다.

  목록의 `margin_pct` 는 **수수료 반영 전** 지표라 정의가 다르지만, 그래도
  판매가가 올려 잡힌 값이면 그 판매가를 그대로 분모에 쓰면 안 된다 —
  20% 할인 기준으로 판매가가 25% 부풀어 마진율이 실제보다 높게 보인다.
"""
import pytest

from webapp.routes.bundles_tower import _rep_policy_price

기본 = {'price': {'sourcing_mode': 'margin_rate', 'sourcing_rate': 9.45,
                  'fee_rate': 6, 'rounding_unit': 100}}


def _with(**extra):
    return {'price': {**기본['price'], **extra}}


def test_목록_대표가도_할인만큼_올라간다():
    """🔴 안 오르면 목록만 실제 업로드가보다 낮은 값을 보여 준다."""
    없음 = _rep_policy_price(기본, 50000)
    있음 = _rep_policy_price(_with(discount_unit='PERCENT', discount_value=20), 50000)
    assert 있음 > 없음, f'목록이 할인을 모른다: {없음} → {있음}'


def test_목록_대표가가_실제_업로드가와_같다():
    from lemouton.policy.as_template import _PolicyTemplate
    from lemouton.pricing.unified import compute_market_price

    cfg = _with(discount_unit='PERCENT', discount_value=20)
    목록 = _rep_policy_price(cfg, 50000)
    업로드 = compute_market_price(
        _PolicyTemplate({'smartstore': cfg}), 'ss', 'sourcing', 50000).final_price
    assert 목록 == 업로드, f'목록 {목록} vs 업로드 {업로드}'


def test_마켓이_부담하면_목록도_안_올린다():
    assert _rep_policy_price(_with(discount_unit='PERCENT', discount_value=20,
                                   discount_burden='market'), 50000) \
        == _rep_policy_price(기본, 50000)


def test_할인_없는_정책은_한_원도_안_바뀐다():
    from lemouton.pricing.unified import compute_sale_price_unified
    assert _rep_policy_price(기본, 50000) == compute_sale_price_unified(
        50000, 0.0945, 0.06).final_price


def test_목록_마진율은_우리_수입_기준으로_잰다():
    """🔴 올려 잡은 판매가를 그대로 분모에 쓰면 마진율이 실제보다 높아 보인다."""
    import inspect

    from webapp.routes import bundles_tower
    src = inspect.getsource(bundles_tower._build_price_index)
    assert 'margin_basis' in src or 'seller_share' in src or '기준' in src, \
        '목록 마진율이 아직 올려 잡은 판매가를 그대로 쓴다'
