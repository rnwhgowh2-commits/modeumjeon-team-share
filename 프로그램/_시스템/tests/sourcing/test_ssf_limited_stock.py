# -*- coding: utf-8 -*-
"""SSF샵 한정재고 '품절임박(N)' 파싱 회귀 테스트.

버그(2026-06-15 수정): SSF 옵션 li 는 ``<span>품절임박</span>(<em>1</em>)`` 구조라
BeautifulSoup ``get_text(" ")`` 가 "품절임박 ( 1 )" 로 괄호 안에 공백을 넣는다.
기존 정규식 ``품절임박\\s*\\((\\d+)\\)`` 은 공백 없는 형태만 매칭 → 한정재고 N 을
전부 놓치고 None→999(충분) 로 둔갑(오발주 위험). 괄호 안 ``\\s*`` 2개로 수정.

폴백 금지: 한정 N 은 실수량이므로 999/평균/최저로 덮어쓰면 안 된다.
"""
from bs4 import BeautifulSoup

from lemouton.sourcing.crawlers.ssf import (
    NEAR_SOLDOUT_PATTERN,
    STATCD_SOLDOUT,
    _parse_sizes,
)


def test_near_soldout_pattern_allows_inner_whitespace():
    """get_text(" ") 가 만든 공백형/무공백형 둘 다 매칭해야 한다."""
    assert NEAR_SOLDOUT_PATTERN.search("품절임박(1)").group(1) == "1"
    # BeautifulSoup get_text(" ") 결과 — 괄호 안 공백
    assert NEAR_SOLDOUT_PATTERN.search("255[255] / 품절임박 ( 1 )").group(1) == "1"
    assert NEAR_SOLDOUT_PATTERN.search("품절임박 (  12  )").group(1) == "12"
    # 마커 없으면 None (충분 → 호출부서 999)
    assert NEAR_SOLDOUT_PATTERN.search("220[220]") is None


# 실제 SSF #optionDiv1 옵션 구조 (한정=품절임박/품절=SLDOUT/충분=마커없음)
def _opt(size, statcd, near=None):
    inner = f"{size}[{size}]"
    if near is not None:
        inner += f" / <span>품절임박</span>(<em>{near}</em>)"
    return (
        f'<li id="li_IT{size}" data="IT{size}">'
        f'<a optcd="{size}" statcd="{statcd}"><em>{inner}</em></a></li>'
    )


SAMPLE_HTML = (
    '<div id="optionDiv1"><ul>'
    + _opt("220", "SALE_PROGRS", near=3)   # 한정 3
    + _opt("235", "SLDOUT")                # 품절
    + _opt("255", "SALE_PROGRS", near=1)   # 한정 1
    + _opt("270", "SALE_PROGRS")           # 충분 (마커 없음)
    + "</ul></div>"
)


def test_parse_sizes_three_states():
    sizes = {s["name"]: s for s in _parse_sizes(BeautifulSoup(SAMPLE_HTML, "html.parser"))}

    # 한정: stock = 실수량 N (999/None 둔갑 금지)
    assert sizes["220mm"]["stock"] == 3
    assert sizes["220mm"]["soldOut"] is False
    assert sizes["255mm"]["stock"] == 1

    # 품절: statcd=SLDOUT → soldOut True
    assert sizes["235mm"]["soldOut"] is True

    # 충분: 마커 없음 → stock None (호출부서 999 센티넬로 처리)
    assert sizes["270mm"]["stock"] is None
    assert sizes["270mm"]["soldOut"] is False


def test_limited_stock_not_silently_999():
    """버그 재현 방지: 한정 사이즈가 None(→999) 으로 떨어지면 실패."""
    sizes = {s["name"]: s for s in _parse_sizes(BeautifulSoup(SAMPLE_HTML, "html.parser"))}
    limited = {n: s["stock"] for n, s in sizes.items() if not s["soldOut"] and s["stock"] is not None}
    assert limited == {"220mm": 3, "255mm": 1}
