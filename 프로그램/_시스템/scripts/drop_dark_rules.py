# -*- coding: utf-8 -*-
"""어두운 타입 전용 규칙만 걷어낸다 — 화이트는 한 글자도 안 건드린다.

[2026-08-02 사장님 확정] 화이트만 남기고 기존·검정A·검정B 를 코드까지 지운다.

왜 손으로 안 지우나
    어두운 전용 규칙이 65개다. 손으로 지우면 반드시 하나를 잘못 건드린다.

🔴 만들면서 두 번 헛디뎠다 — 둘 다 「단순히 자르면 된다」는 착각이었다
    ① **선택자 사이에 설명글이 끼어 있다.**
         .ds.ds-dark .a,     /* 매트릭스 「원본」 173곳 */
         .ds.ds-dark .b { … }
       주석을 기준으로 조각내 훑었더니 선택자가 두 동강 나서 못 알아봤다.
       → 주석을 **같은 길이의 공백으로 가려** 위치를 보존한 채 훑는다.
    ② **괄호 안에도 쉼표가 있다.**
         :where(.ds.ds-dark) :where(option, optgroup) { … }
       쉼표로 무작정 가르면 `:where(option` / ` optgroup)` 로 쪼개져,
       한쪽만 남기는 순간 **문법이 깨진 CSS** 가 만들어진다.
       → 괄호 밖 쉼표에서만 가른다.

★ 지우고 나면 반드시 확인한다 — 어두운 표시가 규칙에 남았는지, 괄호·주석 짝이
  맞는지, 그리고 **화이트 화면 지문이 그대로인지**(scripts/white_fingerprint.py).

쓰는 법
    python scripts/drop_dark_rules.py            # 미리보기
    python scripts/drop_dark_rules.py --쓰기      # 실제로 지움
"""
from __future__ import annotations

import argparse
import io
import pathlib
import re
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

_정적 = pathlib.Path(__file__).resolve().parents[1] / 'webapp' / 'static'

# 어두운 타입을 가리키는 표시. 하나라도 들어 있으면 그 선택자는 어두운 전용이다.
_어두운표시 = re.compile(r'ds-dark|ds-mono|ds-layer')

_대상 = ['tokens.css', 'dark_scope_fix.css', 'dark_badge_fix.css',
         'margin_embed_ds.css', 'badge_bg_fix.css', 'toss.css',
         'sidebar_edit.css', 'topnav.css', 'airy.css', 'modal_resize.css']


def _주석가리기(css: str) -> str:
    """주석을 같은 길이의 공백으로 바꾼다 — 위치가 보존되므로 원본을 그대로 자를 수 있다."""
    나옴 = list(css)
    i = 0
    while True:
        j = css.find('/*', i)
        if j == -1:
            break
        k = css.find('*/', j + 2)
        k = len(css) if k == -1 else k + 2
        for x in range(j, k):
            if 나옴[x] != '\n':
                나옴[x] = ' '
        i = k
    return ''.join(나옴)


def _가를자리(선택자_가린: str) -> list[int]:
    """가를 쉼표의 **자리**를 돌려준다 (`:where(a, b)` 안의 쉼표는 건너뛴다).

    🔴 자리로 돌려주는 이유 — 원본과 가린 것을 각각 쉼표로 가르면 **개수가 어긋난다.**
      설명글 안에 쉼표가 있으면(예: "실측, 2026-07-31") 원본만 더 잘게 갈라져,
      「둘이 안 맞으니 손대지 말자」는 안전장치가 걸려 **아무것도 안 지워졌다**
      (2026-08-02 실측: 13개가 조용히 남았다). 가린 것에서 자리를 구해 **원본을
      그 자리에서** 가르면 둘이 항상 1:1 로 맞는다.
    """
    자리, 깊이 = [], 0
    for i, c in enumerate(선택자_가린):
        if c == '(':
            깊이 += 1
        elif c == ')':
            깊이 = max(0, 깊이 - 1)
        elif c == ',' and 깊이 == 0:
            자리.append(i)
    return 자리


