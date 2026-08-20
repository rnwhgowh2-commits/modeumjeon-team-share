# -*- coding: utf-8 -*-
"""스마트스토어 르무통 표면노출가 = ``benefitsView.discountedSalePrice``.
**``simpleProductForDetailPage.A.salePrice`` 는 정가이지 표면가가 아니다.**

정본: ``docs/소싱처별-정답지-읽는법.md`` §스마트스토어 르무통.

  표면가로 잡는 값 : ``window.__PRELOADED_STATE__`` →
                     ``simpleProductForDetailPage.A.benefitsView`` 의 4단 우선순위
                       1. discountedSalePrice        ← 표시 할인가 (실측 1:1 일치)
                       2. mobileDiscountedSalePrice
                       3. dispDiscountedSalePrice
                       4. 전부 0 → A.salePrice(**정가**) 폴백
                     (`crawlers/ss_lemouton.py:261-267`, `:334-336`)
  선반영된 것      : **즉시할인** (비회원 기준)
  표면가 밖(별도)  : 리뷰적립 · 네이버페이 · 카드
  캡처 조건        : 페이지 토글 조작 없음 (비로그인 brand.naver.com HTML)

⚠️ **미확정 1** — 이 숫자의 **화면 라벨명**을 특정할 수 없다. 네이버 PDP 는 캡션을
붙이지 않는다. "화면에 크게 뜨는 할인가" 로만 이해된다.

⚠️ **미확정 2** — 표면가에 선반영된 혜택 **범위 전체**는 미확정이다. 코드가 명시한다:
"혜택 정책 미정 (사용자 추가 예정)" (`ss_lemouton.py:387-388`).

⚠️ **stale 문서 주의** — 모듈 docstring `:18` 의 "salePrice (할인 적용 후 노출가)" 는
**낡았다**. 2026 정정 주석(`:254-261`)이 우선이며 salePrice 는 **정가**다.
아래 `test_saleprice_is_origin_not_surface` 가 그걸 잠근다.

픽스처 출처: ``tests/sourcing/fixtures/ss_lemouton_sample.html`` — 기존 픽스처
재사용(라이브 캡처 실 HTML). 폴백 케이스는 ``__PRELOADED_STATE__`` 를 코드가 읽는
필드만 축약 **재구성**했고 실제 응답과 다를 수 있다.
"""
import json

import pytest

from lemouton.sourcing.crawlers.ss_lemouton import SsLemoutonCrawler

URL = "https://brand.naver.com/lemouton/products/9496367527"

# 실 픽스처 실측값 (르무통 클래식2 메리노울 운동화)
SURFACE_PRICE = 118000    # discountedSalePrice = 표시 할인가   ★ 이게 표면가
ORIGIN_PRICE = 149000     # A.salePrice = 정가                  ✗ 표면가 아님


def _state_html(**benefits):
    """``__PRELOADED_STATE__`` 축약 재현 — 코드가 읽는 필드만."""
    bv = {"discountedSalePrice": 0, "mobileDiscountedSalePrice": 0,
          "dispDiscountedSalePrice": 0}
    bv.update(benefits.pop("benefitsView", {}))
    state = {"simpleProductForDetailPage": {"A": {
        "name": "르무통 클래식2 발 편한 메리노울 운동화",
        "salePrice": benefits.pop("salePrice", ORIGIN_PRICE),
        "benefitsView": bv,
        "stockQuantity": 100,
        "productOptions": [],
    }}}
    return ("<html><body><script>window.__PRELOADED_STATE__ = "
            + json.dumps(state, ensure_ascii=False)
            + ";</script></body></html>")


# ─────────────────────────────────────────────────────────────
# ① 표면가로 무엇을 잡는가 — discountedSalePrice
# ─────────────────────────────────────────────────────────────
def test_surface_price_is_discounted_sale_price(html_of):
    res = SsLemoutonCrawler().parse_html(html_of("ss_lemouton"), URL)
    assert res.options
    assert {o["price"] for o in res.options} == {SURFACE_PRICE}
    assert {o["sale_price"] for o in res.options} == {SURFACE_PRICE}


