# -*- coding: utf-8 -*-
"""혜택 이름의 띄어쓰기 차이로 게이트가 조용히 통과하면 안 된다.

가이드는 「상품 쿠폰」·「등급 할인」(띄어쓰기 있음), 계산이 주입하는 항목은
「상품쿠폰」·「등급할인」(없음)이다. 끄는 비교는 원문, 경고 비교는 공백제거라
'못 끄는데 경고도 안 뜨는' 조합이 나왔다 — 상품 페이지가 "등급 할인 불가"라고
말해도 계속 차감돼 매입가가 실제보다 싸게 잡혔다(= 손해 매입 방향).
"""
from webapp.routes.api_benefits import _norm_benefit_name


def test_space_is_ignored():
    assert _norm_benefit_name('상품 쿠폰') == _norm_benefit_name('상품쿠폰')
    assert _norm_benefit_name('등급 할인') == _norm_benefit_name('등급할인')


def test_surrounding_space_ignored():
    assert _norm_benefit_name('  등급 적립 ') == _norm_benefit_name('등급적립')


def test_different_names_stay_different():
    """등급'할인' 과 등급'적립' 은 다른 혜택 — 뭉뚱그리면 안 된다."""
    assert _norm_benefit_name('등급할인') != _norm_benefit_name('등급적립')
    assert _norm_benefit_name('구매적립') != _norm_benefit_name('등급적립')


def test_none_and_empty():
    assert _norm_benefit_name(None) == ''
    assert _norm_benefit_name('') == ''
