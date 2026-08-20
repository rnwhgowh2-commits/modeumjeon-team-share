# -*- coding: utf-8 -*-
"""`--faint` 를 「글자용」과 「테두리용」으로 가른다.

무슨 문제였나
  한 이름(`--faint`)이 두 가지 일을 하고 있었다 — 글자색 204번, 테두리 37번.
  글자로 쓰기엔 너무 연해서(흰 바탕 위 2.01) 어둡게 해야 하는데, 그러면 테두리가
  시커멓게 변한다. 그래서 **글자로 쓰던 자리에만** 새 이름을 앞에 끼운다.

    color: var(--faint,#B0B8C1)   →   color: var(--글자-희미, var(--faint,#B0B8C1))

  「현재」 모드에는 `--글자-희미` 가 없으므로 괄호 안 원래값으로 그대로 떨어진다
  — 즉 안전망 모드는 **한 픽셀도 안 바뀐다**. 새 디자인 모드에서만 읽히는 색이 된다.

쓰는 법
  python scripts/split_faint_text.py           # 바꾼다
  python scripts/split_faint_text.py --check   # 안 바뀐 자리가 남았는지만 본다(테스트가 씀)
"""
from __future__ import annotations

import io
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEBAPP = os.path.join(HERE, 'webapp')
SKIP = ('tokens.css', 'dark_scope_fix.css', 'dark_badge_fix.css')

새이름 = '--글자-희미'
# `color: var(--faint …);` 만 잡는다. 테두리·배경은 손대지 않는다.
# ★ 끝을 `;` 로만 보면 `.x{color:var(--faint,#D2D2D7)}` 처럼 `}` 로 끝나는 선언을
#   통째로 놓친다(실측 708곳). 끝은 **들여다보기만** 하고 소비하지 않는다.
_PAT = re.compile(r'(?<![-\w])color\s*:\s*(var\(\s*--faint[^;{}]*\))\s*(?=[;}])')


def _바꾸기(text: str):
    """(바뀐 글, 바꾼 수). 이미 새 이름이 끼워진 자리는 건드리지 않는다."""
    바뀜 = [0]

    def sub(m):
        값 = m.group(1)
        if 새이름 in 값:
            return m.group(0)
        바뀜[0] += 1
        return 'color: var(%s, %s)' % (새이름, 값)

    return _PAT.sub(sub, text), 바뀜[0]


def 대상파일():
    for root, _dirs, files in os.walk(WEBAPP):
        for f in sorted(files):
            if f.endswith(('.html', '.css')) and f not in SKIP:
                yield os.path.join(root, f)


def main() -> int:
    확인만 = '--check' in sys.argv
    총, 파일수, 남은 = 0, 0, []
    for p in 대상파일():
        try:
            t = io.open(p, encoding='utf-8').read()
        except OSError:
            continue
        새글, n = _바꾸기(t)
        if not n:
            continue
        총 += n
        파일수 += 1
        if 확인만:
            남은.append((os.path.relpath(p, WEBAPP), n))
        else:
            io.open(p, 'w', encoding='utf-8').write(새글)
    if 확인만:
        if 남은:
            print('아직 안 바꾼 자리 %d곳 · %d개 파일' % (총, len(남은)))
            for p, n in 남은[:10]:
                print('   %3d  %s' % (n, p))
            return 1
        print('모두 바뀌어 있다')
        return 0
    print('바꾼 자리 %d곳 · %d개 파일' % (총, 파일수))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
