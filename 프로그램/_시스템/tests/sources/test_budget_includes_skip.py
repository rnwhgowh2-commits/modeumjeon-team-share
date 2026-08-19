# -*- coding: utf-8 -*-
"""**건너뛸 쪽도 시간 예산에 넣는다** — 안 그러면 이어걷기가 그 자리에서 굳는다.

🔴🔴 왜
   「다음」 단추 소싱처는 이어서 걸으려면 **눌러서 건너뛴다**. 121쪽부터 걸으려면
   120번을 눌러야 한다. 이어걷기가 깊어질수록 이 횟수가 계속 늘어난다.

   그런데 시간 예산이 **걷는 몫만** 세면 어떻게 되나 —
     ① 건너뛰다 시한이 끝난다
     ② 한 건도 못 걷는다
     ③ 「새로 걷은 것 0」이 된다
     ④ **자동 이어걷기가 멈춘다**(0이면 멈추는 것이 안전장치다)
   → 앞으로 나아가지 못하고 **그 자리에서 굳는다.**

★ 안전장치(「0이면 멈춘다」)는 그대로 두어야 한다 — 그게 없으면 소싱처를 영원히
  두들긴다. 대신 **예산을 정직하게 잡아** 건너뛰기가 예산을 다 먹지 않게 한다.

★ 건너뛰기는 훑지 않아 걷기보다 빠르다 → 쪽당 3초(걷기는 6초).
"""
from __future__ import annotations

import re
from pathlib import Path

BG = (Path(__file__).resolve().parents[2]
      / 'extension' / 'moum-crawler' / 'background.js')


def _budget_src() -> str:
    src = BG.read_text(encoding='utf-8')
    m = re.search(r'const _skipN = .*?;\s*\n\s*const budget = .*?;', src, re.S)
    assert m, ('시간 예산을 잡는 곳을 못 찾았습니다. 구조가 바뀌었다면 이 시험도 '
               '같이 고쳐야 합니다.')
    return m.group(0)


def test_예산에_건너뛸_쪽이_들어간다():
    """🔴 이 파일의 핵심 — 이게 없으면 깊어질수록 못 나아간다."""
    body = _budget_src()
    assert 'rule.click_skip' in body, (
        '건너뛸 횟수를 예산에 안 넣습니다 — 건너뛰다 시한이 끝나 한 건도 못 걷고, '
        '「새로 걷은 것 0」이라 자동 이어걷기가 그 자리에서 멈춥니다.'
    )
    assert re.search(r'_skipN \* 3000', body), '건너뛸 쪽마다 시간을 안 더합니다.'


def test_걷는_몫도_그대로_있다():
    """건너뛰기만 세고 걷는 몫을 빼면 반대로 걷다가 잘린다."""
    body = _budget_src()
    assert re.search(r'\(Number\(rule\.click_pages\) \|\| 1\) - 1\) \* 6000', body)


def test_건너뛰기가_걷기보다_싸게_잡힌다():
    """훑지 않으니 더 빠르다 — 같은 값으로 잡으면 예산이 쓸데없이 커진다."""
    body = _budget_src()
    walk = int(re.search(r'- 1\) \* (\d+)', body).group(1))
    skip = int(re.search(r'_skipN \* (\d+)', body).group(1))
    assert skip < walk, f'건너뛰기({skip}) 가 걷기({walk}) 보다 싸야 합니다.'


def test_숫자로_확인한다():
    """실제 값으로 계산해 본다 — 121쪽부터 60쪽을 걸을 때."""
    body = _budget_src()
    base = int(re.search(r'const budget = (\d+)', body).group(1))
    walk = int(re.search(r'- 1\) \* (\d+)', body).group(1))
    skip = int(re.search(r'_skipN \* (\d+)', body).group(1))
    got = base + (60 - 1) * walk + 120 * skip
    # 건너뛰기 120번(약 6분) + 걷기 60쪽(약 6분)을 담을 수 있어야 한다.
    assert got >= 120 * 3000 + 60 * 3000, (
        f'예산 {got}ms 로는 120번 건너뛰고 60쪽을 걷기에 모자랍니다.'
    )
