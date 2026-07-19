# -*- coding: utf-8 -*-
"""현대H몰 표면노출가 = ``itemPtc.bbprc`` (깜짝할인 선반영가). **``sellPrc``(정가) 아님.**

정본: ``docs/소싱처별-정답지-읽는법.md`` §현대H몰.

  표면가로 잡는 값 : ``__NEXT_DATA__ → props.pageProps.respData.itemPtc.bbprc``
                     없으면 ``sellPrc``(정가) 폴백 (`crawlers/hmall.py:197-199`)
  선반영된 것      : **깜짝할인만**
  표면가 밖(별도)  : 카드 즉시할인(``표면가 − 카드적용가``, 기본 비활성) · H.Point 적립
  캡처 조건        : 페이지 토글 조작 없음

★ H몰은 **롯데아이몰과 정반대**다 — 카드할인이 애초에 bbprc 에 들어간 적이 없다
(`api_benefits.py:815-816`). 같은 규칙을 적용하면 안 된다.

⚠️ **미확정 1** — `bbprc` 가 **화면에서 어떤 라벨로 뜨는지** 코드·문서 어디에도 없다
(`docs/sources/hmall/` 디렉터리 자체가 없음). 즉 "bbprc 가 표면가" 는 **코드 현재
동작을 고정한 것**이지 화면 대조로 확정된 게 아니다.

⚠️ **미확정 2 (D8)** — 옵션 루프는 ``row["sellPrc"]`` 를 상품 bbprc 보다 **우선**
사용하는데(`hmall.py:216-217`), 상품 레벨에서 ``sellPrc`` 는 **정가**로 정의돼 있다.
``stockList`` 행의 ``sellPrc`` 가 옵션가인지 정가인지 근거가 없다.
아래 `test_row_sellprc_overrides_bbprc_SNAPSHOT` 은 **현재 동작 스냅샷**이며
기대값의 정당성은 미확정이다.

픽스처 출처: ``__NEXT_DATA__`` 구조를 코드가 읽는 필드만 축약 **재구성**했다
(`test_hmall_lotteimall_crawl.py:_hmall_html` 과 같은 형태). 실제 응답과 다를 수 있다.
"""
import json

import pytest

from lemouton.sourcing.crawlers.hmall import HmallCrawler

URL = "https://www.hmall.com/p/pdp/x?slitmCd=100"

SELL_PRC = 149000     # 정가          ✗ 표면가 아님
BBPRC = 116900        # 깜짝할인가     ★ 이게 표면가


def _hmall_html(*, sell_prc=SELL_PRC, bbprc=BBPRC, stock_list=None):
    if stock_list is None:
        stock_list = [
            {"uitm1AttrNm": "240", "sellGbcd": "00", "stockCount": 5, "uitmCd": "A"},
            {"uitm1AttrNm": "250", "sellGbcd": "00", "stockCount": 3, "uitmCd": "B"},
        ]
    nd = {"props": {"pageProps": {"respData": {"itemPtc": {
        "slitmCd": "100", "slitmNm": "르무통 메이트 운동화 블랙", "brndNm": "르무통",
        "sellPrc": sell_prc, "bbprc": bbprc, "stockList": stock_list,
    }}}}}
    return ('<html><body><script id="__NEXT_DATA__">'
            + json.dumps(nd, ensure_ascii=False)
            + "</script></body></html>")


# ─────────────────────────────────────────────────────────────
# ① 표면가로 무엇을 잡는가 — bbprc
# ─────────────────────────────────────────────────────────────
def test_surface_price_is_bbprc():
    res = HmallCrawler().parse_html(_hmall_html(), URL)
    assert res.options
    for o in res.options:
        assert o["price"] == BBPRC
        assert o["sale_price"] == BBPRC


# ─────────────────────────────────────────────────────────────
# ② 정가(sellPrc)를 표면가로 잡으면 실패해야 한다
# ─────────────────────────────────────────────────────────────
def test_sellprc_is_not_used_as_surface_when_bbprc_exists():
    """``sellPrc``(정가 149,000)가 표면가로 새면 깜짝할인만큼 매입가가 부풀려진다."""
    res = HmallCrawler().parse_html(_hmall_html(), URL)
    assert SELL_PRC not in {o["price"] for o in res.options}


