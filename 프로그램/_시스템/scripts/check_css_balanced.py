# -*- coding: utf-8 -*-
"""CSS 괄호가 짝이 맞는지 검사한다 — 안 맞으면 그 뒤 규칙이 통째로 죽는다.

왜 필요한가 (2026-08-01 실제 사고)
    색을 토큰으로 바꾸는 치환이 `}` 를 넘어가 다음 규칙까지 삼켰다.

        고치기 전 : .mj-ar{color:var(--faint,#9ca3af)}
                    .mj-brand{border:1px solid var(--faint,#d1d6db);
        망가진 뒤 : .mj-ar{color: var(--글자-희미, var(--faint,#9ca3af)}
                    .mj-brand{border:1px solid var(--faint,#d1d6db));

    브라우저는 이런 자리를 만나면 **그 뒤 스타일을 통째로 버린다.**
    마진계산기에서 <style> 은 50,506자인데 규칙이 112개만 살아남았고,
    `.bfix-*`(브랜드 정리 팝업) 규칙이 0개가 되어 팝업이 날것으로 쏟아졌다.

    테스트 472개가 전부 통과했는데도 못 잡았다 — 글자만 비교했지
    **CSS 로서 말이 되는지**는 아무도 안 봤기 때문이다. 그래서 이 검사를 만든다.

무엇을 보나
    <style> 블록과 .css 파일에서
      ① `var(` 의 짝이 `{` 나 `}` 를 만나기 전에 닫히는가
      ② 블록 `{}` 짝이 맞는가
    Jinja 태그({{ }}, {% %})는 CSS 가 아니므로 먼저 걷어낸다.

쓰는 법
    python scripts/check_css_balanced.py          # 전체 검사(문제 있으면 종료코드 1)
    python scripts/check_css_balanced.py --고침    # 삼켜진 자리를 되돌린다
"""
from __future__ import annotations

import argparse
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

_STYLE_BLOCK = re.compile(r'(<style[^>]*>)(.*?)(</style>)', re.S | re.I)
_JINJA = re.compile(r'\{\{.*?\}\}|\{%.*?%\}', re.S)

# 삼켜진 자리를 되돌릴 때 찾는 머리말 — 치환기가 내놓는 모양 그대로다
# (scripts/split_*.py 의 `'color: var(%s, %s);'`).
_머리말 = re.compile(r'(?<![-\w])color:\s*var\(\s*(--글자-[가-힣]+)\s*,\s*')


def _지빈다(css: str) -> str:
    """Jinja 태그를 같은 길이의 공백으로 바꿔 위치를 보존한 채 걷어낸다."""
    return _JINJA.sub(lambda m: ' ' * (m.end() - m.start()), css)


def 문제찾기(css: str) -> list[tuple[int, str]]:
    """(위치, 무엇이 문제인지) 목록. 빈 목록이면 정상."""
    글 = _지빈다(css)
    문제 = []
    깊이 = 0
    i = 0
    n = len(글)
    while i < n:
        c = 글[i]
        # 🔴 [2026-08-02] 설명글(주석) 짝 — 이걸 안 보다가 실제로 규칙을 죽였다.
        #   설명을 고치다 닫는 표시 `*/` 를 하나 더 남겼더니, 그 앞의 한국어 설명이
        #   **CSS 선택자로 새어 나와** 바로 뒤 규칙을 통째로 삼켰다(중괄호 짝은
        #   멀쩡해서 기존 검사는 전부 통과했다 — 라이브였으면 못 잡았다).
        #   ① 안 닫힌 `/*`  ② 짝 없는 `*/`  둘 다 여기서 걸린다.
        #   ★ 주석 안쪽은 CSS 가 아니므로 통째로 건너뛴다(그 안의 `{`·`(` 는 글자다).
        if c == '/' and 글.startswith('/*', i):
            끝 = 글.find('*/', i + 2)
            if 끝 == -1:
                문제.append((i, '설명글(주석)이 안 닫혔다 — 그 뒤 스타일이 통째로 죽는다: '
                             + 글[i:i + 60].replace('\n', ' ')))
                break
            i = 끝 + 2
            continue
        if c == '*' and 글.startswith('*/', i):
            문제.append((i, '짝 없는 주석 닫힘 표시 — 그 앞 설명글이 CSS 로 새어 나온다: '
                         + 글[max(0, i - 60):i + 2].replace('\n', ' ')))
            i += 2
            continue
        # 따옴표 안은 CSS 문법이 아니라 **글자**다.
        # `[style*="color:var(--green" i]` 같은 선택자를 규칙으로 오인하면 안 된다.
        if c in '"\'':
            끝 = 글.find(c, i + 1)
            i = (끝 + 1) if 끝 != -1 else n
            continue
        if c == 'v' and 글.startswith('var(', i):
            # 이 var( 가 { 나 } 를 만나기 전에 닫히는지 본다
            안깊이 = 0
            j = i + 3
            닫힘 = False
            while j < n:
                d = 글[j]
                if d == '(':
                    안깊이 += 1
                elif d == ')':
                    안깊이 -= 1
                    if 안깊이 == 0:
                        닫힘 = True
                        break
                elif d in '{}':
                    break          # 규칙 경계를 넘었다 = 짝이 안 맞는다
                j += 1
            if not 닫힘:
                문제.append((i, 'var( 가 규칙 경계를 넘어 안 닫힘: ' + 글[i:i + 90].replace('\n', ' ')))
                i += 4
                continue
            i = j + 1
            continue
        if c == '{':
            깊이 += 1
        elif c == '}':
            깊이 -= 1
            if 깊이 < 0:
                문제.append((i, '닫는 중괄호가 더 많다'))
                깊이 = 0
        i += 1
    if 깊이 != 0:
        문제.append((len(글), '중괄호 짝이 안 맞는다(%+d)' % 깊이))
    return 문제


