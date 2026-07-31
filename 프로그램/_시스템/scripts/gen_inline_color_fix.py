# -*- coding: utf-8 -*-
"""요소에 직접 박힌 색을 어두운 타입에서만 덮는 CSS 를 만든다.

왜 필요한가
    디자인 타입은 `var(--토큰)` 을 쓰는 자리에만 걸린다. 그런데 화면 곳곳에
    `style="background:#fff"` 처럼 **요소에 직접 박힌 색**이 1,600곳 넘게 있다.
    글자색은 토큰을 따라 밝아지는데 배경은 흰색 그대로라, 검정 타입에서
    **흰 글자에 흰 배경(대비 1.09)** 이 된다 — 사장님이 「안 보인다」고 하신 것.

    라이브 실측(2026-07-31, 검정A): 흰 배경 잔재 3,108곳, 대비 미달 8,376곳.

왜 템플릿을 안 고치고 CSS 로 덮나 — 두 가지 이유가 다 실측으로 확인됐다
    ① 이 색들이 몰려 있는 파일 6개는 스윕 금지 목록(SKIP_FILES)이다.
       자바스크립트가 색을 다룬다(`td.style.background = '#FAFBFC'` 같은 쓰기가
       items.html 에만 38곳). 템플릿만 고쳐 봐야 **JS 가 런타임에 다시 밝은 색을
       박는다** — 고쳐도 화면은 그대로다.
    ② CSS 로 덮으면 템플릿이 쓴 것이든 JS 가 쓴 것이든 **둘 다** 잡힌다.

「기존 타입」 무손실
    모든 규칙이 `.ds` 아래에만 있다. 그 타입은 ds 클래스가 안 붙으므로
    이 파일 전체가 잠든다 — 한 픽셀도 안 바뀐다.

브랜드색은 안 건드린다
    마켓 고유색(네이버 초록·쿠팡 빨강·옥션 보라 …)은 그 마켓을 가리키는
    표시다. 바꾸면 다른 마켓처럼 보인다. design_sweep.BRAND_KEEP 과 같은 원칙.

실행
    python scripts/gen_inline_color_fix.py          # 미리보기
    python scripts/gen_inline_color_fix.py --쓰기    # webapp/static/inline_color_fix.css 갱신
"""
from __future__ import annotations

import argparse
import io
import pathlib
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

_시스템 = pathlib.Path(__file__).resolve().parents[1]
_출력 = _시스템 / 'webapp' / 'static' / 'inline_color_fix.css'


# ── 배경 ────────────────────────────────────────────────────────────────
# 순서가 곧 우선순위다(같은 세기의 규칙은 뒤가 이긴다).
# `#fff` 는 `#fff8e6`·`#fff0f0` 의 앞부분이기도 해서 함께 걸린다 →
# 뜻이 있는 옅은 색(노랑·빨강 …)을 **뒤에** 둬서 다시 제 색으로 돌린다.
배경맵: list[tuple[str, list[str], str]] = [
    ('흰 판·아주 옅은 회색 → 카드 바탕', [
        '#fff', '#ffffff', 'white', '#fafbfc', '#f9fafb', '#fafafa',
        '#f2f4f6', '#f1f1f4', '#f3f4f6', '#f4f4f4', '#eef1f4',
    ], 'var(--surface)'),
    ('옅은 파랑 배지·강조칸', ['#eff6ff', '#eaf3ff', '#dbeafe', '#eef1fe', '#f0f6ff', '#f8fbff'],
     'var(--연한-파랑)'),
    ('옅은 초록', ['#f0fdf4', '#e7f8ef', '#ecfdf5'], 'var(--연한-초록)'),
    ('옅은 빨강·분홍', ['#feecec', '#fee2e2', '#fef2f2', '#fff0f0', '#ffe9e9'], 'var(--연한-빨강)'),
    ('옅은 노랑·살구', ['#fef3c7', '#fffbeb', '#fff8e6', '#fef9c3'], 'var(--연한-노랑)'),
    ('옅은 보라', ['#f3e8ff', '#f5f3ff', '#ede9fe'], 'var(--연한-보라)'),
]

# ── 글자 ────────────────────────────────────────────────────────────────
# 흰 글자(#fff)는 그대로 둔다 — 어두운 화면에서도 흰 글자는 잘 보인다.
# (게다가 `color:#fff` 는 `background-color:#fff` 의 일부라 잘못 걸릴 위험이 크다.)
글자맵: list[tuple[str, list[str], str]] = [
    ('진한 글자 — 검정 바탕에서 안 보인다', [
        '#191f28', '#292a2f', '#111827', '#1f2937', '#374151', '#4b5563',
        '#000', '#000000', '#333', '#212529',
    ], 'var(--ink)'),
    ('보조 글자', ['#8b95a1', '#6b7684', '#4e5968', '#525866', '#666'], 'var(--글자-보조)'),
    ('흐린 글자', ['#9ca3af', '#8f91a0', '#6b7280', '#b0b8c1', '#cbccd3', '#d1d6db', '#9aa3af'],
     'var(--글자-희미)'),
]

