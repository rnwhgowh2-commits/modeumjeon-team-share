# -*- coding: utf-8 -*-
"""**다 걷고도 「더 있다」고 하지 않는다.**

🔴 왜 (2026-08-13 라이브 무신사)
   1~60쪽으로 시켜 **1,204개를 전부** 걷었다. 21쪽이 마지막이고 22쪽은 0개였다.
   그런데 화면의 「더 있음」이 **켜져** 있었다.

   무신사는 **마지막 쪽 뒤에도 `nextPageUrl` 을 계속 준다.** 그래서 0개짜리 쪽에서
   빠져나와도 `url` 이 남아 있고, 아래의 `if (url) capped = true` 가 켜 버린다.

★★ **「덜 걷고 끝났다 하기」와 「다 걷고 더 있다 하기」는 둘 다 거짓말이다.**
   앞의 것은 사장님이 없는 상품을 없다고 믿게 하고,
   뒤의 것은 있지도 않은 상품을 찾아 쪽 수를 계속 늘리게 만든다.

★ 판정 기준 — **한 개도 없는 쪽이 나왔으면 끝난 것이다.** 소싱처가 다음 쪽 주소를
  계속 주더라도, 그 쪽에 상품이 없으면 더 걸을 것이 없다.
"""
from __future__ import annotations

import re
from pathlib import Path

BG = (Path(__file__).resolve().parents[2]
      / 'extension' / 'moum-crawler' / 'background.js')


def _next_url_block() -> str:
    """다음 쪽 주소를 따라가는 부분(무신사 경로)."""
    src = BG.read_text(encoding='utf-8')
    m = re.search(r'  if \(nextUrlRe\) \{.*?\n  \}', src, re.S)
    assert m, ('다음 쪽 주소를 따라가는 부분을 못 찾았습니다. 구조가 바뀌었다면 '
               '이 시험도 같이 고쳐야 합니다 — 못 찾은 채 통과하면 아무것도 안 봅니다.')
    return m.group(0)


def test_따라가는_부분을_찾는다():
    body = _next_url_block()
    assert 'capped' in body and 'fetch(url' in body


def test_한_개도_없는_쪽이_나오면_다음쪽을_버린다():
    """🔴 이 파일의 핵심 — `url` 을 비우지 않으면 「더 있음」이 켜진다."""
    body = _next_url_block()
    assert re.search(r'if \(!n\) \{ url = null; break; \}', body), (
        '한 개도 없는 쪽에서 빠져나올 때 다음 쪽 주소를 안 버립니다. '
        '그러면 다 걷고도 「더 있음」이 켜져, 있지도 않은 상품을 찾아 '
        '쪽 수를 계속 늘리게 됩니다.'
    )


def test_진짜로_남았을_때는_여전히_더있음이다():
    """반대쪽도 지킨다 — 다음 쪽이 실제로 남아 있으면 「더 있음」이어야 한다."""
    body = _next_url_block()
    assert re.search(r'if \(url\) capped = true;', body), (
        '남은 쪽이 있는데 「더 있음」을 안 켜면, 덜 걷고 「끝남」이라 말하게 됩니다.'
    )


def test_다음쪽을_못_찾은_경우도_그대로다():
    """여러 쪽을 시켰는데 첫 쪽에서 주소를 못 찾은 것은 여전히 「다 못 봤다」."""
    body = _next_url_block()
    assert re.search(r'if \(want > 1 && !url\) capped = true;', body), (
        '다음 쪽 주소를 아예 못 찾은 경우를 「더 있음」으로 안 말하면 '
        '무신사 47개 사고가 그대로 재발합니다.'
    )
