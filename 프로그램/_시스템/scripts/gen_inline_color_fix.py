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
    ('흐린 글자', ['#9ca3af', '#8f91a0', '#6b7280', '#b0b8c1', '#cbccd3', '#d1d6db', '#9aa3af',
                   '#d2d2d7'],
     'var(--글자-희미)'),
    # [2026-08-01] 의미색 글자 — 밝은 바탕에서 안 읽힌다(계산값은 tokens.css 주석 참고).
    #   초록 #22C55E 흰 바탕 2.28 · 파랑 #3182F6 3.71 · 주황 #F59E0B 2.15
    # 검정 타입에서는 반대로 밝아야 하므로 토큰이 모드별로 갈린다.
    ('초록 글자', ['#22c55e', '#16a34a', '#10b981', '#34c759', '#059669', '#15803d', '#1ab053',
                   '#0f7a3a', '#065f46'], 'var(--글자-초록)'),
    ('빨강 글자', ['#f04452', '#f04438', '#e24b4a', '#c00', '#8a2020'], 'var(--글자-빨강)'),
    ('주황 글자', ['#b45309', '#92400e', '#ca8a04', '#c2570c', '#c2410c'], 'var(--글자-주황)'),
    ('파랑 글자', ['#3182f6', '#3b82f6', '#4a90d9', '#5b7db1', '#2997ff'], 'var(--글자-파랑)'),
    # 보라 — 자료 숫자에 쓴 자리(검정 위 3.47). 로고 배지는 선택자에서 이미 제외된다.
    ('보라 글자', ['#7c3aed', '#8b5cf6', '#6b21a8', '#5b21a6'], 'var(--보라)'),
]

# ── 흰 글자를 얹은 색 배경 ───────────────────────────────────────────────
# 배경만 보고 바꾸면 어두운 글자를 얹은 자리까지 망가진다.
# **같은 style 안에 흰 글자가 함께 적혀 있을 때만** 바꾼다(선택자 두 개를 겹쳐서).
흰글자배경맵: list[tuple[str, list[str], str]] = [
    ('초록 배경 + 흰 글자 — 지금 2.2~3.3', ['#34c759', '#10b981', '#16a34a', '#22c55e'],
     'var(--바탕-초록)'),
    ('빨강 배경 + 흰 글자 — 지금 3.7~4.2', ['#f04452', '#ee2c2c', '#e24b4a'], 'var(--바탕-빨강)'),
    ('파랑 배경 + 흰 글자 — 지금 3.7~4.5', ['#3182f6', '#3b82f6', '#4f67ff'], 'var(--바탕-파랑)'),
    # [2026-08-02] 주황만 빠져 있었다 — 초록·빨강·파랑은 갈라 뒀는데 주황은 안 갈라서
    #   「조정 완료」·「⚖ 조정」 같은 주황 단추의 흰 글자가 2.15 로 남았다(8화면 25곳).
    #   #F0C040·#FFA500 도 같은 자리에 쓰인다. 브랜드 마크는 아래 선택자로 이미 빠진다.
    ('주황 배경 + 흰 글자 — 지금 2.1~2.6', ['#f59e0b', '#f0c040', '#ffa500', '#ff9500',
                                            '#fb923c', '#f97316'], 'var(--바탕-주황)'),
]
# 마켓 브랜드 마크는 건드리지 않는다 — 바꾸면 다른 마켓처럼 보인다.
# (표준도 로고·브랜드 마크는 대비 기준에서 뺀다.)
브랜드_제외 = ':not(.brand-app-logo):not(.brand-pill-v2):not(.site-logo):not(.brand-favi)'

