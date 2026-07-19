# -*- coding: utf-8 -*-
"""르무통 공홈(Cafe24) 표면노출가 — **현재 코드 동작 스냅샷**.

정본: ``docs/소싱처별-정답지-읽는법.md`` §르무통 공홈 — **확인 상태 ❌ 미확인**.

  표면가로 잡는 값 (우선순위, `crawlers/lemouton.py:_parse_prices`):
      1. ``strong.price-number``
      2. 0 이면 ``span.txt_price.ProductPrice, span.ProductPrice``(정가) 를 sale 로 승격
      3. ``meta[property="product:sale_price:amount"]``
      4. JS ``var product_price = '...'``
  선반영된 것 : **기본할인(%)만**
  캡처 조건   : 페이지 토글 조작 코드 없음

🔴 **이 값이 옳은지는 미확정 — 코드 현재 동작을 고정한 것이다.**
셀렉터가 **화면의 어느 라벨**에 해당하는지 적힌 문서가 존재하지 않는다. 코드 주석이
"할인가" 라 부르는 건 **셀렉터에 대한 코드의 자체 명명**이지 페이지 캡션이 아니다.
사장님이 라벨을 확정하면 기대값을 바꾼다. 그 전까지 이 테스트의 역할은
**"표면가 정의가 조용히 바뀌는 것"을 잡는 것**이다.

⚠️ 본 테스트는 **정적 파서**(`lemouton.py`) 경로만 덮는다. Playwright 경로
(`lemouton_playwright.py:191-213`)는 **폴백 체인이 다르다**(meta 우선, `var
product_price` 폴백 없음 — 정답지 D15). 라이브는 정적 경로다.

픽스처 출처: ``tests/sourcing/fixtures/lemouton_sample.html`` — 기존 픽스처 재사용
(라이브 캡처 실 HTML). 폴백 체인 케이스는 셀렉터만 남긴 축약 HTML 을 새로
**재구성**했고 실제 응답과 다를 수 있다.
"""
from bs4 import BeautifulSoup

from lemouton.sourcing.crawlers.lemouton import (
    LemoutonCrawler,
    _parse_option_stock_data,
    _parse_prices,
)

URL = "https://lemouton.co.kr/product/detail.html?product_no=219"


def _osd_script(entries: dict) -> str:
    """Cafe24 ``var option_stock_data = '...'`` 2단 인코딩 재현.

    파서(`_parse_option_stock_data`)는 JS 단일따옴표 문자열 본문을 JSON 문자열
    본문으로 보고 2단 디코드한다 → 본문 = ``json.dumps(JSON텍스트)`` 의 알맹이.
    """
    import json as _json
    json_text = _json.dumps(entries, ensure_ascii=False)
    body = _json.dumps(json_text, ensure_ascii=False)[1:-1]
    return "<script>var option_stock_data = '" + body + "';</script>"


def _combo_html(option_price: int) -> str:
    """표면가 셀렉터 + option_stock_data 1조합 축약 HTML (재구성 — 실제와 다를 수 있음)."""
    return ('<html><body>'
            '<strong class="price-number">116,900</strong>'
            '<span class="ProductPrice">149,000</span>'
            + _osd_script({"X1": {
                "is_display": "T", "is_selling": "T", "stock_number": 5,
                "option_price": option_price,
                "option_value_orginal": ["블랙", "230mm"],
            }})
            + "</body></html>")

# 실 픽스처 실측값 (르무통 클래식2 메리노울 운동화)
SURFACE_PRICE = 116900     # strong.price-number   ★ 현재 표면가
ORIGIN_PRICE = 149000      # span.ProductPrice      ✗ 정가


# ─────────────────────────────────────────────────────────────
# ① 표면가로 무엇을 잡는가 — strong.price-number
# ─────────────────────────────────────────────────────────────
def test_surface_price_is_price_number_selector(html_of):
    html = html_of("lemouton")
    sale, origin, rate = _parse_prices(BeautifulSoup(html, "lxml"), html)
    assert sale == SURFACE_PRICE
    assert origin == ORIGIN_PRICE
    assert rate == 22


def test_all_options_carry_surface_price(html_of):
    res = LemoutonCrawler().parse_html(html_of("lemouton"), URL)
    assert res.options
    assert {o["price"] for o in res.options} == {SURFACE_PRICE}
    assert res.discount_info == "기본할인 22%"


# ─────────────────────────────────────────────────────────────
# ② 정가를 표면가로 잡으면 실패해야 한다
# ─────────────────────────────────────────────────────────────
def test_origin_price_is_not_used_as_surface(html_of):
    """정가(149,000)가 표면가로 새면 기본할인 22% 만큼 매입가가 부풀려진다."""
    res = LemoutonCrawler().parse_html(html_of("lemouton"), URL)
    assert ORIGIN_PRICE not in {o["price"] for o in res.options}