# ── 테두리 ──────────────────────────────────────────────────────────────
테두리맵: list[tuple[str, list[str], str]] = [
    ('옅은 선 — 흰 바탕 기준이라 검정 위에서 너무 밝다',
     ['#e5e8eb', '#e5e7eb', '#f1f1f4', '#eef1f4', '#e8e8ed', '#ededed'], 'var(--line)'),
]


def _배경선택자(값: str) -> list[str]:
    """`background:` 와 `background-color:` 는 서로의 부분문자열이 아니라 둘 다 필요하다.
    값 앞 공백 유무도 흔하므로 함께 낸다. `i` = 대소문자 무시(#FFF 도 걸린다)."""
    쌍 = []
    for 속성 in ('background:', 'background-color:'):
        for 사이 in ('', ' '):
            쌍.append(f'[style*="{속성}{사이}{값}" i]')
    return 쌍


def _글자선택자(값: str) -> list[str]:
    """`color:` 는 `background-color:` 의 뒷부분이기도 하다.
    그래서 **앞이 무엇인지**를 못 박는다 — 맨 앞이거나, 세미콜론/공백 다음일 때만."""
    쌍 = []
    for 앞 in ('', ';', '; ', ' '):
        for 사이 in ('', ' '):
            본 = f'color:{사이}{값}'
            if 앞 == '':
                쌍.append(f'[style^="{본}" i]')
            else:
                쌍.append(f'[style*="{앞}{본}" i]')
    return 쌍


def _테두리선택자(값: str) -> list[str]:
    쌍 = []
    for 속성 in ('border:', 'border-color:', 'border-top:', 'border-bottom:',
                 'border-left:', 'border-right:'):
        for 사이 in ('', ' '):
            # `border:1px solid #E5E8EB` 처럼 값이 뒤에 붙는 형태까지 잡으려면
            # 속성 이름만으로는 안 된다 → 색 값만으로 매칭하고 border 계열은
            # 아래 `solid` 패턴으로 따로 잡는다.
            pass
    for 앞 in ('solid ', 'solid'):
        쌍.append(f'[style*="{앞}{값}" i]')
    for 속성 in ('border-color:', 'border-color: '):
        쌍.append(f'[style*="{속성}{값}" i]')
    return 쌍


def 만들기() -> str:
    줄 = []
    줄.append('/* ' + '═' * 70)
    줄.append('   요소에 직접 박힌 색 덮개 — 어두운·밝은 타입 전용')
    줄.append('   ' + '─' * 70)
    줄.append('   ★ 이 파일은 손으로 고치지 마세요.')
    줄.append('     scripts/gen_inline_color_fix.py 가 만듭니다(값의 근거는 그 파일 설명 참고).')
    줄.append('')
    줄.append('   왜 필요한가 — 화면 곳곳에 style="background:#fff" 처럼 요소에 직접')
    줄.append('   박힌 색이 1,600곳 넘게 있다. 글자색은 토큰을 따라 밝아지는데 배경은')
    줄.append('   흰색 그대로라, 검정 타입에서 흰 글자에 흰 배경(대비 1.09)이 된다.')
    줄.append('')
    줄.append('   ★ 모든 규칙이 .ds 아래에만 있다 → 「기존 타입」은 한 픽셀도 안 바뀐다.')
    줄.append('   ★ !important 가 필요하다 — 요소에 직접 박힌 색은 그러지 않으면 안 진다.')
    줄.append('   ★ 마켓 브랜드색(네이버 초록·쿠팡 빨강·옥션 보라…)은 일부러 안 건드린다.')
    줄.append('   ' + '═' * 70 + ' */')
    줄.append('')

    def 묶음(제목, 맵, 선택자만들기, 속성):
        줄.append(f'/* ── {제목} ─────────────────────────────────────── */')
        for 설명, 값들, 토큰 in 맵:
            줄.append(f'/* {설명} */')
            for 값 in 값들:
                sels = [f'.ds {s}' for s in 선택자만들기(값)]
                줄.append(',\n'.join(sels) + ' {')
                줄.append(f'  {속성}: {토큰} !important;')
                줄.append('}')
            줄.append('')

    묶음('배경', 배경맵, _배경선택자, 'background-color')
    묶음('글자', 글자맵, _글자선택자, 'color')
    묶음('테두리', 테두리맵, _테두리선택자, 'border-color')
    return '\n'.join(줄) + '\n'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--쓰기', action='store_true')
    a = ap.parse_args()
    본문 = 만들기()
    규칙수 = 본문.count('!important')
    print(f'규칙 {규칙수}개 · {len(본문):,}자')
    if a.쓰기:
        with io.open(_출력, 'w', encoding='utf-8', newline='\n') as f:
            f.write(본문)
        print('썼습니다:', _출력)
    else:
        print('(미리보기 — 실제로 쓰려면 --쓰기)')
        print(본문[:800])


if __name__ == '__main__':
    main()