def _자리로_가르기(글: str, 자리: list[int]) -> list[str]:
    갈래, 앞 = [], 0
    for i in 자리:
        갈래.append(글[앞:i])
        앞 = i + 1
    갈래.append(글[앞:])
    return 갈래


def 걷어내기(css: str) -> tuple[str, int, int]:
    """(새 css, 통째로 지운 규칙 수, 선택자만 줄인 규칙 수)"""
    가린 = _주석가리기(css)          # 위치는 원본과 1:1
    조각들, 지운규칙, 깎은규칙 = [], 0, 0
    i = 0
    while True:
        m = re.search(r'([^{}]+)\{', 가린[i:])
        if not m:
            조각들.append(css[i:])
            break
        시작 = i + m.start()
        여는 = i + m.end() - 1
        선택자_가린 = m.group(1)
        # 짝 맞는 닫는 괄호
        깊이, j = 0, 여는
        while j < len(가린):
            if 가린[j] == '{':
                깊이 += 1
            elif 가린[j] == '}':
                깊이 -= 1
                if 깊이 == 0:
                    break
            j += 1
        if j >= len(가린):
            조각들.append(css[i:])
            break
        규칙끝 = j + 1
        조각들.append(css[i:시작])

        if '@' in 선택자_가린:                    # @media 등은 손대지 않는다
            조각들.append(css[시작:규칙끝])
        else:
            자리 = _가를자리(선택자_가린)
            갈래_가린 = _자리로_가르기(선택자_가린, 자리)
            갈래_원본 = _자리로_가르기(css[시작:여는], 자리)   # ★ 같은 자리 → 늘 1:1
            남길 = [원 for 원, 가 in zip(갈래_원본, 갈래_가린)
                    if not _어두운표시.search(가)]
            if len(남길) == len(갈래_원본):
                조각들.append(css[시작:규칙끝])               # 어두운 것 없음
            elif not 남길:
                지운규칙 += 1                                 # 통째로 삭제
                if css[규칙끝:규칙끝 + 1] == '\n':
                    규칙끝 += 1
            else:
                깎은규칙 += 1
                조각들.append(','.join(남길).strip() + ' ' + css[여는:규칙끝].lstrip())
        i = 규칙끝
    새 = ''.join(조각들)
    새 = re.sub(r'\n{3,}', '\n\n', 새)
    return 새, 지운규칙, 깎은규칙


def _규칙수(css: str) -> int:
    본문 = re.sub(r'/\*.*?\*/', '', css, flags=re.S)
    return len([x for x in re.findall(r'([^{}]+)\{', 본문) if x.strip()])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--쓰기', action='store_true')
    a = ap.parse_args()
    총지움 = 총깎음 = 0
    for 이름 in _대상:
        p = _정적 / 이름
        if not p.exists():
            continue
        옛 = io.open(p, encoding='utf-8').read()
        새, 지움, 깎음 = 걷어내기(옛)
        if not 지움 and not 깎음:
            continue
        # 안전장치 — 괄호·주석 짝이 깨졌으면 그 파일은 손대지 않는다
        if 새.count('{') != 새.count('}') or 새.count('/*') != 새.count('*/'):
            print(f'⚠ {이름}: 짝이 안 맞아 건너뜀 (도구 결함 의심)')
            continue
        총지움 += 지움
        총깎음 += 깎음
        print(f'{이름:<22} 통째삭제 {지움:>3} · 선택자만 {깎음:>3} · 남는 규칙 {_규칙수(새):>4}')
        if a.쓰기:
            io.open(p, 'w', encoding='utf-8', newline='').write(새)
    print(f'\n합계 — 통째삭제 {총지움} · 선택자만 {총깎음}')
    if not a.쓰기:
        print('(미리보기였다. 실제로 지우려면 --쓰기)')


if __name__ == '__main__':
    main()
