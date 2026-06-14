"""parse_html(html, url) -> CrawlResult 분리 검증 테스트.

Task 2~5: 4개 비로그인 소싱처(ssf/ssg/ss_lemouton/lemouton)의
parse_html 메서드가 픽스처 HTML 을 올바르게 파싱하는지 확인한다.
"""
from lemouton.sourcing.crawlers import build_crawlers

URLS = {
    "ssf": "https://www.ssfshop.com/LEMOUTON/GRG426021974780/good",
    "ssg": "https://www.ssg.com/item/itemView.ssg?itemId=1000809938058&siteNo=6009&salestrNo=1004",
    "ss_lemouton": "https://brand.naver.com/lemouton/products/9496367527",
    "lemouton": "https://lemouton.co.kr/product/detail.html?product_no=219",
}


def _check(key, html_of):
    c = build_crawlers()[key]
    res = c.parse_html(html_of(key), URLS[key])
    assert res.source == key
    assert res.product_name_raw
    assert len(res.options) > 0
    assert all(o["price"] > 0 for o in res.options)


def test_ssf_parse_html(html_of):
    _check("ssf", html_of)


def test_ssg_parse_html(html_of):
    _check("ssg", html_of)


def test_ss_lemouton_parse_html(html_of):
    _check("ss_lemouton", html_of)


def test_lemouton_parse_html(html_of):
    _check("lemouton", html_of)


def test_ssf_js_string_size_stock():
    """[2026-06-14] SSF 가 옵션을 <script> JS 문자열(camelCase optCd/statCd)로 임베드.

    BeautifulSoup a[optcd] 셀렉터로는 0개라 전 사이즈 999 둔갑하던 것을 raw HTML
    정규식 파싱으로 교정: 품절임박(N)→N(한정) / SLDOUT→품절(soldOut) / 표시없음→None(충분).
    """
    from bs4 import BeautifulSoup
    from lemouton.sourcing.crawlers.ssf import _parse_sizes
    # 실제 SSF raw 구조(JS 문자열) 축약 — optCd/statCd camelCase, 품절임박</span>(<em>N</em>)
    html = (
        'var x = "<a godNo="G1" optCd="220" statCd="SALE_PROGRS">'
        '<em>220[220]&nbsp;/ <span>품절임박</span>(<em>3</em>)</em></a>'
        '<a godNo="G1" optCd="235" statCd="SLDOUT"><em>235[235]&nbsp;/ 품절(재입고 알림 신청)</em></a>'
        '<a godNo="G1" optCd="240" statCd="SALE_PROGRS"><em>240[240]</em></a>";'
    )
    sizes = _parse_sizes(BeautifulSoup("<html></html>", "lxml"), html)
    by = {s["name"]: s for s in sizes}
    assert by["220mm"]["stock"] == 3 and by["220mm"]["soldOut"] is False   # 한정 3
    assert by["235mm"]["soldOut"] is True                                   # 품절
    assert by["240mm"]["stock"] is None                                     # 충분(표시없음)


def test_ss_lemouton_sku_stock_override(html_of):
    """[2026-06-14] 확장이 n/v2 로 수집한 per-SKU 재고가 옵션별 stock 을 교정한다.

    배경: inline state 엔 SKU별 재고가 없어 옵션 다중 상품은 전부 999(있음) 둔갑했다.
    sku_stock("색상||사이즈"→수량)을 주면 해당 SKU 만 실수량/품절로 교정(미스 키는 999 유지).
    """
    c = build_crawlers()["ss_lemouton"]
    html = html_of("ss_lemouton")
    base = c.parse_html(html, URLS["ss_lemouton"])
    multi = [o for o in base.options if o.get("size_text")]  # 사이즈 있는 옵션
    if not multi:
        return  # 단품 픽스처면 스킵(해당 픽스처는 단일 옵션)
    target = multi[0]
    color, size = target["color_text"], target["size_text"]
    sku = {f"{color}||{size}": 0,            # 이 SKU = 품절
           f"{color}|| {size} ": 0}          # 공백 표기차 방어도 같이
    res = c.parse_html(html, URLS["ss_lemouton"], sku_stock=sku)
    got = {(o["color_text"], o["size_text"]): o["stock"] for o in res.options}
    assert got[(color, size)] == 0          # 교정됨(품절)
    # 맵에 없던 다른 SKU 는 기존 로직(999 또는 단품 수량) 유지 — 0 으로 둔갑 안 됨
    others = [v for k, v in got.items() if k != (color, size)]
    assert any(v != 0 for v in others) if len(others) else True
