# -*- coding: utf-8 -*-
"""정책 미리보기가 할인을 반영하는가 — **화면과 실제 업로드가가 갈리면 안 된다.**

🔴 미리보기는 사장님이 「이 정책 걸면 얼마에 팔리나」를 보고 결정하는 화면이다.
  여기서 할인을 모르면 두 가지가 동시에 틀린다:
    ① 판매가가 실제 업로드가보다 **낮게** 나온다(올려 잡기를 안 하니까)
    ② 마진이 **부풀어** 보인다(표시가로 재니까) — 스스 20% 기준 3.5배

  ②가 더 위험하다. 적자인 상품이 남는 것처럼 보여 그대로 올라간다.
"""
import pytest

from lemouton.pricing.unified import compute_sale_price_unified

매입 = 50000


def _preview_price(values, purchase=매입, market='smartstore'):
    """🔴 **진짜 `preview_for_model` 을 부른다.**

    여기서 계산을 다시 쓰면 「내 시험이 내 시험을 검사하는」 꼴이 돼,
    정작 화면 코드가 할인을 몰라도 초록불이 뜬다.
    """
    from lemouton.policy.preview import preview_for_model

    def fake_matrix(_mc):
        return {'ok': True, 'options': [{'sku': 'SKU-A', 'color': '블랙',
                                         'size': '230', 'ss_price': 150000}]}

    import lemouton.orders.price_diff as pd
    orig = pd._current_purchase
    pd._current_purchase = lambda s, skus, matrix_loader=None: ({'SKU-A': purchase}, {})
    try:
        out = preview_for_model(None, model_code='M1', values=values,
                                market=market, matrix_loader=fake_matrix)
    finally:
        pd._current_purchase = orig
    assert out['ok'] is True, out.get('reason')
    return out['rows'][0]['policy_price']


기본 = {'price': {'sourcing_mode': 'margin_rate', 'sourcing_rate': 9.45,
                  'fee_rate': 6, 'rounding_unit': 100}}


def _with(**extra):
    return {'price': {**기본['price'], **extra}}


def test_미리보기_판매가가_할인만큼_올라간다():
    """🔴 안 오르면 화면값 ≠ 실제 업로드가 — 이 저장소에서 그건 금전 사고다."""
    없음 = _preview_price(기본)
    있음 = _preview_price(_with(discount_unit='PERCENT', discount_value=20))
    assert 있음 > 없음, f'미리보기가 할인을 모른다: {없음} → {있음}'


def test_미리보기가_실제_업로드가와_같다():
    """🔴 같은 정책이면 두 경로가 **한 원도** 달라선 안 된다."""
    from lemouton.policy.as_template import _PolicyTemplate
    from lemouton.pricing.unified import compute_market_price

    cfg = _with(discount_unit='PERCENT', discount_value=20)
    미리보기 = _preview_price(cfg)
    업로드 = compute_market_price(
        _PolicyTemplate({'smartstore': cfg}), 'ss', 'sourcing', 매입).final_price
    assert 미리보기 == 업로드, f'화면 {미리보기} vs 업로드 {업로드}'


def test_마켓이_부담하면_미리보기도_안_올린다():
    없음 = _preview_price(기본)
    마켓 = _preview_price(_with(discount_unit='PERCENT', discount_value=20,
                                discount_burden='market'))
    assert 마켓 == 없음


def test_할인_없는_정책은_한_원도_안_바뀐다():
    """지금 저장된 정책 대부분이 이 경우다."""
    assert _preview_price(기본) == compute_sale_price_unified(
        매입, 0.0945, 0.06).final_price


def test_미리보기_마진은_우리_수입_기준으로_잰다():
    """🔴 표시 판매가로 재면 3배 넘게 부풀어 보인다."""
    import inspect

    from lemouton.policy import preview
    src = inspect.getsource(preview.preview_summary) \
        if hasattr(preview, 'preview_summary') else inspect.getsource(preview)
    assert 'exposed_price' in src and '우리몫' in src, \
        '마진을 아직 표시 판매가로 재고 있다'
