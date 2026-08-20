# -*- coding: utf-8 -*-
"""SSF샵 표면노출가 = 「판매가」 ``em.price``.

정본: ``docs/소싱처별-정답지-읽는법.md`` §SSF샵 (확인 상태 ✅ — 표면가 한정).

  표면가로 잡는 값 : ``em.price`` 텍스트 숫자 (`crawlers/ssf.py:_parse_prices`)
  선반영된 것      : **시즌·쇼핑위크 할인만**
  표면가 밖(별도)  : 기프트포인트(멤버십 10% 즉시할인) · 멤버십포인트 적립
  캡처 조건        : 페이지 토글 조작 없음 (익명 raw HTML)

픽스처 출처: ``tests/sourcing/fixtures/ssf_sample.html`` — 기존 픽스처 재사용
(``_capture_fixtures.py`` 가 라이브에서 캡처한 실 HTML). 폴백·경계 케이스만
축약 HTML 을 새로 만들었고, 그건 실제 응답과 다를 수 있다.

이 테스트의 목적은 **표면가 정의가 조용히 바뀌는 것을 잡는 것**이다.
"""
import pytest
from bs4 import BeautifulSoup

from lemouton.sourcing.crawlers.ssf import SsfCrawler, _parse_prices

URL = "https://www.ssfshop.com/LEMOUTON/GRG426021974780/good"

# 실 픽스처 실측값 (르무통 메이트 메리노울 운동화)
SURFACE_PRICE = 126300      # 「판매가」 em.price   ★ 이게 표면가
ORIGIN_PRICE = 149000       # 정가 <del>          ✗ 표면가 아님


# ─────────────────────────────────────────────────────────────
# ① 표면가로 무엇을 잡는가 — em.price(판매가)
# ─────────────────────────────────────────────────────────────
def test_surface_price_is_em_price(html_of):
    """표면가 = 「판매가」 em.price. 라이브 픽스처에서 126,300 이 나와야 한다."""
    soup = BeautifulSoup(html_of("ssf"), "lxml")
    sale, origin, rate = _parse_prices(soup)
    assert sale == SURFACE_PRICE
    assert origin == ORIGIN_PRICE
    assert rate == 15


def test_all_options_carry_surface_price(html_of):
    res = SsfCrawler().parse_html(html_of("ssf"), URL)
    assert res.options
    for o in res.options:
        assert o["price"] == SURFACE_PRICE
        assert o["sale_price"] == SURFACE_PRICE


# ─────────────────────────────────────────────────────────────
# ② 선반영 아닌 값을 표면가로 잡으면 실패해야 한다
# ─────────────────────────────────────────────────────────────
def test_origin_price_is_not_used_as_surface(html_of):
    """정가(<del> 149,000)가 표면가로 새면 시즌할인만큼 매입가가 부풀려진다."""
    res = SsfCrawler().parse_html(html_of("ssf"), URL)
    assert ORIGIN_PRICE not in {o["price"] for o in res.options}


def test_membership_points_are_outside_surface_price(html_of):
    """멤버십포인트 적립은 표면가 밖 — 별도 키로만 실려야 한다.

    ``point_amount`` 가 표면가에서 이미 빠져 있으면(=표면가가 포인트 차감가라면)
    엔진이 한 번 더 빼서 이중차감이 된다. 여기선 '별도 키 + 표면가 불변' 을 고정한다.
    """
    res = SsfCrawler().parse_html(html_of("ssf"), URL)
    o = res.options[0]
    assert o["point_rate"] == 0.005
    assert o["point_amount"] == 631
    # 포인트가 표면가에 먹혀 있지 않다 = 표면가는 여전히 em.price 그대로
    assert o["price"] == SURFACE_PRICE
    assert o["price"] - o["point_amount"] != o["price"]   # 차감 전 값임을 명시


def test_card_discount_is_not_baked_into_surface_price(html_of):
    """현대카드 2.73% 는 표면가 밖(included_in_sale_price=False)."""
    res = SsfCrawler().parse_html(html_of("ssf"), URL)
    acd = res.options[0]["auto_card_discount"]
    assert acd["included_in_sale_price"] is False
    assert acd["rate"] == 2.73


# ─────────────────────────────────────────────────────────────
# ③ 폴백이 엉뚱한 값으로 떨어지지 않는가
# ─────────────────────────────────────────────────────────────
def test_missing_sale_price_falls_back_to_origin_only():
    """em.price 가 없으면 정가(<del>)로 승격 — V7 ``|| originPrice`` 규약.

    ⚠️ 이건 '정가를 표면가로 쓴다' 는 뜻이라 위험해 보이지만, 할인이 없는 상품은
    판매가=정가이므로 의도된 동작이다. 여기선 **폴백이 그 외 값(0·정가 아닌 값)으로
    새지 않는 것**을 고정한다.
    """
    html = '<html><body><del>149,000</del></body></html>'
    sale, origin, rate = _parse_prices(BeautifulSoup(html, "lxml"))
    assert sale == ORIGIN_PRICE
    assert origin == ORIGIN_PRICE
    assert rate == 0          # 할인율 0 — 가짜 할인율을 만들지 않는다


def test_no_price_at_all_fails_loudly():
    """가격을 전혀 못 읽으면 0원 저장이 아니라 실패 — 금전 직결."""
    html = '<html><body><h2 class="brand-name">르무통</h2></body></html>'
    with pytest.raises(RuntimeError) as ei:
        SsfCrawler().parse_html(html, URL)
    assert "sale_price" in str(ei.value)