# ─────────────────────────────────────────────────────────────
# ③ 폴백 체인 — 엉뚱한 값으로 떨어지지 않는가
# ─────────────────────────────────────────────────────────────
def test_priority_1_price_number_wins_over_meta():
    """1순위 셀렉터가 있으면 meta/JS 폴백을 타지 않는다."""
    html = ('<html><head>'
            '<meta property="product:sale_price:amount" content="99000">'
            '</head><body>'
            '<strong class="price-number">116,900</strong>'
            '<span class="ProductPrice">149,000</span>'
            "<script>var product_price = '88000';</script>"
            "</body></html>")
    sale, origin, _ = _parse_prices(BeautifulSoup(html, "lxml"), html)
    assert sale == SURFACE_PRICE
    assert origin == ORIGIN_PRICE


def test_priority_2_origin_promoted_when_price_number_empty():
    """★ ``strong.price-number`` 는 JS 로 채워지므로 raw 단계에선 비어 있다.

    그때는 **정가를 그대로 sale 로 승격**한다(할인 없는 상품 취급). 할인율은 0 —
    가짜 할인율을 만들지 않는다.
    """
    html = '<html><body><span class="ProductPrice">149,000</span></body></html>'
    sale, origin, rate = _parse_prices(BeautifulSoup(html, "lxml"), html)
    assert sale == ORIGIN_PRICE
    assert origin == ORIGIN_PRICE
    assert rate == 0


def test_priority_3_meta_sale_price_when_no_selectors():
    html = ('<html><head>'
            '<meta property="product:sale_price:amount" content="116900">'
            '<meta property="product:price:amount" content="149000">'
            "</head><body></body></html>")
    sale, origin, rate = _parse_prices(BeautifulSoup(html, "lxml"), html)
    assert sale == SURFACE_PRICE
    assert origin == ORIGIN_PRICE
    assert rate == 22


def test_priority_4_js_var_product_price_last():
    """정적 경로에만 있는 마지막 폴백 (Playwright 경로엔 없음 — 정답지 D15)."""
    html = "<html><body><script>var product_price = '116900';</script></body></html>"
    sale, origin, _ = _parse_prices(BeautifulSoup(html, "lxml"), html)
    assert sale == SURFACE_PRICE
    assert origin == SURFACE_PRICE     # origin 부재 → sale 로 채움 (V7 규약)


def test_no_price_yields_zero_not_guess():
    """아무 것도 못 읽으면 0 — 추정가를 지어내지 않는다."""
    html = "<html><body>no price here</body></html>"
    sale, origin, rate = _parse_prices(BeautifulSoup(html, "lxml"), html)
    assert (sale, origin, rate) == (0, 0, 0)


# ─────────────────────────────────────────────────────────────
# ⚠️ 미확정 (D13) — option_price 가 표면가를 덮어쓴다
# ─────────────────────────────────────────────────────────────
def test_option_price_in_live_fixture_is_full_price(html_of):
    """라이브 픽스처에서 ``option_stock_data.option_price`` = 표면가와 **동일**.

    정답지 D13 은 이 "조합가" 가 Cafe24 의 **추가금인지 완가인지 근거가 없다**고
    적었다. 이 픽스처(실 캡처)에서는 ``option_price == 116900 == 표면가`` 이고
    별도로 ``origin_option_added_price: "0.00"`` (추가금 필드)이 따로 있다.
    → **추가금이 0 인 상품이라 두 해석이 구분되지 않는다.** 여전히 ❓미확정이며,
    여기선 값이 조용히 바뀌는 것만 잡는다.
    """
    rows = _parse_option_stock_data(html_of("lemouton"))
    assert rows
    assert {r["price"] for r in rows} == {SURFACE_PRICE}


def test_option_price_overrides_surface_price_SNAPSHOT():
    """🔴 **이 동작이 옳은지는 미확정 — 코드 현재 동작을 고정한 것이다.**

    ``lemouton.py:377`` 은 ``price = r["price"] or sale_price`` 다. 즉
    ``option_price`` 가 0 이 아니면 **표면가를 덮어쓴다**. 이 값이 Cafe24 의
    *추가금*이라면 옵션 표면가가 정상가의 몇 % 수준으로 붕괴한다(정답지 D13).

    아래는 그 덮어쓰기가 실제로 일어난다는 사실만 고정한다.
    """
    res = LemoutonCrawler().parse_html(_combo_html(9900), URL)   # 표면가와 다른 조합가
    assert len(res.options) == 1
    # 현재 동작: 조합가 9,900 이 표면가 116,900 을 덮어쓴다
    assert res.options[0]["price"] == 9900
    assert res.options[0]["price"] != SURFACE_PRICE


def test_option_price_zero_falls_back_to_surface_price():
    """``option_price`` 가 0 이면 표면가 유지 — 폴백이 0원으로 새면 안 된다."""
    res = LemoutonCrawler().parse_html(_combo_html(0), URL)
    assert res.options[0]["price"] == SURFACE_PRICE
