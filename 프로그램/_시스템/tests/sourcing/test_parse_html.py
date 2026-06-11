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
