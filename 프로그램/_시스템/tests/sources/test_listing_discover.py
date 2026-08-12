# -*- coding: utf-8 -*-
"""리스팅 URL → 상품 URL 목록 — 대량등록 수집의 입구.

━━ 재구현 금지 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
`sourcing/crawlers/musinsa.py::discover_variants` 가 **이미** 무신사 검색 페이지를
열어 `/products/{id}` 링크를 전부 긁는다. 여기서 새 크롤러를 만들지 않고 그
「페이지에서 상품 링크를 뽑는 규칙」만 순수 함수로 꺼내 쓴다.

이 파일이 고정하는 것 — **페이지를 여는 일(브라우저)과 링크를 고르는 일(규칙)을 가른다.**
브라우저는 로컬 PC 워커가 담당하므로(크롤=로컬 PC 원칙), 규칙만 서버에서 시험할 수 있어야
한다. 규칙이 브라우저에 묶여 있으면 영영 시험을 못 한다.
"""
import pytest

from lemouton.sources.listing_discover import (
    extract_product_urls, page_urls_for, MAX_PAGES)


# ── 무신사 ─────────────────────────────────────────────────────────────

MUSINSA_HTML = """
<a href="/products/3976350">나이키 에어포스1</a>
<a href="https://www.musinsa.com/products/1234567?srsltid=x">나이키 덩크</a>
<a href="/products/3976350">같은 상품 또 나옴(썸네일·제목 둘 다 링크)</a>
<a href="/brands/nike">브랜드 페이지 — 상품 아님</a>
<a href="/products/">번호 없음 — 상품 아님</a>
"""


def test_상품_링크만_골라내고_중복은_한_번만():
    urls = extract_product_urls(MUSINSA_HTML, source_key='musinsa')

    assert urls == ['https://www.musinsa.com/products/3976350',
                    'https://www.musinsa.com/products/1234567'], urls


def test_추적_꼬리표는_떼고_같은_상품으로_본다():
    """`?srsltid=` 같은 광고 추적 꼬리표가 붙으면 같은 상품이 두 벌로 갈린다."""
    html = ('<a href="/products/111">A</a>'
            '<a href="https://www.musinsa.com/products/111?srsltid=abc">A 또</a>')
    assert extract_product_urls(html, source_key='musinsa') == [
        'https://www.musinsa.com/products/111']


def test_저장_상품수_상한을_넘기지_않는다():
    html = ''.join(f'<a href="/products/{i}">x</a>' for i in range(1, 11))
    urls = extract_product_urls(html, source_key='musinsa', max_items=4)
    assert len(urls) == 4, urls


def test_상품이_하나도_없으면_빈_목록():
    """0 건은 오류가 아니다 — 검색 결과가 없을 수 있다. 빈 목록으로 정직하게 답한다."""
    assert extract_product_urls('<a href="/brands/nike">x</a>',
                                source_key='musinsa') == []


def test_모르는_소싱처는_규칙이_없다고_말한다():
    """🔴 지어내지 않는다 — 규칙을 모르면 빈 목록이 아니라 예외로 표면화한다."""
    with pytest.raises(ValueError) as e:
        extract_product_urls(MUSINSA_HTML, source_key='29cm')
    assert '29cm' in str(e.value)


# ── 페이지 범위 ────────────────────────────────────────────────────────
#   🔴 [2026-08-08 정정] 예전엔 여기 예시가 **무신사**였다. 그런데 무신사는
#     `page=` 를 **서버가 아예 무시한다**(1쪽·2쪽 응답의 상품번호가 완전히 동일,
#     둘 다 totalCount 2412). 그대로 두면 「5쪽까지」로 시켜도 같은 1쪽을 5번 긁고
#     「5장 봤다」고 거짓말한다 — 무신사는 `nextPageUrl` 을 따라간다.
#   주소로 진짜 넘어가는 곳은 **르무통**(1쪽·2쪽 상품 25개가 달랐다, 실측)과
#   SSF 카테고리 목록이다. 그래서 예시를 르무통으로 바꾼다.

def test_페이지_범위만큼_주소를_만든다():
    base = 'https://lemouton.co.kr/product/list_women.html?cate_no=60'
    got = page_urls_for(base, source_key='lemouton', page_from=2, page_to=4)

    assert got == [base + '&page=2', base + '&page=3', base + '&page=4'], got


def test_범위를_안_주면_첫_페이지만():
    base = 'https://lemouton.co.kr/product/list_women.html?cate_no=60'
    assert page_urls_for(base, source_key='lemouton') == [base]


def test_이미_page_가_붙어_있으면_바꿔_끼운다():
    """사장님이 2페이지 주소를 그대로 붙여넣을 수 있다 — page 가 두 번 붙으면 안 된다."""
    base = 'https://lemouton.co.kr/product/list_women.html?cate_no=60&page=7'
    got = page_urls_for(base, source_key='lemouton', page_from=1, page_to=2)

    assert got == ['https://lemouton.co.kr/product/list_women.html?cate_no=60&page=1',
                   'https://lemouton.co.kr/product/list_women.html?cate_no=60&page=2'], got


def test_페이지_수는_상한이_있다():
    """🔴 실수로 1~9999 를 넣으면 소싱처를 두들기게 된다 — 한 번에 훑을 수 있는 상한."""
    base = 'https://lemouton.co.kr/product/list_women.html?cate_no=60'
    got = page_urls_for(base, source_key='lemouton', page_from=1, page_to=9999)
    assert len(got) == MAX_PAGES, len(got)


def test_무신사에_주소를_만들지_않는다():
    """🔴 이 시험이 없으면 「page=」 거짓말이 조용히 되살아난다.
    무신사는 범위를 줘도 **주소 한 장**이고, 나머지는 nextPageUrl 로 따라간다."""
    base = 'https://www.musinsa.com/search/goods?keyword=나이키'
    got = page_urls_for(base, source_key='musinsa', page_from=1, page_to=5)

    assert got == [base], got
