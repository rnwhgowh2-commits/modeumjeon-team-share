# -*- coding: utf-8 -*-
"""SSG — 규칙은 넣되 **아직 눈으로 못 본 곳**임을 분명히 한다.

━━ 무엇을 아는가 / 모르는가 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
**안다**
  · 페이지 넘김 = `page=` — 사장님이 2쪽으로 넘긴 주소를 그대로 주셨다.
      `…/search.ssg?target=all&query=나이키+신발&page=2&shpp=department`
  · 상품 주소 모양 = `https://www.ssg.com/item/itemView.ssg?itemId=…`
      — 우리 크롤러 `sourcing/crawlers/ssg.py` 첫 줄에 적혀 있고, 그 크롤러가
        라이브에서 SSG 상품을 실제로 긁고 있다(지어낸 값이 아니다).

**모른다**
  🔴 검색 결과 화면에서 **상품 링크가 실제로 어떻게 생겼는지 못 봤다.**
    SSG 는 앱 브라우저·사장님 크롬 연결 **둘 다 정책 차단**이고, 서버로 받아도
    403 이다(2026-08-08 확인). 즉 내 눈으로는 확인할 방법이 없다.
  🔴 결과 0건 화면에 추천 상품이 깔리는지도 모른다(6곳 중 5곳이 그랬다).

━━ 그래서 이렇게 한다 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
규칙을 넣어 **확장이 사장님 크롬에서 대신 재 보게** 한다 — 확장은 안 막힌다.
첫 수집 결과가 나오면 그때 「맞다/틀리다」를 사장님 화면 숫자와 대조한다.
그때까지 **「검증됨」이라고 적지 않는다.**
"""
from lemouton.sources.listing_discover import (
    dom_rule_for, extract_product_urls, page_urls_for)


SEARCH = ('https://www.ssg.com/search.ssg?target=all&query=%EB%82%98%EC%9D%B4%ED%82%A4+%EC%8B%A0%EB%B0%9C'
          '&shpp=department')

HTML = """
<a href="/item/itemView.ssg?itemId=1000552535854&siteNo=6009&salestrNo=6009">A</a>
<a href="https://www.ssg.com/item/itemView.ssg?itemId=1000660011122&siteNo=6001">B</a>
<a href="/item/itemView.ssg?itemId=1000552535854">A 또(다른 꼬리표)</a>
<a href="/disp/category.ssg?dispCtgId=6000123">카테고리 — 상품 아님</a>
"""


def test_상품번호만_뽑아_우리_틀로_다시_만든다():
    """`siteNo`·`salestrNo` 꼬리표가 붙은 채 저장되면 같은 상품이 여러 벌로 갈린다."""
    urls = extract_product_urls(HTML, source_key='ssg')

    assert urls == ['https://www.ssg.com/item/itemView.ssg?itemId=1000552535854',
                    'https://www.ssg.com/item/itemView.ssg?itemId=1000660011122'], urls


def test_page_로_쪽을_넘긴다():
    """사장님이 2쪽으로 넘긴 뒤의 주소를 그대로 주셨다 — `page=2`."""
    got = page_urls_for(SEARCH, source_key='ssg', page_from=1, page_to=3)

    assert got == [SEARCH + '&page=1', SEARCH + '&page=2', SEARCH + '&page=3'], got


def test_이미_page_가_붙어_있으면_바꿔_끼운다():
    base = SEARCH + '&page=2'
    got = page_urls_for(base, source_key='ssg', page_from=1, page_to=2)

    assert got == [SEARCH + '&page=1', SEARCH + '&page=2'], got


def test_확장에_줄_규칙이_있다():
    r = dom_rule_for('ssg')

    assert r['sel'] and r['attr'] == 'href' and r['id_re']


def test_결과없음_글귀는_아직_모른다고_남긴다():
    """🔴 모르는 것을 아는 척하지 않는다. 글귀를 지어 넣으면 두 가지로 틀린다 —
    영영 안 걸리거나(가짜 상품 통과), 멀쩡한 수집이 통째로 0건이 된다."""
    assert dom_rule_for('ssg')['empty_text'] is None
