# -*- coding: utf-8 -*-
"""**마지막 쪽에서도 새 상품이 나왔으면 「끝난 것」이 아니다.**

🔴 왜 (2026-08-12 라이브 현대H몰)
   1~60쪽으로 시켜 **2,159개**를 걷었다. 그런데 그 검색엔 **16,413개**가 있다.
   사장님이 적은 만큼만 열고 멈춘 것뿐인데 화면의 「더 있음」이 **꺼져** 있으면
   **2,159개가 전부**로 읽힌다.

   「끝까지 봤다」와 「시킨 만큼만 보고 멈췄다」는 다른 사실이다.

★ 판정 기준 — **마지막으로 연 쪽에서도 새 번호가 나왔나.** 나왔으면 아직 캘 것이
  남아 있는 것이다. 「총 몇 쪽인지」를 소싱처마다 알아내려 하지 않는다(모르는 곳이
  대부분이고, 추측하면 늘 켜지거나 늘 꺼져 둘 다 거짓말이 된다).

★ 한 쪽짜리(단추로 넘기는 롯데온·아이몰 등)는 제외한다 — 그 안에서 이미
  「다음 단추가 살아 있나」로 자기 방식의 판정을 한다. 두 번 판정하면 서로 덮는다.
"""
from __future__ import annotations

import re
from pathlib import Path

BG = (Path(__file__).resolve().parents[2]
      / 'extension' / 'moum-crawler' / 'background.js')


def _src() -> str:
    return BG.read_text(encoding='utf-8')


def test_마지막쪽에_새것이_있었는지_센다():
    src = _src()
    assert '_newOnLastPage' in src, '마지막 쪽 새 상품 수를 세는 곳이 없습니다.'
    # 쪽마다 0으로 되돌려야 **마지막** 쪽 값이 된다(누적이면 늘 켜진다).
    assert re.search(r'_newOnLastPage = 0;\s*\n\s*for \(const id of res\.ids\)', src), (
        '쪽마다 0으로 되돌리지 않으면 누적이 되어 「더 있음」이 늘 켜집니다 — '
        '늘 켜지는 경고는 아무 말도 안 하는 것과 같습니다.'
    )
    assert re.search(r'if \(!ids\.has\(id\)\) _newOnLastPage\+\+;', src), (
        '이미 본 번호까지 세면 같은 쪽을 다시 읽어도 「새 것이 있다」가 됩니다.'
    )


def test_마지막쪽에_새것이_있으면_더있음을_켠다():
    src = _src()
    m = re.search(r'if \(\(job\.page_urls \|\| \[\]\)\.length > 1 && _newOnLastPage > 0\)'
                  r' capped = true;', src)
    assert m, (
        '마지막 쪽까지 새 상품이 나왔는데 「더 있음」을 안 켭니다 — '
        '걷은 수가 전부로 읽힙니다.'
    )


def test_한쪽짜리는_제외한다():
    """단추로 넘기는 곳은 그 안에서 이미 판정한다 — 두 번 판정하면 서로 덮는다."""
    src = _src()
    assert 'page_urls || []).length > 1' in src, (
        '한 쪽짜리를 제외하지 않으면 단추로 넘기는 곳의 판정을 덮어씁니다.'
    )