# ─────────────────────────────────────────────────────────────
# ② 정가·선반영 값을 표면가로 잡으면 실패해야 한다
# ─────────────────────────────────────────────────────────────
def test_saleprice_is_origin_not_surface(html_of):
    """``A.salePrice`` 는 **정가**다. 표면가로 새면 즉시할인만큼 매입가가 부풀려진다.

    (모듈 docstring `:18` 의 "salePrice = 할인 적용 후 노출가" 는 stale — 이 테스트가
    코드 실동작 쪽을 잠근다.)
    """
    res = SsLemoutonCrawler().parse_html(html_of("ss_lemouton"), URL)
    prices = {o["price"] for o in res.options}
    assert ORIGIN_PRICE not in prices
    assert res.options[0]["original_price"] == ORIGIN_PRICE   # 정가는 별도 키로만


def test_seller_immediate_discount_is_not_deducted_again(html_of):
    """★ 이중차감 차단 — 즉시할인은 **이미 discountedSalePrice 에 반영**돼 있다.

    ``sellerImmediateDiscountAmount`` 는 읽되 계산엔 안 쓴다(`:320-327`).
    표면가가 '즉시할인을 한 번 더 뺀 값' 이면 안 된다.
    """
    res = SsLemoutonCrawler().parse_html(html_of("ss_lemouton"), URL)
    assert "즉시할인" in (res.discount_info or "")      # 사람이 읽을 명목으로만 존재
    o = res.options[0]
    assert o["price"] == SURFACE_PRICE
    # 정가 − 즉시할인 = 표면가 (즉시할인이 표면가에 이미 먹혀 있다는 항등식)
    assert ORIGIN_PRICE - 31000 == SURFACE_PRICE
    # 즉시할인이 또 빠진 값이 아니다
    assert o["price"] != SURFACE_PRICE - 31000
    # 즉시할인 금액이 옵션 dict 에 차감용 키로 실리지 않는다
    assert "seller_immediate_discount" not in o


def test_review_point_is_outside_surface_price(html_of):
    """리뷰적립은 표면가 밖 — 별도 키로만."""
    o = SsLemoutonCrawler().parse_html(html_of("ss_lemouton"), URL).options[0]
    assert o["review_point_max"] == 5000
    assert o["price"] == SURFACE_PRICE       # 적립 차감 전


# ─────────────────────────────────────────────────────────────
# ③ 폴백 4단 우선순위 — 엉뚱한 값으로 떨어지지 않는가
# ─────────────────────────────────────────────────────────────
def test_priority_1_discounted_sale_price_wins():
    res = SsLemoutonCrawler().parse_html(_state_html(benefitsView={
        "discountedSalePrice": 118000,
        "mobileDiscountedSalePrice": 117000,
        "dispDiscountedSalePrice": 116000,
    }), URL)
    assert res.options[0]["price"] == 118000


def test_priority_2_mobile_when_first_zero():
    res = SsLemoutonCrawler().parse_html(_state_html(benefitsView={
        "mobileDiscountedSalePrice": 117000,
        "dispDiscountedSalePrice": 116000,
    }), URL)
    assert res.options[0]["price"] == 117000


def test_priority_3_disp_when_first_two_zero():
    res = SsLemoutonCrawler().parse_html(_state_html(benefitsView={
        "dispDiscountedSalePrice": 116000,
    }), URL)
    assert res.options[0]["price"] == 116000


def test_priority_4_falls_back_to_origin_price():
    """benefitsView 가 전부 0 이면 정가 폴백 — 정상가만 노출되는 상품."""
    res = SsLemoutonCrawler().parse_html(_state_html(), URL)
    assert res.options[0]["price"] == ORIGIN_PRICE


def test_all_prices_zero_fails_loudly():
    """가격 0 저장 절대 금지 — 전부 0 이면 실패."""
    with pytest.raises(RuntimeError) as ei:
        SsLemoutonCrawler().parse_html(_state_html(salePrice=0), URL)
    assert "가격 추출 실패" in str(ei.value)
