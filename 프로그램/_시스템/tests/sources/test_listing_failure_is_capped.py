# -*- coding: utf-8 -*-
"""한 장이 **실패하면 「다 못 봤다」**고 말한다 — 「끝남」이 아니라.

🔴🔴 왜 이 시험이 있나 (2026-08-12 라이브)
   롯데온·롯데아이몰을 1~60쪽으로 시켰더니 「훑는 중 시간 초과」가 났는데,
   화면의 「더 있음」은 **꺼진 채**였다. 즉 사유는 적혔는데 상태는 「끝남」이었다.

   그러면 사장님은 **「이 검색엔 289개뿐」**이라고 믿는다.
   사유를 적는 것과 **「다 못 봤다」고 말하는 것은 다른 일이다.**

★ 이 파일은 확장 소스를 **글자로** 본다. 확장은 크롬 안에서만 도는 코드라
  파이썬에서 실행할 수 없다 — 대신 「이 줄이 사라지면 알아챈다」를 목표로 한다.
  (주소 푸는 식처럼 **돌려 볼 수 있는 것**은 node 로 돌린다 —
   `test_musinsa_next_url_unescape.py` 참조.)
"""
from __future__ import annotations

import re
from pathlib import Path

BG = (Path(__file__).resolve().parents[2]
      / 'extension' / 'moum-crawler' / 'background.js')


def _scan_loop() -> str:
    """훑기 결과를 모으는 for 문 — 여기서 실패를 어떻게 다루는지가 핵심."""
    src = BG.read_text(encoding='utf-8')
    m = re.search(r'for \(const pageUrl of \(rule \? \(job\.page_urls.*?\n      \}',
                  src, re.S)
    assert m, ('background.js 에서 훑기 for 문을 못 찾았습니다. 구조가 바뀌었다면 '
               '이 시험도 같이 고쳐야 합니다 — 못 찾은 채 통과하면 아무것도 안 봅니다.')
    return m.group(0)


def test_훑기_for문을_찾는다():
    body = _scan_loop()
    assert '_listingScanOnePage' in body, '엉뚱한 곳을 잡았습니다.'


def test_한_장이_실패하면_더있음을_켠다():
    """🔴 이 파일의 핵심."""
    body = _scan_loop()
    m = re.search(r'\} catch \(e\) \{(.*?)\n        \}', body, re.S)
    assert m, '실패를 받는 catch 를 못 찾았습니다.'
    catch_body = m.group(1)
    assert 'err' in catch_body, '실패 사유를 안 남기고 있습니다.'
    assert re.search(r'capped\s*=\s*true', catch_body), (
        '한 장이 실패했는데 「더 있음(capped)」을 안 켭니다. '
        '사유만 적고 상태는 「끝남」이면, 사장님은 덜 걷은 수를 전부라고 믿습니다.'
    )


def test_시간초과도_같은_길로_들어온다():
    """「훑는 중 시간 초과」는 예외로 던져져 위 catch 로 들어와야 한다."""
    src = BG.read_text(encoding='utf-8')
    assert '훑는 중 시간 초과' in src
    assert re.search(r'rej\(new Error\("훑는 중 시간 초과"\)\)', src), (
        '시간 초과가 예외로 던져지지 않으면 위 catch 를 안 타 「더 있음」이 안 켜집니다.'
    )
