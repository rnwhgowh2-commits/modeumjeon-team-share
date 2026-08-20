# -*- coding: utf-8 -*-
"""SSF 는 **같은 소싱처인데 주소 종류에 따라 페이지 넘김이 다르다.**

━━ 🔴 내 규칙의 구멍 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
`_PAGE_PARAM` 은 **소싱처 단위**라 주소 종류를 구분하지 않았다. 그런데 실측하니:

  · 카테고리 목록 `/…/list?dspCtgryNo=…`  → `currentPage` 가 **진짜 먹는다**
      (1쪽과 2쪽의 상품 60개가 서로 달랐다)
  · 검색 결과   `/search/result?keyword=…` → `currentPage` 가 **안 먹는다**
      (2026-08-08 실측: 1쪽·2쪽·`page=2` 모두 상품 60개가 **완전히 겹침**)

그대로 두면 사장님이 **검색 주소**로 필터를 만들고 「5쪽까지」로 시켰을 때
**같은 1쪽을 5번 긁고 「5장 봤다」**고 말한다 — 내가 다른 소싱처에서 그렇게 될까 봐
일부러 막아 뒀던 바로 그 거짓말이다.

★ 검색 주소여도 **첫 쪽 60개는 정상으로 걷힌다.** 예외로 막지 않는다 —
  걷을 수 있는 데까지는 걷고, 「더 있음」으로 알린다.
"""
from lemouton.sources.listing_discover import page_urls_for


SEARCH = 'https://www.ssfshop.com/search/result?keyword=8SECONDS'
CATEGORY = ('https://www.ssfshop.com/Beanpole-Men/OUTLET/list?dspCtgryNo=SFMA44'
            '&brandShopNo=BDMA01A01')


def test_SSF_검색은_쪽을_안_붙인다():
    """🔴 붙이면 같은 1쪽을 여러 번 긁고 「여러 장 봤다」고 거짓말한다."""
    got = page_urls_for(SEARCH, source_key='ssf', page_from=1, page_to=5)

    assert got == [SEARCH], got


def test_SSF_카테고리_목록은_예전처럼_쪽을_붙인다():
    """실측 — 여기선 `currentPage` 가 진짜로 넘어간다(1쪽·2쪽 상품 60개가 달랐다)."""
    got = page_urls_for(CATEGORY, source_key='ssf', page_from=1, page_to=3)

    assert got == [CATEGORY + '&currentPage=1',
                   CATEGORY + '&currentPage=2',
                   CATEGORY + '&currentPage=3'], got


def test_SSF_검색이어도_첫_쪽은_걷는다():
    """예외로 막으면 60개조차 못 걷는다 — 걷을 수 있는 데까지는 걷는다."""
    got = page_urls_for(SEARCH, source_key='ssf')

    assert got == [SEARCH], got
