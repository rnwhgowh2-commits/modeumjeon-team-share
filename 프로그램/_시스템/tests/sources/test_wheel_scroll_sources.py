# -*- coding: utf-8 -*-
"""현대H몰 — 「스크롤」로 보이지만 **주소로 쪽이 넘어간다.**

━━ 실측 여정 (2026-08-08) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
사장님: 「현대H몰 늘어남 (스크롤 형태)」. 그래서 스크롤을 파고들었는데 —

  · `window.scrollTo` / 안쪽 상자 `scrollTop` → 안 늘어남
  · `new WheelEvent(...)` 흉내 → 안 늘어남
  · **진짜 마우스 휠**(브라우저가 만든 신호)로 굴리니 **화면 상품은 바뀌는데**
    `[data-slitm-cd]` 는 계속 **같은 36개**였다(합집합 36, 새로 생긴 것 0)

즉 화면은 36개짜리 창을 갈아 끼우고 있었고, 우리가 보던 36개는 그 창이 아니었다.

━━ 답은 훨씬 단순했다 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
`__NEXT_DATA__` 에 `totalCount 16,406` · `totalPages 456` 이 있었다 — 쪽당 36개.
검색 주소에 **`page=` 를 붙이니 그대로 넘어갔다**(6쪽 = 216개, 중복 0).
`pageNo=` 는 안 먹는다(1쪽과 같음) — 이름을 확인하지 않으면 또 같은 쪽을 반복한다.

★ 배운 것 — **「스크롤로 보인다」가 「스크롤로만 된다」는 뜻은 아니다.**
  화면 동작을 흉내 내기 전에 **주소부터 눌러 봐야** 한다. 훨씬 빠르고 튼튼하다.
"""
from lemouton.sources.listing_discover import click_pages_for, page_urls_for


HMALL = ('https://www.hmall.com/md/pde/search?gnbSearchYn=Y&requestPath=w&tab=all'
         '&searchTerm=%EB%82%98%EC%9D%B4%ED%82%A4+%EC%8B%A0%EB%B0%9C&searchType=normal')


def test_H몰은_주소로_쪽을_넘긴다():
    got = page_urls_for(HMALL, source_key='hmall', page_from=1, page_to=3)

    assert got == [HMALL + '&page=1', HMALL + '&page=2', HMALL + '&page=3'], got


def test_H몰은_눌러야_할_단추가_없다():
    """주소로 넘기니 단추를 누르거나 휠을 굴릴 필요가 없다 — 두 번 걷게 된다."""
    assert click_pages_for('hmall', 1, 5) == 1


def test_휠로_굴려야_하는_곳은_이제_없다():
    """🔴 실측 결과 휠은 답이 아니었다(화면은 바뀌는데 같은 36개).
    쓰지도 않을 통로를 남겨 두면 나중에 「이건 왜 있지」가 된다."""
    from lemouton.sources import listing_discover as LD

    assert not getattr(LD, '_WHEEL_SCROLL', set())
