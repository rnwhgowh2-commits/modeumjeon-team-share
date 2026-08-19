# -*- coding: utf-8 -*-
"""**이어서 걷기** — 한 회차 상한(60쪽)을 지키면서도 끝까지 간다.

🔴 왜 (2026-08-13)
   현대H몰 「나이키 신발」은 **456쪽 16,413개**다. 한 회차 상한이 60쪽이라
   한 번에 2,160개(13%)밖에 못 걷는다. **못 걷은 만큼 팔 상품이 줄어든다.**

   상한은 없앨 수 없다 — 소싱처를 몰아치면 차단·계정 위험이다(사람이 정한 안전선).
   대신 **회차를 거듭해** 끝까지 간다. 「더 있음」이면 다음 회차가 그 다음 창부터.

★ 「다음」 단추로 넘기는 곳(롯데온·아이몰)은 **이어걷기가 안 된다** — 늘 1쪽에서
  눌러 가야 해서 중간부터 시작할 방법이 없다. 그런 곳은 한 회차에 더 멀리 가는
  수밖에 없고, 그건 확장이 걸음마다 따로 훑어 해결한다.
"""
from __future__ import annotations

from lemouton.sources import listing_discover as LD


# ── 이어걷기가 되는 곳 / 안 되는 곳 ─────────────────────────────────────
def test_주소로_넘기는_곳은_이어걷기가_된다():
    assert LD.can_resume('hmall', 'https://www.hmall.com/search?q=나이키') is True
    assert LD.can_resume('ssg', 'https://www.ssg.com/search.ssg?query=나이키') is True
    assert LD.can_resume('lemouton', 'https://lemouton.co.kr/product/list.html?cate_no=60') is True


def test_단추로_넘기는_곳도_이어걷기가_된다():
    """🔴 [2026-08-13 뒤집음] 처음엔 「안 된다」고 못 박았다 — 늘 1쪽에서 눌러
    가야 해서 중간부터 시작할 수단이 없다고 봤기 때문이다.

    그러면 한 회차 상한(60쪽=3,600개)이 **영원한 천장**이 된다. 아이몰
    「나이키 신발」은 46,009개(767쪽)라 **92%를 영영 못 걷는다.**

    ★ 방법이 있었다 — **걷지 않고 누르기만** 하면 된다(`click_skip_for`).
      301쪽부터 걸으려면 300번 누르고 시작한다. 훑지 않으니 훨씬 빠르다.
      자세한 것은 `test_click_resume_skip.py`.

    ★★ 배운 것 — **「구조상 안 된다」는 판정도 낡는다.** 「그 수단이 없다」와
       「내가 아직 못 찾았다」는 다른 사실이다.
    """
    assert LD.can_resume('lotteon', 'https://www.lotteon.com/search/search/search.ecn?q=x') is True
    assert LD.can_resume('lotteimall', 'https://www.lotteimall.com/search/searchMain.lotte?q=x') is True


def test_SSF_검색주소는_이어걷기가_안_된다():
    """같은 소싱처인데 주소 종류에 따라 다르다 — 검색은 쪽이 안 먹는다(실측)."""
    assert LD.can_resume('ssf', 'https://www.ssfshop.com/search/result?keyword=x') is False
    assert LD.can_resume('ssf', 'https://www.ssfshop.com/A/list?dspCtgryNo=1') is True


# ── 창을 어디까지 걷나 ──────────────────────────────────────────────────
def test_처음에는_사장님이_적은_대로():
    assert LD.window_for(1, 60, None) == (1, 60)
    assert LD.window_for(1, 10, None) == (1, 10)


def test_이어걷기면_그_다음_창부터():
    """1~60 을 걷고 「더 있음」이면 다음은 61~120."""
    nxt = LD.next_window(1, 60, None, more=True)
    assert nxt == 61, nxt
    assert LD.window_for(1, 60, nxt) == (61, 120)
    nxt2 = LD.next_window(1, 60, nxt, more=True)
    assert nxt2 == 121, nxt2
    assert LD.window_for(1, 60, nxt2) == (121, 180)


def test_창_크기는_사장님이_적은_그대로():
    """「몇 쪽부터~까지」가 한 회차에 걷는 창이다 — 임의로 넓히지 않는다."""
    nxt = LD.next_window(1, 10, None, more=True)
    assert nxt == 11
    assert LD.window_for(1, 10, nxt) == (11, 20)


def test_끝까지_걸었으면_처음으로_되돌린다():
    """🔴 이걸 안 하면 **앞쪽에 들어온 새 상품을 영영 못 본다.**

    상품은 앞쪽(최신)에 들어온다. 한 바퀴 돌고도 커서를 456쪽에 두면
    그 뒤로는 늘 빈 쪽만 보게 된다.
    """
    assert LD.next_window(1, 60, 421, more=False) is None


def test_상한을_넘는_창은_상한까지만():
    """사장님이 1~9999 를 적어도 한 회차는 60쪽까지다(소싱처 보호선)."""
    lo, hi = LD.window_for(1, 9999, None)
    assert (lo, hi) == (1, LD.MAX_PAGES), (lo, hi)
    assert LD.next_window(1, 9999, None, more=True) == 1 + LD.MAX_PAGES


def test_이어걷기_창도_실제_주소로_만들어진다():
    """계산만 맞고 주소가 안 바뀌면 같은 쪽을 또 걷는다."""
    lo, hi = LD.window_for(1, 3, 4)          # 2회차: 4~6쪽
    urls = LD.page_urls_for('https://www.hmall.com/search?q=나이키',
                            source_key='hmall', page_from=lo, page_to=hi)
    assert urls == ['https://www.hmall.com/search?q=나이키&page=4',
                    'https://www.hmall.com/search?q=나이키&page=5',
                    'https://www.hmall.com/search?q=나이키&page=6'], urls