# ── ★ 굳은 hex 말고 「토큰 형태」로 적힌 자리 ──────────────────────────
#  이 저장소는 이미 색을 `var(--green,#16A34A)` 처럼 바꿔 뒀다. 그래서
#  hex 만 찾으면 정작 대부분을 놓친다(실제로 처음에 놓쳤다).
#  ※ 토큰 자체를 어둡게 만들 수는 없다 — 같은 이름이 검정 화면 위 글자로도
#    쓰여서(거기선 밝아야 한다) 반대 요구가 부딪힌다. 그래서 「쓰인 자리」별로 가른다.
토큰글자맵: list[tuple[str, list[str], str]] = [
    ('초록 글자(토큰)', ['var(--green', 'var(--color-ok'], 'var(--글자-초록)'),
    ('빨강 글자(토큰)', ['var(--red', 'var(--danger'], 'var(--글자-빨강)'),
    ('주황 글자(토큰)', ['var(--amber', 'var(--warning'], 'var(--글자-주황)'),
    ('파랑 글자(토큰)', ['var(--blue', 'var(--sky', 'var(--primary'], 'var(--글자-파랑)'),
    # [2026-08-01] 선·옅은 판을 위한 이름이 「글자」로 쓰인 자리.
    #   요소에 직접 박힌 것(인라인·자바스크립트)이라 <style> 치환기가 못 닿는다.
    #   실측(화이트): var(--n300)=#D2D2D7 글자 1.51 · var(--n500)=#86868B 3.62
    ('흐린 글자(토큰)', ['var(--faint', 'var(--n300', 'var(--n400', 'var(--n500',
                        'var(--sub', 'var(--line'], 'var(--글자-희미)'),
]
토큰흰글자배경맵: list[tuple[str, list[str], str]] = [
    ('초록 배경(토큰) + 흰 글자', ['var(--green', 'var(--color-ok'], 'var(--바탕-초록)'),
    ('빨강 배경(토큰) + 흰 글자', ['var(--red', 'var(--danger'], 'var(--바탕-빨강)'),
    ('주황 배경(토큰) + 흰 글자', ['var(--amber', 'var(--warning'], 'var(--바탕-주황)'),
    # --primary 는 밝은 타입에선 이미 통과(#0071E3 = 4.70)지만 검정 타입에서
    # 밝은 파랑(#2997FF)으로 뒤집혀 흰 글자가 3.02 로 떨어진다(「+ 추가」 단추 114곳).
    ('파랑 배경(토큰) + 흰 글자', ['var(--blue', 'var(--primary', 'var(--sky'],
     'var(--바탕-파랑)'),
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
    묶음('글자(토큰으로 적힌 자리)', 토큰글자맵, _글자선택자, 'color')
    묶음('테두리', 테두리맵, _테두리선택자, 'border-color')

    # ── 흰 글자를 얹은 색 배경 ─────────────────────────────────────────
    줄.append('/* ── 흰 글자를 얹은 색 배경 ───────────────────────────────')
    줄.append('   배경만 보고 바꾸면 어두운 글자를 얹은 자리까지 망가진다.')
    줄.append('   **같은 style 안에 흰 글자가 함께 적혀 있을 때만** 바꾼다.')
    줄.append('   마켓 브랜드 마크는 뺀다 — 바꾸면 다른 마켓처럼 보인다. */')
    흰글자표기 = ['color:#fff', 'color: #fff', 'color:#ffffff', 'color: #ffffff',
                  'color:white', 'color: white']
    for 설명, 값들, 토큰 in 흰글자배경맵 + 토큰흰글자배경맵:
        줄.append(f'/* {설명} */')
        for 값 in 값들:
            sels = []
            for 배경sel in _배경선택자(값):
                for 흰 in 흰글자표기:
                    sels.append(f'.ds {배경sel}[style*="{흰}" i]{브랜드_제외}')
            줄.append(',\n'.join(sels) + ' {')
            줄.append(f'  background-color: {토큰} !important;')
            줄.append('}')
        줄.append('')

    # ── 입력칸 — 색을 아무도 안 정해도 브라우저가 흰색으로 그린다 ──────────
    # 그래서 위의 「박힌 색」 규칙으로는 안 잡힌다(박힌 게 없으니까).
    # 어두운 타입에서 흰 상자가 가장 눈에 띄는 잔재였다(감사 실측 176곳).
    줄.append('/* ── 입력칸 ─────────────────────────────────────────────')
    줄.append('   색을 아무도 안 정해도 브라우저가 흰색으로 그린다 → 박힌 색 규칙으로는')
    줄.append('   안 잡힌다. 어두운 타입에서 가장 눈에 띄는 흰 상자였다.')
    줄.append('   버튼·체크상자는 뺀다 — 버튼은 제 색이 있고, 체크상자는 색을 건드리면')
    줄.append('   켜짐/꺼짐이 안 보인다. */')
    줄.append(', '.join([
        '.ds input:not([type="checkbox"]):not([type="radio"]):not([type="range"]):not([type="color"])',
        '.ds select', '.ds textarea',
    ]) + ' {')
    줄.append('  background-color: var(--surface);')
    줄.append('  color: var(--ink);')
    줄.append('  border-color: var(--line);')
    줄.append('}')
    줄.append('.ds input::placeholder, .ds textarea::placeholder { color: var(--글자-희미); }')
    줄.append('')
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
