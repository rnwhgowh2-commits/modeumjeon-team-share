# -*- coding: utf-8 -*-
"""「다음」 단추 소싱처도 **이어서 걷는다** — 눌러서 건너뛰면 된다.

🔴 왜 (2026-08-13, 사장님: 「끝까지 해야지. 못 걷는 만큼 매출이 안 나온다」)
   롯데온·아이몰은 「다음」을 눌러야만 넘어간다. 늘 1쪽에서 시작해야 해서
   **중간부터 시작할 방법이 없다**고 보고 이어걷기를 막아 뒀다.
   그러면 한 회차 상한(60쪽=3,600개)이 **영원한 천장**이 된다.
   아이몰 「나이키 신발」은 46,009개 — 767쪽이다. 92%를 못 걷는다.

★ 그런데 방법이 있다 — **걷지 않고 누르기만** 하면 된다. 301쪽부터 걸으려면
  300번 누르고 시작한다. 훑지 않으니 훨씬 빠르다.

🔴 공짜가 아니다. 쪽이 뒤로 갈수록 눌러야 할 횟수가 늘어난다. 시한에 걸리면
  확장이 **「더 있음」이라 말하며** 나온다 — 조용히 「끝남」이 되면 사장님이
  그 뒤 상품을 영영 못 본다.
"""
from __future__ import annotations

import re
from pathlib import Path

from lemouton.sources import listing_discover as LD

BG = (Path(__file__).resolve().parents[2]
      / 'extension' / 'moum-crawler' / 'background.js')


# ── 서버 쪽 ────────────────────────────────────────────────────────────
def test_단추로_넘기는_곳도_이어걷기가_된다():
    assert LD.can_resume('lotteon', 'https://www.lotteon.com/search/x') is True
    assert LD.can_resume('lotteimall', 'https://www.lotteimall.com/search/x') is True


def test_주소로_넘기는_곳은_건너뛸_필요가_없다():
    assert LD.click_skip_for('hmall', 301) == 0
    assert LD.click_skip_for('ssg', 61) == 0


def test_커서만큼_눌러_건너뛴다():
    assert LD.click_skip_for('lotteimall', None) == 0     # 처음이면 0
    assert LD.click_skip_for('lotteimall', 1) == 0
    assert LD.click_skip_for('lotteimall', 61) == 60      # 61쪽부터면 60번
    assert LD.click_skip_for('lotteon', 301) == 300


def test_이어걷기_커서가_실제로_는다():
    """1~60 을 걷고 「더 있음」이면 다음은 61쪽부터 → 60번 건너뛴다."""
    nxt = LD.next_window(1, 60, None, more=True)
    assert nxt == 61
    assert LD.click_skip_for('lotteimall', nxt) == 60


def test_다음쪽_주소를_따라가는_곳은_이어걷기가_없다():
    """무신사는 한 회차에 끝까지 간다(1,218 실증) — 중간 시작 수단이 없다."""
    assert LD.can_resume('musinsa', 'https://www.musinsa.com/search/goods?keyword=x') is False


def test_SSF_검색주소는_여전히_안_된다():
    assert LD.can_resume('ssf', 'https://www.ssfshop.com/search/result?keyword=x') is False


# ── 확장 쪽 ────────────────────────────────────────────────────────────
def _walk() -> str:
    m = re.search(r'async function _listingWalkByClicks\(.*?\n\}',
                  BG.read_text(encoding='utf-8'), re.S)
    assert m, '걸음마다 훑는 함수를 못 찾았습니다.'
    return m.group(0)


def test_확장이_건너뛰기를_실제로_한다():
    body = _walk()
    assert re.search(r'const skip = Math\.max\(0, Number\(rule\.click_skip\) \|\| 0\);', body), (
        '확장이 건너뛸 횟수를 안 읽습니다 — 서버가 보내도 안 쓰면 소용없습니다.'
    )
    assert re.search(r'for \(let k = 0; k < skip; k\+\+\)', body), '건너뛰는 반복이 없습니다.'


def test_건너뛰는_동안은_훑지_않는다():
    """훑으면 느려져 시한에 먼저 걸린다 — 건너뛸 때는 누르기만 한다."""
    body = _walk()
    skip_block = re.search(r'for \(let k = 0; k < skip; k\+\+\) \{.*?\n  \}', body, re.S)
    assert skip_block, '건너뛰는 반복을 못 찾았습니다.'
    assert '_listingSweepInPage' not in skip_block.group(0), (
        '건너뛰는 동안에도 훑고 있습니다 — 느려서 시한에 먼저 걸립니다.'
    )


def test_건너뛰다_시한이_와도_더있음이라_말한다():
    """🔴 조용히 「끝남」이 되면 그 뒤 상품을 영영 못 본다."""
    body = _walk()
    assert re.search(r'if \(capped\) return \{ ids: \[\], capped: true \};', body), (
        '건너뛰다 시한에 걸렸을 때 「더 있음」으로 안 나옵니다.'
    )


def test_확장이_서버에서_받은_값을_규칙에_싣는다():
    src = BG.read_text(encoding='utf-8')
    assert 'click_skip: job.click_skip' in src, (
        '서버가 보낸 건너뛰기 횟수를 규칙에 안 싣습니다.'
    )
