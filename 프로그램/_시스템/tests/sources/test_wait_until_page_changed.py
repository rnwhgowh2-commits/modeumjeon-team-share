# -*- coding: utf-8 -*-
"""「다음」을 누른 뒤 **화면이 바뀔 때까지 지켜본다** — 고정 시간으로 기다리지 않는다.

🔴🔴 왜 (2026-08-13 라이브 롯데아이몰)
   아이몰 쪽 넘김 선택자를 고친 뒤 60쪽으로 시켰는데 **새로 걷은 것이 0개**였다.
   확장은 새 판(0.7.98)으로 제대로 돌았고 선택자도 1쪽에서 잘 잡혔다.

   범인은 **누른 뒤 1.2초**였다. 아이몰이 아직 다시 그리기 전이라 **같은 쪽**을 읽고
   「안 늘었다」며 첫 쪽에서 멈춘 것이다.
   (내가 손으로 잴 때 3.5초를 기다린 것이 **우연히 넉넉했을 뿐**이다.)

★ 고정 시간은 두 가지가 다 나쁘다 —
  짧으면 같은 쪽을 읽고 멈추고, 길면 쪽마다 그만큼 느려진다.
  **바뀔 때까지 지켜보면** 빠른 곳은 바로 넘어가고 느린 곳도 안 놓친다.

★★ 배운 것 — **「기다린다」와 「바뀐 것을 확인한다」는 다르다.**
   내가 손으로 재서 되던 값을 그대로 코드에 넣으면, 그건 실측이 아니라 우연이다.
"""
from __future__ import annotations

import re
from pathlib import Path

BG = (Path(__file__).resolve().parents[2]
      / 'extension' / 'moum-crawler' / 'background.js')


def _src() -> str:
    return BG.read_text(encoding='utf-8')


def _waiter() -> str:
    m = re.search(r'async function _listingWaitPageChanged\(.*?\n\}', _src(), re.S)
    assert m, ('바뀔 때까지 지켜보는 함수(_listingWaitPageChanged)를 못 찾았습니다.')
    return m.group(0)


def test_지켜보는_함수가_있다():
    body = _waiter()
    assert '_listingSweepInPage' in body, '무엇이 바뀌었는지 재지 않습니다.'


def test_첫_상품번호가_바뀌면_바로_넘어간다():
    body = _waiter()
    assert re.search(r'if \(now && now !== before\) return true;', body), (
        '바뀐 것을 알아보고 바로 넘어가지 않습니다 — 쪽마다 쓸데없이 느려집니다.'
    )


def test_시한이_있다():
    """영영 안 바뀌는 화면에서 무한 대기하면 필터 하나가 폴링을 통째로 잡는다."""
    body = _waiter()
    assert re.search(r'while \(Date\.now\(\) - t0 < maxMs\)', body), '시한이 없습니다.'
    assert re.search(r'return false;', body), '시한이 지난 뒤 돌려주는 값이 없습니다.'


def test_누른_뒤_고정시간_대기를_안_쓴다():
    """🔴 이 파일의 핵심 — 고정 1.2초가 아이몰을 첫 쪽에서 멈추게 했다."""
    src = _src()
    m = re.search(r'async function _listingWalkByClicks\(.*?\n\}', src, re.S)
    assert m, '걸음마다 훑는 함수를 못 찾았습니다.'
    body = m.group(0)
    assert '_listingWaitPageChanged' in body, (
        '누른 뒤 「바뀔 때까지 지켜보기」를 안 씁니다.'
    )
    assert not re.search(r'setTimeout\(r, 1200\)', body), (
        '아직 고정 1.2초 대기가 남아 있습니다 — 아이몰이 다시 멈춥니다.'
    )


def test_건너뛸_때도_지켜본다():
    """안 바뀐 채 다음을 누르면 같은 자리를 헛돌며 「건너뛰었다」고 착각한다."""
    src = _src()
    m = re.search(r'for \(let k = 0; k < skip; k\+\+\) \{.*?\n  \}', src, re.S)
    assert m, '건너뛰는 반복을 못 찾았습니다.'
    assert '_listingWaitPageChanged' in m.group(0), (
        '건너뛸 때 바뀐 것을 확인하지 않습니다 — 같은 자리를 헛돕니다.'
    )
