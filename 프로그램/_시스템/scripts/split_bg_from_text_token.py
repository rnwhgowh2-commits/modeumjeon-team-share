# -*- coding: utf-8 -*-
"""글자색 이름을 **배경**으로 쓴 자리에 배경용 이름을 앞에 끼운다.

무슨 문제였나
  `--ink` 는 「글자색」 이름이다. 어두운 화면에서 밝은 값(#F5F5F7)으로 **뒤집히도록**
  설계돼 있다. 그런데 `background: var(--ink)` 처럼 배경으로 쓴 자리가 61곳 있었다.
  그러면 흰 글자 위에 거의 흰 배경이 겹친다.

  라이브 실측: 마진계산기 「분석 시작」 단추 — 흰 글자에 배경 #F5F5F7, 대비 **1.09**.
  사장님이 「안 보인다」고 보내주신 화면이 이것이다.

    background:var(--ink,#191F28) → background: var(--바탕-진하게, var(--ink,#191F28))

  「기존 타입」에는 `--바탕-진하게` 도 `--ink` 도 없어 맨 안쪽 원래값으로 떨어진다
  — 즉 안전망 타입은 **한 픽셀도 안 바뀐다**.

🔴 정규식은 `[^;{}]*` 로 규칙 경계를 막는다.
   `[^;]*` 로 뒀다가 CSS 를 통째로 깨뜨린 사고가 있었다(2026-08-01).
   바꾼 뒤에는 반드시 scripts/check_css_balanced.py 로 확인한다.

쓰는 법
  python scripts/split_bg_from_text_token.py          # 바꾼다
  python scripts/split_bg_from_text_token.py --확인    # 남은 자리만 본다
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

_건너뛸파일 = ('tokens.css', 'dark_scope_fix.css', 'dark_badge_fix.css',
               'inline_color_fix.css', 'margin_embed_ds.css',
               # 생성 파일 — 빌드가 같은 처리를 한다(tools/build_margin_embed.py)
               'margin_embed.html')

# 글자용 이름 → 배경으로 쓸 때의 이름
_짝 = {
    'ink': '--바탕-진하게', '글자-진하게': '--바탕-진하게', '글자-기본': '--바탕-진하게',
    'sub': '--바탕-흐리게', 'faint': '--바탕-흐리게',
    '글자-보조': '--바탕-흐리게', '글자-희미': '--바탕-흐리게',
}
_이름들 = '|'.join(re.escape(k) for k in sorted(_짝, key=len, reverse=True))

_규칙 = re.compile(
    r'(background(?:-color)?)\s*:\s*(var\(\s*--(' + _이름들 + r')\b[^;{}]*\))')


def _바꾸기(글: str):
    """(바뀐 글, 바꾼 수). 이미 배경용 이름이 끼워진 자리는 건드리지 않는다."""
    바뀜 = [0]

    def sub(m):
        속성, 값, 옛이름 = m.group(1), m.group(2), m.group(3)
        새이름 = _짝[옛이름]
        if 새이름 in 값:
            return m.group(0)
        바뀜[0] += 1
        return '%s: var(%s, %s)' % (속성, 새이름, 값)

    글, n1 = _규칙.sub(sub, 글), 바뀜[0]
    글, n2 = _강조배경_가르기(글)
    return 글, n1 + n2


# ── 강조색 배경 + 흰 글자 ───────────────────────────────────────────────
#  `--primary`·`--blue` 는 어두운 화면에서 **밝은 파랑(#2997FF)** 으로 뒤집힌다.
#  링크 글자로는 그게 맞지만, 그 위에 흰 글자를 얹으면 대비 3.02 로 떨어진다
#  (라이브 실측: 모음전 상품의 선택된 줄 「전체」·개수 배지).
#
#  ★ 배경만 보고 바꾸면 어두운 글자를 얹은 자리까지 망가진다.
#    그래서 **같은 규칙 덩어리 안에 흰 글자가 함께 적혀 있을 때만** 바꾼다.
_강조배경 = re.compile(
    r'(background(?:-color)?)\s*:\s*(var\(\s*--(primary|blue|sky|green|red|amber)\b[^;{}]*\))')
_흰글자 = re.compile(r'(?<![-\w])color\s*:\s*(?:#fff(?:fff)?|white)\b', re.IGNORECASE)
_덩어리 = re.compile(r'\{[^{}]*\}')
_강조짝 = {'primary': '--바탕-파랑', 'blue': '--바탕-파랑', 'sky': '--바탕-파랑',
           'green': '--바탕-초록', 'red': '--바탕-빨강', 'amber': '--바탕-주황'}


def _강조배경_가르기(글: str):
    """규칙 덩어리 `{...}` 안에 흰 글자가 함께 있을 때만 배경을 어둡게 돌린다."""
    수 = [0]

    def 덩어리처리(m):
        본문 = m.group(0)
        if not _흰글자.search(본문):
            return 본문

        def sub(mm):
            속성, 값, 이름 = mm.group(1), mm.group(2), mm.group(3)
            새 = _강조짝[이름]
            if 새 in 값:
                return mm.group(0)
            수[0] += 1
            return '%s: var(%s, %s)' % (속성, 새, 값)

        return _강조배경.sub(sub, 본문)

    return _덩어리.sub(덩어리처리, 글), 수[0]


def 대상파일():
    for root, _dirs, files in os.walk(_웹앱):
        for f in sorted(files):
            if f.endswith(('.html', '.css')) and f not in _건너뛸파일:
                yield os.path.join(root, f)


def main() -> int:
    확인만 = '--확인' in sys.argv
    총 = 파일수 = 0
    남은곳 = []
    for p in 대상파일():
        s = io.open(p, encoding='utf-8', errors='replace').read()
        새, n = _바꾸기(s)
        if not n:
            continue
        총 += n
        파일수 += 1
        rel = os.path.relpath(p, _시스템).replace(os.sep, '/')
        if 확인만:
            남은곳.append((rel, n))
        else:
            io.open(p, 'w', encoding='utf-8', newline='').write(새)
            print('%5d곳  %s' % (n, rel))
    if 확인만:
        if 남은곳:
            print('아직 배경용 이름으로 안 바꾼 자리 %d곳 / %d파일' % (총, 파일수))
            for rel, n in sorted(남은곳, key=lambda t: -t[1])[:15]:
                print('   %5d %s' % (n, rel))
            return 1
        print('전부 배경용 이름으로 갈라져 있습니다.')
        return 0
    print('합계 %d곳 / %d파일' % (총, 파일수))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
