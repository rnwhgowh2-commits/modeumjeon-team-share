# -*- coding: utf-8 -*-
"""의미색(초록·빨강·주황·파랑)을 「글자용」과 「나머지」로 가른다.

무슨 문제였나 — 이름 하나가 세 가지 일을 하고 있었다
  같은 `--green`(#34C759) 이
    ① 밝은 바탕 위 글자   흰 바탕 2.22 · 옅은 초록 바탕 2.05   ← 안 읽힘
    ② 검정 바탕 위 글자   9.46 · 7.45                          ← 괜찮음
    ③ 흰 글자를 얹는 배경 2.22                                 ← 안 읽힘
  ①③은 어두워야 하고 ②는 밝아야 한다 — **한 값으로는 불가능하다.**
  `--faint` 를 「글자용」과 「테두리용」으로 갈랐던 것과 똑같은 처방을 쓴다.

    color: var(--green,#16A34A)  →  color: var(--글자-초록, var(--green,#16A34A))

  「기존 타입」에는 `--글자-초록` 이 없으므로 괄호 안 원래값으로 그대로 떨어진다
  — 즉 안전망 타입은 **한 픽셀도 안 바뀐다**.

  ★ 배경으로 쓴 자리는 **안 건드린다**. 배경은 위에 얹힌 글자가 흰색일 때만
    어두워야 하는데, 그 판단은 CSS 선택자 두 개를 겹쳐서 한다
    (scripts/gen_inline_color_fix.py 의 「흰 글자를 얹은 색 배경」).

쓰는 법
  python scripts/split_semantic_text.py           # 바꾼다
  python scripts/split_semantic_text.py --확인     # 안 바뀐 자리가 남았는지만 본다
"""
from __future__ import annotations

import io
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

_시스템 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_웹앱 = os.path.join(_시스템, 'webapp')

# 색 값의 단일 원천이라 여기서 자기 자신을 다시 감싸면 순환이 된다 → 건너뛴다.
_건너뛸파일 = ('tokens.css', 'dark_scope_fix.css', 'dark_badge_fix.css',
               'inline_color_fix.css', 'margin_embed_ds.css',
               # 생성 파일 — 손대면 동치 가드가 깨진다. 빌드가 같은 처리를 한다
               # (tools/build_margin_embed.py).
               'margin_embed.html')

# 옛 이름 → 글자용 새 이름
_짝 = {
    'green': '--글자-초록', 'color-ok': '--글자-초록',
    'red': '--글자-빨강', 'danger': '--글자-빨강',
    'amber': '--글자-주황', 'warning': '--글자-주황',
    'blue': '--글자-파랑', 'sky': '--글자-파랑', 'primary': '--글자-파랑',
}

# `color: var(--green …);` 만 잡는다.
#   (?<![-\w]) — `background-color:` 의 뒷부분에 걸리지 않게 앞을 막는다.
#   [^;]*      — 예비값(중첩 var 포함)을 통째로 안고 간다.
_규칙 = re.compile(
    r'(?<![-\w])color\s*:\s*(var\(\s*--(' + '|'.join(map(re.escape, _짝)) + r')\b[^;{}]*\))\s*(?=[;}])')

# ── 굳은 옅은 회색이 「글자」로 쓰인 자리 ────────────────────────────────
#  색표(COLOR_MAP)에 넣어 통째로 바꾸면 **테두리까지** 어두워진다 — 테두리는
#  옅은 게 맞다. 그래서 `color:` 선언일 때만, 여기서 따로 바꾼다.
#  라이브 실측(화이트 타입): #D2D2D7 글자 1.51 · #86868B 3.62 · #8B95A1 3.04
_옅은회색 = ('d2d2d7', 'cbccd3', 'b0b8c1', '86868b', '8b95a1', '8f91a0', '9ca3af')
_회색규칙 = re.compile(
    r'(?<![-\w])color\s*:\s*(#(?:' + '|'.join(_옅은회색) + r'))(?![0-9a-zA-Z_-])\s*(?=[;}])',
    re.IGNORECASE)


# ── 배경용 이름이 「글자색」으로 쓰인 자리 ────────────────────────────────
#  `--line`·`--n400`·`--연한-빨강` 은 **선이나 옅은 판**을 위한 이름이다.
#  글자색으로 쓰면 어두운 화면에서 거의 안 보인다
#  (실측: `rgba(255,59,48,.18)` 글자 — 대비 1.2).
_배경이름_글자 = {
    'line': '--글자-희미', 'line2': '--글자-희미',
    'n200': '--글자-희미', 'n300': '--글자-희미', 'n400': '--글자-희미',
    '연한-파랑': '--글자-파랑', '연한-빨강': '--글자-빨강',
    '연한-초록': '--글자-초록', '연한-주황': '--글자-주황',
}
_배경이름들 = '|'.join(re.escape(k) for k in sorted(_배경이름_글자, key=len, reverse=True))
_배경이름규칙 = re.compile(
    r'(?<![-\w])color\s*:\s*(var\(\s*--(' + _배경이름들 + r')\b[^;{}]*\))\s*(?=[;}])')


def _바꾸기(글: str):
    """(바뀐 글, 바꾼 수). 이미 새 이름이 끼워진 자리는 건드리지 않는다."""
    바뀜 = [0]

    def sub(m):
        값, 옛이름 = m.group(1), m.group(2)
        새이름 = _짝[옛이름]
        if 새이름 in 값:
            return m.group(0)
        바뀜[0] += 1
        return 'color: var(%s, %s)' % (새이름, 값)

    글 = _규칙.sub(sub, 글)

    def sub회색(m):
        바뀜[0] += 1
        return 'color: var(--글자-희미, %s)' % m.group(1)

    글 = _회색규칙.sub(sub회색, 글)

    def sub배경이름(m):
        값, 옛 = m.group(1), m.group(2)
        새 = _배경이름_글자[옛]
        if 새 in 값:
            return m.group(0)
        바뀜[0] += 1
        return 'color: var(%s, %s)' % (새, 값)

    return _배경이름규칙.sub(sub배경이름, 글), 바뀜[0]


def 대상파일():
    for root, _dirs, files in os.walk(_웹앱):
        for f in sorted(files):
            if not f.endswith(('.html', '.css')):
                continue
            if f in _건너뛸파일:
                continue
            yield os.path.join(root, f)


def main() -> int:
    확인만 = '--확인' in sys.argv
    총 = 0
    파일수 = 0
    남은곳 = []
    for p in 대상파일():
        s = io.open(p, encoding='utf-8', errors='replace').read()
        새, n = _바꾸기(s)
        if not n:
            continue
        총 += n
        파일수 += 1
        rel = os.path.relpath(p, _시스템).replace('\\', '/')
        if 확인만:
            남은곳.append((rel, n))
        else:
            io.open(p, 'w', encoding='utf-8', newline='').write(새)
            print('%5d곳  %s' % (n, rel))
    if 확인만:
        if 남은곳:
            print('아직 글자용 이름으로 안 바꾼 자리 %d곳 / %d파일' % (총, 파일수))
            for rel, n in sorted(남은곳, key=lambda t: -t[1])[:15]:
                print('   %5d %s' % (n, rel))
            return 1
        print('전부 글자용 이름으로 갈라져 있습니다.')
        return 0
    print('합계 %d곳 / %d파일' % (총, 파일수))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