def 고치기(css: str) -> tuple[str, int]:
    """삼켜진 자리만 원래대로 되돌린다.

    `color: var(--새이름, <삼킨내용>);`  →  `color:<삼킨내용>;`
    (감싸기 전 모습으로 돌아간다. 고친 뒤 올바른 도구로 다시 감싸면 된다.)

    🔴 정규식으로 되돌리려다 **멀쩡한 자리까지 건드렸다**(33곳 문제인데 40곳 수정).
       그래서 여기서는 정규식 대신 **괄호를 하나씩 세어** 짝을 찾는다.
       삼킨 자리(괄호 안에 `{`·`}` 가 있는 것)만 되돌리고 나머지는 손대지 않는다.
    """
    수 = 0
    결과 = []
    자리 = 0
    while True:
        m = _머리말.search(css, 자리)
        if not m:
            결과.append(css[자리:])
            break
        # `var(` 의 짝을 센다 — 머리말 끝은 이미 var( 안쪽이므로 깊이 1 에서 시작
        깊이 = 1
        j = m.end()
        삼킴 = False
        while j < len(css) and 깊이:
            c = css[j]
            if c == '(':
                깊이 += 1
            elif c == ')':
                깊이 -= 1
            elif c in '{}':
                삼킴 = True
            j += 1
        # `);` 형태여야 우리가 만든 자리다
        끝 = j
        while 끝 < len(css) and css[끝] in ' \t':
            끝 += 1
        if 깊이 or 끝 >= len(css) or css[끝] != ';' or not 삼킴:
            결과.append(css[자리:m.end()])     # 멀쩡한 자리 — 그대로 둔다
            자리 = m.end()
            continue
        안쪽 = css[m.end():j - 1]              # 마지막 ')' 를 뺀 내용
        결과.append(css[자리:m.start()])
        결과.append('color:' + 안쪽 + ';')
        자리 = 끝 + 1
        수 += 1
    return ''.join(결과), 수


def _대상():
    for root, _d, files in os.walk(_웹앱):
        for f in sorted(files):
            if f.endswith(('.html', '.css')):
                yield os.path.join(root, f)


def _파일처리(p: str, 고침: bool):
    글 = io.open(p, encoding='utf-8', errors='replace').read()
    조각 = []
    if p.endswith('.css'):
        조각 = [(0, 글)]
    else:
        조각 = [(m.start(2), m.group(2)) for m in _STYLE_BLOCK.finditer(글)]
    문제수 = sum(len(문제찾기(c)) for _s, c in 조각)
    고친수 = 0
    if 고침 and 문제수:
        if p.endswith('.css'):
            새글, 고친수 = 고치기(글)
        else:
            def 블록(m):
                nonlocal 고친수
                새내용, n = 고치기(m.group(2))
                고친수 += n
                return m.group(1) + 새내용 + m.group(3)
            새글 = _STYLE_BLOCK.sub(블록, 글)
        if 새글 != 글:
            io.open(p, 'w', encoding='utf-8', newline='').write(새글)
    return 문제수, 고친수


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--고침', action='store_true', help='삼켜진 자리를 되돌린다')
    a = ap.parse_args()

    총문제 = 0
    총고침 = 0
    나쁜파일 = []
    for p in _대상():
        문제수, 고친수 = _파일처리(p, a.고침)
        총문제 += 문제수
        총고침 += 고친수
        if 문제수:
            나쁜파일.append((os.path.relpath(p, _시스템).replace(os.sep, '/'), 문제수))
    if a.고침:
        print('되돌린 자리 %d곳' % 총고침)
        # 고친 뒤 다시 검사
        남음 = sum(_파일처리(p, False)[0] for p in _대상())
        print('아직 남은 문제 %d곳' % 남음)
        return 1 if 남음 else 0

    print('괄호가 안 맞는 자리 %d곳 / %d파일' % (총문제, len(나쁜파일)))
    for rel, n in sorted(나쁜파일, key=lambda t: -t[1])[:20]:
        print('%5d %s' % (n, rel))
    return 1 if 총문제 else 0


if __name__ == '__main__':
    raise SystemExit(main())
