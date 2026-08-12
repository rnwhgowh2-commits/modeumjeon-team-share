# -*- coding: utf-8 -*-
"""단추로 넘기는 소싱처도 **여러 장**을 걷는다.

━━ 왜 필요한가 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
롯데온·롯데아이몰은 주소로도 스크롤로도 못 넘긴다(2026-08-08 실측) — **단추를
눌러야** 넘어간다. 그래서 지금은 첫 장(48·24건)만 가져오고 「더 있음」만 알린다.
수천 개를 올리는 대량등록에서 48건은 쓸모가 얕다.

━━ 사장님 화면을 그대로 쓴다 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
「몇 쪽부터 / 몇 쪽까지」 칸이 **이미 있다.** 주소로 넘기는 곳은 주소를 만들고,
단추로 넘기는 곳은 **그만큼 단추를 누른다.** 칸을 새로 만들지 않는다 —
같은 뜻인데 칸이 둘이면 사장님이 어느 쪽을 채워야 할지 모른다.

━━ 🔴 상한은 사람이 정한 안전선 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
`MAX_PAGES` 를 그대로 쓴다. 실수로 1~9999 를 넣으면 소싱처를 두들긴다(차단 위험).
"""
import pytest

from lemouton.sources.listing_discover import (
    MAX_PAGES, click_pages_for, page_urls_for)


# ── 단추로 넘기는 곳 ──────────────────────────────────────────────────

def test_범위를_주면_그만큼_누른다():
    assert click_pages_for('lotteon', 1, 5) == 5


def test_범위를_안_주면_첫_장만():
    """임의로 넓히지 않는다 — 사장님이 안 시킨 만큼 소싱처를 두들기지 않는다."""
    assert click_pages_for('lotteon', None, None) == 1


def test_주소가_2쪽부터여도_몇_장으로_센다():
    """단추는 지금 화면에서부터 누른다 — 2쪽부터 4쪽까지면 3장이다."""
    assert click_pages_for('lotteon', 2, 4) == 3


def test_상한을_넘지_않는다():
    assert click_pages_for('lotteon', 1, 9999) == MAX_PAGES


def test_주소로_넘기는_곳은_누르지_않는다():
    """르무통은 주소로 넘긴다 — 단추까지 누르면 같은 상품을 두 번 걷는다."""
    assert click_pages_for('lemouton', 1, 5) == 1


def test_무신사도_여러_장을_걷는다():
    """🔴 무신사엔 「다음」 단추가 없지만 응답이 `nextPageUrl` 을 준다.
    이걸 1 로 답하면 **확장이 첫 쪽만 보고 끝난다**(다음쪽을 아예 안 따라감)."""
    assert click_pages_for('musinsa', 1, 5) == 5


def test_넘기는_법을_모르는_곳도_첫_장만():
    """규칙이 없는 소싱처는 예외를 내지 않는다 — 첫 장은 걷을 수 있다.
    ★ 예전엔 H몰이 이 자리였는데, `page=` 로 넘어가는 것을 실측해 옮겼다."""
    assert click_pages_for('ss_lemouton', 1, 5) == 1


def test_SSF는_주소로_넘긴다():
    """★ 처음엔 「SSF도 둘 다 모른다」고 적었는데 틀렸다 — 카테고리 목록에서
    `currentPage` 가 진짜로 먹는 것을 실측했다(1쪽·2쪽 상품 60개가 달랐다)."""
    assert click_pages_for('ssf', 1, 5) == 1      # 주소로 넘기니 안 누른다


# ── 주소 만들기는 그대로 ──────────────────────────────────────────────

def test_단추로_넘기는_곳은_주소를_한_장만_만든다():
    """🔴 예전엔 여기서 예외가 났다 — 범위를 주면 「페이지 넘김 규칙을 모릅니다」.
    이제는 **주소 한 장 + 단추 N번**으로 답한다(첫 장도 못 걷던 것이 걷힌다)."""
    got = page_urls_for('https://www.lotteon.com/search/search/search.ecn?q=나이키',
                        source_key='lotteon', page_from=1, page_to=3)

    assert got == ['https://www.lotteon.com/search/search/search.ecn?q=나이키'], got


def test_주소로_넘기는_곳은_예전_그대로():
    """★ 예시를 무신사 → 르무통으로 바꿨다. 무신사는 `page=` 를 서버가 무시한다(실측)."""
    got = page_urls_for('https://lemouton.co.kr/product/list_women.html?cate_no=60',
                        source_key='lemouton', page_from=1, page_to=2)

    assert got == ['https://lemouton.co.kr/product/list_women.html?cate_no=60&page=1',
                   'https://lemouton.co.kr/product/list_women.html?cate_no=60&page=2'], got


def test_둘_다_모르는_곳은_주소를_그대로_한_장():
    """예외로 막으면 첫 장조차 못 걷는다 — 걷을 수 있는 데까지는 걷는다.
    ★ 예전엔 H몰이 이 자리였는데 `page=` 가 먹는 것을 실측해 다른 곳으로 바꿨다."""
    got = page_urls_for('https://smartstore.naver.com/lemouton/category/ALL',
                        source_key='ss_lemouton', page_from=1, page_to=3)

    assert got == ['https://smartstore.naver.com/lemouton/category/ALL'], got
