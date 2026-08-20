# -*- coding: utf-8 -*-
"""「다음」 단추로 넘기는 곳도 **끝까지 걷고, 걷은 것을 잃지 않는다.**

🔴🔴 왜 (2026-08-12~13 라이브 롯데온·롯데아이몰)
   1~60쪽으로 시켰더니 「훑는 중 시간 초과」가 나고 **새로 걷은 것이 0개**였다.
   그때까지 걷은 것이 **통째로 사라진** 것이다. 10쪽으로 낮춰야 겨우 됐는데,
   그건 답이 아니다 — 못 걷은 만큼 팔 상품이 줄어든다.

   원인은 「눌렀다 훑었다」를 **한 번의 긴 주입 안에서** 다 한 것이다.
     ① 시한을 넘기면 주입 결과가 통째로 버려진다
     ② 「다음」이 **진짜 페이지 이동**이면 주입된 코드가 함께 죽어 영영 안 돌아온다

★ 그래서 **한 걸음마다 따로 주입**한다. 배경(서비스워커)이 결과를 들고 있으므로
  페이지가 갈아 끼워지든 통째로 이동하든 **걷은 것은 남는다.**
"""
from __future__ import annotations

import re
from pathlib import Path

BG = (Path(__file__).resolve().parents[2]
      / 'extension' / 'moum-crawler' / 'background.js')


def _src() -> str:
    return BG.read_text(encoding='utf-8')


def _walk() -> str:
    m = re.search(r'async function _listingWalkByClicks\(.*?\n\}', _src(), re.S)
    assert m, ('걸음마다 훑는 함수(_listingWalkByClicks)를 못 찾았습니다. '
               '이름이 바뀌었다면 이 시험도 같이 고쳐야 합니다.')
    return m.group(0)


def test_걸음마다_따로_훑는_함수가_있다():
    body = _walk()
    assert '_listingSweepInPage' in body, '한 걸음 훑기가 따로 없습니다.'
    assert '_listingClickNextInPage' in body, '「다음」 누르기가 따로 없습니다.'


def test_단추로_넘기는_곳은_이_길로_간다():
    """🔴 만들어 놓고 안 쓰면 소용없다 — 「규칙을 넣었다」와 「그게 쓰인다」는 다르다."""
    src = _src()
    assert re.search(r'if \(rule\.more_sel\) \{\s*\n.*?_listingWalkByClicks', src, re.S), (
        '「다음」 단추가 있는 소싱처를 새 길로 안 보냅니다.'
    )


def test_시한이_와도_걷은_것을_들고_나온다():
    """🔴 이 파일의 핵심 — 통째로 버리면 10쪽으로 낮추는 수밖에 없다."""
    body = _walk()
    assert re.search(r'if \(Date\.now\(\) > deadline\) \{ capped = true; break; \}', body), (
        '시한이 왔을 때 걷은 것을 들고 나오지 않습니다 — 통째로 사라집니다.'
    )
    assert re.search(r'return \{ ids: Array\.from\(seen\), capped: capped \}', body), (
        '걷은 것을 돌려주지 않습니다.'
    )


def test_페이지가_이동해도_견딘다():
    """「다음」이 진짜 이동이면 다음 걸음 전에 로드를 기다려야 한다."""
    body = _walk()
    assert '_notionWaitTab(tabId' in body, (
        '「다음」을 누른 뒤 페이지 로드를 안 기다립니다 — 진짜 이동하는 곳에서 '
        '빈 화면을 훑게 됩니다.'
    )


def test_헛돌기와_마지막장을_구분한다():
    body = _walk()
    assert re.search(r'if \(i > 0 && seen\.size === before\) break;', body), (
        '눌렀는데 안 늘어난 경우를 안 막으면 같은 장을 헛돕니다.'
    )
    assert re.search(r'if \(!c \|\| !c\.clicked\) break;', body), (
        '단추가 사라진 경우(마지막 장)를 안 막습니다.'
    )


def test_아직_단추가_살아_있으면_더있음이다():
    body = _walk()
    assert '_listingHasNextInPage' in body, (
        '다 걸은 뒤 「다음」이 남아 있는지 안 봅니다 — 덜 걷고 「끝남」이 됩니다.'
    )


def test_결과없음_화면을_먼저_본다():
    """🔴 0건 화면에도 추천 상품이 깔린다 — 그걸 상품으로 걷으면 안 된다."""
    src = _src()
    m = re.search(r'function _listingSweepInPage\(.*?\n\}', src, re.S)
    assert m, '한 걸음 훑기 함수를 못 찾았습니다.'
    assert 'emptyText' in m.group(0) and 'empty: true' in m.group(0), (
        '「검색 결과 없음」 글귀를 안 봅니다 — 오타 한 번에 엉뚱한 상품이 걷힙니다.'
    )