def test_single_sku_fallback_also_uses_bbprc():
    """stockList 부재(단일 SKU) 폴백 행도 정가가 아니라 bbprc 를 써야 한다."""
    res = HmallCrawler().parse_html(_hmall_html(stock_list=[]), URL)
    assert len(res.options) == 1
    assert res.options[0]["price"] == BBPRC


# ─────────────────────────────────────────────────────────────
# ③ 폴백이 엉뚱한 값으로 떨어지지 않는가
# ─────────────────────────────────────────────────────────────
def test_falls_back_to_sellprc_only_when_bbprc_absent():
    """bbprc 가 0/부재일 때만 정가 폴백 (할인 없는 상품 = 판매가가 곧 정가)."""
    res = HmallCrawler().parse_html(_hmall_html(bbprc=0), URL)
    assert {o["price"] for o in res.options} == {SELL_PRC}


def test_no_price_at_all_yields_no_options_not_zero_price():
    """가격이 전혀 없으면 0원 옵션을 만들지 않는다 (0원 = 최저가 오인 = 손실)."""
    res = HmallCrawler().parse_html(
        _hmall_html(sell_prc=0, bbprc=0, stock_list=[]), URL)
    assert res.options == []


def test_missing_itemptc_is_honest_failure_not_stale_price():
    """상품 데이터 자체가 없으면 옛값·추정가 금지 — 빈 옵션 + 실패 표기."""
    nd = {"props": {"pageProps": {"respData": {}}}}
    res = HmallCrawler().parse_html(
        '<script id="__NEXT_DATA__">' + json.dumps(nd) + "</script>", URL)
    assert res.options == []
    assert "실패" in (res.discount_info or "")


def test_no_next_data_raises():
    with pytest.raises(RuntimeError):
        HmallCrawler().parse_html("<html><body>nope</body></html>", URL)


# ─────────────────────────────────────────────────────────────
# ⚠️ 미확정 — 현재 동작 스냅샷 (옳은지 미확정, 조용한 변경 감지용)
# ─────────────────────────────────────────────────────────────
def test_row_sellprc_overrides_bbprc_SNAPSHOT():
    """🔴 **이 값이 옳은지는 미확정 — 코드 현재 동작을 고정한 것이다.**

    ``hmall.py:216-217`` 은 ``row["sellPrc"] > 0`` 이면 그 값을 옵션 price 로 쓰고
    상품 ``bbprc`` 를 무시한다. 그런데 상품 레벨에서 ``sellPrc`` 는 **정가**로
    정의돼 있다(`:197`). ``stockList`` 행의 ``sellPrc`` 가 옵션 실판매가인지
    정가인지 **코드·문서 어디에도 근거가 없다**(정답지 D8).

    행 sellPrc 가 정가라면 이 경로에서 **표면가가 정가로 둔갑**한다.
    사장님이 의미를 확정하면 기대값을 바꾼다. 그 전까지 이 테스트는
    "이 동작이 조용히 바뀌는 것" 만 잡는다.
    """
    res = HmallCrawler().parse_html(_hmall_html(stock_list=[
        {"uitm1AttrNm": "240", "sellPrc": 149000, "sellGbcd": "00",
         "stockCount": 5, "uitmCd": "A"},
    ]), URL)
    # 현재 동작: 행 sellPrc(149,000)가 상품 bbprc(116,900)를 덮어쓴다
    assert res.options[0]["price"] == 149000
    assert res.options[0]["price"] != BBPRC


def test_row_without_sellprc_uses_bbprc():
    """행에 sellPrc 가 없으면 상품 bbprc — 이쪽은 정의가 명확한 경로."""
    res = HmallCrawler().parse_html(_hmall_html(stock_list=[
        {"uitm1AttrNm": "240", "sellGbcd": "00", "stockCount": 5, "uitmCd": "A"},
    ]), URL)
    assert res.options[0]["price"] == BBPRC
