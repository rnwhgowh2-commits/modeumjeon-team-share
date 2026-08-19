# -*- coding: utf-8 -*-
"""디자인 치환 스크립트 뼈대 (T6) — 하드코딩 hex 색을 CSS 변수로 바꾼다.

배경: 새 디자인(Apple 실측 기반, `class="ds"` 옵트인)은 CSS **변수**를 쓰는
곳에만 적용된다. 162개 템플릿에서 var(--…) 는 2,443곳, 하드코딩 hex 색은
10,402곳(776종)이라 지금 모드를 켜면 반쪽만 새 디자인이 되는 "얼룩" 화면이
나온다. 이 스크립트는 그 hex 색을 변수로 치환하는 도구이며, **이 파일 자체는
어떤 템플릿도 건드리지 않는다** — 적용은 이후 태스크(T7~T10)의 몫이다.

핵심 안전 규칙 (모두 테스트로 고정됨, tests/design/test_design_sweep.py):
  1. class=/id=/data-* 속성값 안의 색은 절대 안 건드린다 —애초에 그 속성을
     스캔하지 않는다 (style="..." 와 <style> 블록만 스캔).
  2. style="..." 안, <style> 블록 안의 CSS 선언은 바꾼다.
  3. 대소문자 무관 매칭, 3자리 축약(#abc → #aabbcc) 확장 후 조회.
  4. BRAND_KEEP 에 있는 색은 절대 안 바꾼다 (마켓/브랜드 고유색).
  5. <script> 안의 JS 문자열(색 대입)은 스캔 범위 밖이라 원천적으로 안 건드림.
  6. Jinja 태그 자체 안({{ … }}, {% … %}) 의 내용은 안 건드린다 — 단, 조건부
     분기의 *출력* 위치에 있는 CSS 값(예: `{% if %}#hex{% else %}#hex2{% endif %}`)
     은 진짜 CSS 값이므로 바꾼다 (아래 "설계 판단" 참고).
  7. SKIP_FILES 에 있는 9개 파일은 통째로 건드리지 않는다.
  8. COLOR_MAP 에 없는 색은 그대로 둔다 — 추측 금지.

설계 판단 — 예비값(fallback) 동반 치환:
  치환 결과는 항상 예비값을 동반한다 — `#191F28` 이 `var(--ink)` 가 아니라
  `var(--ink,#191F28)` 로 바뀐다. 예비값은 이 자리에서 실제로 매치된 원본
  hex 다(COLOR_MAP 이 다대일이라 변수의 "대표값"과 다를 수 있음 — 예:
  191f28/292a2f/374151/333d4b 는 전부 var(--ink) 로 가지만 각자 자기
  원본 hex 를 예비값으로 남긴다). `current` 모드는 tokens.css 의 `.ds`
  안에서만 `--ink` 등을 정의하므로, `class="ds"` 가 없는 화면에서는 이
  변수가 미정의라 브라우저가 예비값을 그대로 쓴다 — 즉 스윕 전과 픽셀
  단위로 동일한 색이 나온다(안전망). `ds` 모드에서는 변수가 정의돼 있어
  예비값은 무시되고 애플 팔레트가 이긴다.

설계 판단 — Jinja 보호 범위:
  `{{ ... }}` / `{% ... %}` **델리미터 안쪽 텍스트**만 보호 대상이다. 예를 들어
  `{{ some_macro('#191f28') }}` 처럼 hex 가 Jinja/Python 문자열 리터럴의
  일부로 쓰이면(비-CSS 문맥일 수 있음) 절대 안 건드린다. 반면
  `style="border:1px solid {% if x %}#4F67FF{% else %}#E5E8EB{% endif %}"`
  처럼 제어 태그 *사이*에 있는 색은 항상 style="" 값 안의 진짜 CSS 값으로
  렌더링되므로(실사례: inventory/settings/integration.html) 정상적으로 바꾼다.

BRAND_KEEP 조사 방법과 판단 근거:
  템플릿 전체에서 쿠팡/네이버/SSG/롯데/SSF/무신사/11번가/옥션/G마켓/스마트스토어
  근처 hex 와 `.br-*`/`brand` 클래스를 grep 했다. 결과, 마켓 고유색은 전부
  <script> 안의 JS 객체 리터럴(예: `{key:'musinsa', color:'#191f28'}`,
  `MK={coupang:{c:'#E03A3E'}, ...}`)이거나 이미 SKIP_FILES 에 들어있는 파일
  (accounts/upload.html, bundles/_matrix_v3.html 등) 안에만 있었다 — 즉 스캔
  범위(스타일 속성/<style> 블록) 밖이라 구조적으로 이미 안전하다.
  그래도 방어적으로(향후 COLOR_MAP 이 커질 때 대비) 실제로 발견한 **뚜렷한**
  마켓 고유색만 시드했다. 반대로 #191f28/#000000/#1a1a1a 같은 무채색(검정 계열)은
  일부러 **제외**했다 — 이 값들은 무신사/SSF 를 가리키는 JS 상수로도 쓰이지만
  동시에 템플릿 전역에서 가장 흔한 "일반 텍스트 잉크" 색(COLOR_MAP 1순위,
  #191f28→var(--ink))이기도 하다. BRAND_KEEP 에 넣으면 이 스윕의 존재 이유인
  최상위 치환 대상을 통째로 막아버리는데, 실제로 마켓 브랜드색으로 쓰이는
  자리는 전부 <script> 안이라 BRAND_KEEP 없이도 이미 보호된다 — 득 없이
  핵심 기능만 죽이는 셈이라 뺐다.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Set, Tuple

try:
    sys.stdout.reconfigure(encoding='utf-8')  # type: ignore[attr-defined]
except Exception:
    pass


# ── 경로 ──────────────────────────────────────────────────────────────
_SCRIPT_DIR = Path(__file__).resolve().parent
_SYSTEM_DIR = _SCRIPT_DIR.parent  # 프로그램/_시스템
TEMPLATES_DIR = _SYSTEM_DIR / 'webapp' / 'templates'


# ── 절대 건드리지 않는 9개 파일 (위험 구역) ──────────────────────────
SKIP_FILES: Set[str] = {
    'bundles/_matrix_v3.html',
    'bulk/partials/_settings.html',
    'inventory/data/items.html',
    'inventory/barcode.html',
    'accounts/upload.html',
    'orders/margin_embed.html',
    'inventory/home.html',
    'inventory/inspection_detail.html',
    'sourcing_guide/add.html',
}
assert len(SKIP_FILES) == 9, f'SKIP_FILES 는 정확히 9개여야 함 (현재 {len(SKIP_FILES)})'

# ── 어떤 스윕도 절대 건드리면 안 되는 파일 ─────────────────────────────
#  SKIP_FILES 와 뜻이 다르다. 저기는 「<style> 블록은 훑어도 된다」이고,
#  여기는 **한 글자도 손대면 안 된다**.
#
#  [2026-08-01] 안전망 드롭버튼이 여기 들어간다.
#  이 부품은 토큰을 한 개도 쓰지 않는 것이 존재 이유다 — 토큰이 무너졌을 때
#  「기존 타입」으로 되돌릴 유일한 통로이기 때문이다. 실제로 흰 배경 스윕이
#  여기까지 손대서 `background: var(--surface,#FFFFFF)` 로 바꿔 놨다.
#  (tests/design/test_dark_contrast_pass2.py 가 그 성질에 못을 박아 두고 있다.)
절대금지: Set[str] = {
    'partials/design_mode_menu.html',
}


# ── 마켓/브랜드 고유색 — 절대 치환 금지 ──────────────────────────────
# 조사 방법·근거는 모듈 docstring 참고. 전부 소문자 6자리(# 없이).
BRAND_KEEP: Set[str] = {
    # 네이버 · 스마트스토어 (초록)
    '03c75a', '2db400',
    # 쿠팡 (빨강 계열, 파일마다 값이 갈려 발견한 것 전부 시드)
    'ff5a5f', 'e03a3e', 'ee293d', 'b91c1c',
    # 롯데온 · 롯데아이몰 (빨강 계열)
    'ed2025', 'e60012', 'ef4444', 'da291c', '1b64da',
    # SSG (주황/자홍)
    'f47216', 'cd163f', 'f97316',
    # SSF샵 (보라/남색/주황)
    '8b5cf6', '1e3a8a', 'ff6b00',
    # 르무통 (호박색/연보라/베이지)
    'f59e0b', 'a78bfa', 'fef3c7',
    # 11번가 (빨강/주황)
    'ff0038', 'c2410c',
    # 옥션 (보라)
    '7c3aed',
    # G마켓 (초록/청록)
    '00a862', '0f766e',
    # 무신사 (짙은 남색 배경 — 순검정·순무채색은 일부러 제외, docstring 참고)
    '1f2937',
}


# ── T6 시드 — 측정 상위 10개 색 ────────────────────────────────────────
# ── T7 — 다음 110개 추가(자동 분류 제안 병합, color_map_add.py 원천) ──
# 대상 변수는 전부 webapp/static/tokens.css 에 실재함을
# test_color_map_타겟변수는_tokens_css에_실재한다 로 고정 검증한다.
COLOR_MAP: Dict[str, str] = {
    # [2026-08-01] 옅은 판(배지 바탕) — 검정 타입에서 밝게 남아 그 위 밝은 글자가
    #   안 읽혔다(실측: 소싱처 칩 #F3E8FF 위 밝은 글자 대비 1.08).
    'f3e8ff': 'var(--연한-보라)', 'e9d5ff': 'var(--연한-보라)',
    'e8f2ff': 'var(--연한-파랑)', 'e6f1fc': 'var(--연한-파랑)', 'eaf3ff': 'var(--연한-파랑)',
    'e9f9ef': 'var(--연한-초록)', 'daf5e1': 'var(--연한-초록)',
    'fef6e7': 'var(--연한-주황)',
    # T6 시드 10개
    '191f28': 'var(--ink)',
    'e5e8eb': 'var(--line)',
    '6b7684': 'var(--글자-보조)',
    '8b95a1': 'var(--sub)',
    '4e5968': 'var(--글자-기본)',
    '3182f6': 'var(--primary)',
    'f2f4f6': 'var(--n100)',
    'f9fafb': 'var(--bg)',
    'd1d6db': 'var(--faint)',
    'cbccd3': 'var(--faint)',

    # T7 — 본문 잉크
    '292a2f': 'var(--ink)',              # 277곳
    '374151': 'var(--ink)',              # 13곳
    '333d4b': 'var(--ink)',              # 6곳

    # T7 — 보조 글자
    '8f91a0': 'var(--sub)',              # 170곳
    '6b7280': 'var(--sub)',              # 36곳

    # T7 — 흐린 글자
    '9ca3af': 'var(--faint)',            # 131곳
    'b0b8c1': 'var(--faint)',            # 61곳
    '9aa4b0': 'var(--faint)',            # 34곳
    '98a2b3': 'var(--faint)',            # 18곳
    '9aa3ad': 'var(--faint)',            # 12곳
    '999999': 'var(--faint)',            # 7곳
    '9aa0aa': 'var(--faint)',            # 5곳
    '99a1ab': 'var(--faint)',            # 6곳
    '94a3b8': 'var(--faint)',            # 5곳

    # T7 — 파랑(primary)
    '4f67ff': 'var(--primary)',          # 107곳
    '1e40af': 'var(--primary)',          # 27곳
    '1d4ed8': 'var(--primary)',          # 23곳
    '0c447c': 'var(--primary)',          # 13곳
    '185fa5': 'var(--primary)',          # 11곳
    '2563eb': 'var(--primary)',          # 11곳
    '0a2540': 'var(--primary)',          # 9곳
    '3b82f6': 'var(--primary)',          # 8곳

    # T7 — 연한 선(line2)
    'f1f1f4': 'var(--line2)',            # 92곳
    'f1f3f5': 'var(--line2)',            # 36곳
    'eef1f4': 'var(--line2)',            # 35곳
    'e5e7eb': 'var(--line2)',            # 19곳
    'f3f4f6': 'var(--line2)',            # 14곳
    'f4f6f8': 'var(--line2)',            # 11곳
    'f4f5f7': 'var(--line2)',            # 11곳
    'eef0f3': 'var(--line2)',            # 10곳
    'eef2f7': 'var(--line2)',            # 6곳
    'edf0f3': 'var(--line2)',            # 6곳
    'e9ecef': 'var(--line2)',            # 7곳

    # T7 — 초록
    '15803d': 'var(--green)',            # 79곳
    '22c55e': 'var(--green)',            # 27곳
    '16a34a': 'var(--green)',            # 27곳
    '10b981': 'var(--green)',            # 25곳
    '065f46': 'var(--green)',            # 18곳
    '12b886': 'var(--green)',            # 8곳
    '0f6e56': 'var(--green)',            # 7곳
    '15a06e': 'var(--green)',            # 7곳
    '03a65a': 'var(--green)',            # 6곳
    '166534': 'var(--green)',            # 6곳
    '0f9d58': 'var(--green)',            # 6곳
    '0b7a54': 'var(--green)',            # 5곳
    '12b76a': 'var(--green)',            # 5곳

    # T7 — 빨강
    'dc2626': 'var(--red)',              # 61곳
    '991b1b': 'var(--red)',              # 52곳
    'c0392b': 'var(--red)',              # 18곳
    'f04452': 'var(--red)',              # 16곳
    'c53030': 'var(--red)',              # 12곳
    'e5484d': 'var(--red)',              # 9곳
    'c92a2a': 'var(--red)',              # 8곳

    # T7 — 주황(amber)
    '92400e': 'var(--amber)',            # 48곳
    'b45309': 'var(--amber)',            # 35곳
    '8a5a00': 'var(--amber)',            # 13곳
    'e8830c': 'var(--amber)',            # 13곳
    '854f0b': 'var(--amber)',            # 11곳
    '8a6100': 'var(--amber)',            # 6곳
    '78350f': 'var(--amber)',            # 6곳
    'd98300': 'var(--amber)',            # 6곳

    # T7 — 아주 밝은 회색(n100)
    'fafbfc': 'var(--n100)',             # 25곳
    'f7f9fb': 'var(--n100)',             # 22곳
    'fbfcfd': 'var(--n100)',             # 12곳
    'f7f8fa': 'var(--n100)',             # 9곳
    'f6f8fa': 'var(--n100)',             # 8곳
    'fcfdfe': 'var(--n100)',             # 8곳
    'f8fafb': 'var(--n100)',             # 8곳
    'f7faff': 'var(--n100)',             # 7곳
    'f5f7f9': 'var(--n100)',             # 6곳
    'f4f8ff': 'var(--n100)',             # 5곳

    # T7 — 선(line)
    'dddddd': 'var(--line)',             # 11곳
    'c9d2dc': 'var(--line)',             # 6곳
    'dde1e6': 'var(--line)',             # 5곳

    # T7 — 본문 회색(글자-기본)
    '4b5563': 'var(--글자-기본)',            # 14곳
    '555555': 'var(--글자-기본)',            # 12곳
    '666666': 'var(--글자-기본)',            # 10곳
    '555e6b': 'var(--글자-기본)',            # 9곳
    '5f5e5a': 'var(--글자-기본)',            # 7곳
    '475569': 'var(--글자-기본)',            # 6곳

    # T7 — 연한 빨강 배경 (신규 토큰, tokens.css 참고)
    'fef2f2': 'var(--연한-빨강)',            # 53곳
    'fee2e2': 'var(--연한-빨강)',            # 48곳
    'fca5a5': 'var(--연한-빨강)',            # 48곳
    'feecec': 'var(--연한-빨강)',            # 12곳
    'fdecec': 'var(--연한-빨강)',            # 9곳

    # T7 — 연한 초록 배경 (신규 토큰)
    'dcfce7': 'var(--연한-초록)',            # 38곳
    'ecfdf5': 'var(--연한-초록)',            # 35곳
    '86efac': 'var(--연한-초록)',            # 32곳
    'e7f6ec': 'var(--연한-초록)',            # 9곳
    'e6f9f1': 'var(--연한-초록)',            # 5곳
    'f0fdf4': 'var(--연한-초록)',            # 8곳

    # T7 — 연한 주황 배경 (신규 토큰)
    'fffbeb': 'var(--연한-주황)',            # 18곳
    'fef6e7': 'var(--연한-주황)',            # 13곳
    'f5d9a0': 'var(--연한-주황)',            # 10곳
    'fde68a': 'var(--연한-주황)',            # 10곳
    'fef3e2': 'var(--연한-주황)',            # 7곳
    'faeeda': 'var(--연한-주황)',            # 6곳
    'fde4c5': 'var(--연한-주황)',            # 6곳
    'fff4e6': 'var(--연한-주황)',            # 5곳

    # T7 — 연한 파랑 배경 (신규 토큰)
    'eef4ff': 'var(--연한-파랑)',            # 21곳
    'dbeafe': 'var(--연한-파랑)',            # 21곳
    'eff6ff': 'var(--연한-파랑)',            # 20곳
    'e8f2ff': 'var(--연한-파랑)',            # 19곳
    'bfdbfe': 'var(--연한-파랑)',            # 14곳
    'eaf2fe': 'var(--연한-파랑)',            # 10곳
    'eef1fe': 'var(--연한-파랑)',            # 10곳
    'e8f1ff': 'var(--연한-파랑)',            # 7곳
    'e6f1fb': 'var(--연한-파랑)',            # 6곳
    'f0f7ff': 'var(--연한-파랑)',            # 5곳
    'eaf3ff': 'var(--연한-파랑)',            # 5곳

    # T10(Job2) — 롱테일 정리(design_sweep 재실행 대상 남은 색).
    # 근거: max-min 채널<12 는 hue 가 불안정해 무채색으로, S<40% 는 '색이라
    # 있어도 사실상 무채색'으로 보아 근채색(n100~ink) 버킷에, S>=40% 인
    # 나머지는 밝기(L)로 연한-배경/진한 4색을 가른다(정확한 문턱은 스크립트
    # 상단 주석 참고). #fff/#000 은 배경·글자 겸용이라 제외, 보라·마젠타·
    # 청록처럼 대응 토큰이 없는 색은 추측하지 않고 그대로 둔다.

    # T10 — 아주 밝은 회색(n100) — 롱테일
    'fcfcfd': 'var(--n100)',  # 5곳
    'fff5f5': 'var(--n100)',  # 4곳
    'fbfdff': 'var(--n100)',  # 4곳
    'f7f8f9': 'var(--n100)',  # 3곳
    'f2fbf5': 'var(--n100)',  # 3곳
    'fcfbff': 'var(--n100)',  # 2곳
    'fffcf5': 'var(--n100)',  # 2곳
    'faf5ff': 'var(--n100)',  # 2곳
    'f5fbf7': 'var(--n100)',  # 2곳
    'fbfcff': 'var(--n100)',  # 2곳
    'f1fbf5': 'var(--n100)',  # 2곳
    'fff4f4': 'var(--n100)',  # 2곳
    'f7fafe': 'var(--n100)',  # 2곳
    'f5f9ff': 'var(--n100)',  # 1곳
    'fff6f6': 'var(--n100)',  # 1곳
    'f5f6f8': 'var(--n100)',  # 1곳
    'fff9f9': 'var(--n100)',  # 1곳
    'fbfbfc': 'var(--n100)',  # 1곳
    'faf9f6': 'var(--n100)',  # 1곳
    'fffdf8': 'var(--n100)',  # 1곳
    'fafcff': 'var(--n100)',  # 1곳
    'f4f6f9': 'var(--n100)',  # 1곳
    'fafafb': 'var(--n100)',  # 1곳
    'f7fbff': 'var(--n100)',  # 1곳
    'f5f7fa': 'var(--n100)',  # 1곳
    'f3fbf4': 'var(--n100)',  # 1곳
    'fbfdfb': 'var(--n100)',  # 1곳
    'fffdf6': 'var(--n100)',  # 1곳
    'fff8f8': 'var(--n100)',  # 1곳
    'f7fcf9': 'var(--n100)',  # 1곳
    'fff7f7': 'var(--n100)',  # 1곳
    'fbfaf7': 'var(--n100)',  # 1곳
    'f1fbf6': 'var(--n100)',  # 1곳
    'f8f4ff': 'var(--n100)',  # 1곳
    'fff7f8': 'var(--n100)',  # 1곳

    # T10 — 연한 선(line2) — 롱테일
    'eff1f3': 'var(--line2)',  # 4곳
    'f0f1f3': 'var(--line2)',  # 4곳
    'eef0f2': 'var(--line2)',  # 3곳
    'f0f2f5': 'var(--line2)',  # 3곳
    'eaecef': 'var(--line2)',  # 3곳
    'e2e8f0': 'var(--line2)',  # 3곳
    'eceff2': 'var(--line2)',  # 3곳
    'e6ebf1': 'var(--line2)',  # 2곳
    'f1f7f3': 'var(--line2)',  # 2곳
    'eeeeee': 'var(--line2)',  # 2곳
    'f1efe8': 'var(--line2)',  # 2곳
    'f5f5f5': 'var(--line2)',  # 2곳
    'ececef': 'var(--line2)',  # 2곳
    'e8ebee': 'var(--line2)',  # 2곳
    'f0faf4': 'var(--line2)',  # 1곳
    'e9edf1': 'var(--line2)',  # 1곳
    'f2f8f4': 'var(--line2)',  # 1곳
    'eef2f6': 'var(--line2)',  # 1곳
    'f1f4f7': 'var(--line2)',  # 1곳
    'f1f5f9': 'var(--line2)',  # 1곳
    'e8f5ee': 'var(--line2)',  # 1곳
    'eff1f4': 'var(--line2)',  # 1곳
    'e9ebef': 'var(--line2)',  # 1곳
    'f0fbf6': 'var(--line2)',  # 1곳
    'f2f3f5': 'var(--line2)',  # 1곳
    'edeff2': 'var(--line2)',  # 1곳
    'e7ebee': 'var(--line2)',  # 1곳
    'e4e9f0': 'var(--line2)',  # 1곳
    'e3f2ea': 'var(--line2)',  # 1곳
    'eef1f5': 'var(--line2)',  # 1곳
    'f0f2f4': 'var(--line2)',  # 1곳
    'e8ecef': 'var(--line2)',  # 1곳
    'f0faf5': 'var(--line2)',  # 1곳

    # T10 — 선(line) — 롱테일
    'c4cad2': 'var(--line)',  # 4곳
    'bee3d5': 'var(--line)',  # 4곳
    'e1e4e8': 'var(--line)',  # 4곳
    'c2c9d2': 'var(--line)',  # 3곳
    'd7dde3': 'var(--line)',  # 3곳
    'c6cdd6': 'var(--line)',  # 3곳
    'd1d5db': 'var(--line)',  # 3곳
    'cbd5e1': 'var(--line)',  # 3곳
    'd5dbe2': 'var(--line)',  # 3곳
    'c6cbd3': 'var(--line)',  # 3곳
    'dceee3': 'var(--line)',  # 3곳
    'c8cdd3': 'var(--line)',  # 3곳
    'c6cdd5': 'var(--line)',  # 3곳
    'e4e8ec': 'var(--line)',  # 2곳
    'd7dce2': 'var(--line)',  # 2곳
    'c9cdd2': 'var(--line)',  # 2곳
    'cdd5de': 'var(--line)',  # 2곳
    'cbd2d9': 'var(--line)',  # 2곳
    'c6ccd3': 'var(--line)',  # 2곳
    'c5ccd4': 'var(--line)',  # 1곳
    'e0e4e9': 'var(--line)',  # 1곳
    'cde7d6': 'var(--line)',  # 1곳
    'cbd0d6': 'var(--line)',  # 1곳
    'c4ccd4': 'var(--line)',  # 1곳
    'e3e0d8': 'var(--line)',  # 1곳
    'cdd1d8': 'var(--line)',  # 1곳
    'cccccc': 'var(--line)',  # 1곳
    'dfe2e6': 'var(--line)',  # 1곳
    'e5c9c9': 'var(--line)',  # 1곳
    'c5cbd3': 'var(--line)',  # 1곳
    'dbe1e8': 'var(--line)',  # 1곳
    'd5d9de': 'var(--line)',  # 1곳
    'd0d7de': 'var(--line)',  # 1곳
    'cfd4da': 'var(--line)',  # 1곳
    'cfe9dc': 'var(--line)',  # 1곳
    'c2c8cf': 'var(--line)',  # 1곳
    'd7dbe0': 'var(--line)',  # 1곳
    'dce2ea': 'var(--line)',  # 1곳
    'cdd6e2': 'var(--line)',  # 1곳
    'd9dee4': 'var(--line)',  # 1곳
    'c9d1d9': 'var(--line)',  # 1곳
    'c5ccd3': 'var(--line)',  # 1곳

    # T10 — 흐린 글자(faint) — 롱테일
    '9aa3af': 'var(--faint)',  # 4곳
    'aab2bd': 'var(--faint)',  # 3곳
    'a0a8b0': 'var(--faint)',  # 3곳
    'c0c6cd': 'var(--faint)',  # 1곳
    'b4b2a9': 'var(--faint)',  # 1곳
    'aeb4bd': 'var(--faint)',  # 1곳
    'b6bcc4': 'var(--faint)',  # 1곳
    'b9c2cc': 'var(--faint)',  # 1곳
    '9dc9a8': 'var(--faint)',  # 1곳
    'aacccc': 'var(--faint)',  # 1곳
    'a7aeb6': 'var(--faint)',  # 1곳
    'c0c4cc': 'var(--faint)',  # 1곳
    '9aa3ab': 'var(--faint)',  # 1곳
    'a8b0b8': 'var(--faint)',  # 1곳
    'b8c0c8': 'var(--faint)',  # 1곳
    '9aa4b2': 'var(--faint)',  # 1곳
    'b7c0c8': 'var(--faint)',  # 1곳

    # T10 — 보조 글자(sub) — 롱테일
    '888888': 'var(--sub)',  # 4곳
    '868e96': 'var(--sub)',  # 2곳
    '777777': 'var(--sub)',  # 2곳
    '8fa898': 'var(--sub)',  # 1곳
    '64748b': 'var(--sub)',  # 1곳

    # T10 — 본문 회색(글자-기본) — 롱테일
    '5b6573': 'var(--글자-기본)',  # 3곳
    '3a4a5a': 'var(--글자-기본)',  # 2곳
    '425466': 'var(--글자-기본)',  # 1곳
    '495057': 'var(--글자-기본)',  # 1곳
    '3f8a72': 'var(--글자-기본)',  # 1곳
    '5c6672': 'var(--글자-기본)',  # 1곳
    '4d7c5a': 'var(--글자-기본)',  # 1곳
    '3e4854': 'var(--글자-기본)',  # 1곳
    '5e6670': 'var(--글자-기본)',  # 1곳

    # T10 — 본문 잉크(ink) — 롱테일
    '111827': 'var(--ink)',  # 5곳
    '0f172a': 'var(--ink)',  # 4곳
    '333344': 'var(--ink)',  # 2곳
    '2a3038': 'var(--ink)',  # 2곳
    '3a424b': 'var(--ink)',  # 2곳
    '232320': 'var(--ink)',  # 1곳
    '3a3a37': 'var(--ink)',  # 1곳
    '2c2c2a': 'var(--ink)',  # 1곳
    '444441': 'var(--ink)',  # 1곳
    '1e293b': 'var(--ink)',  # 1곳
    '0f141a': 'var(--ink)',  # 1곳
    '2e3742': 'var(--ink)',  # 1곳
    '3a4450': 'var(--ink)',  # 1곳
    '0e1525': 'var(--ink)',  # 1곳
    '2a3441': 'var(--ink)',  # 1곳
    '2b333c': 'var(--ink)',  # 1곳
    '33424f': 'var(--ink)',  # 1곳

    # T10 — 파랑(primary) — 롱테일
    '534ab7': 'var(--primary)',  # 4곳
    '1b4a9e': 'var(--primary)',  # 3곳
    '5b51c4': 'var(--primary)',  # 2곳
    '1f5fe0': 'var(--primary)',  # 2곳
    '4263eb': 'var(--primary)',  # 1곳
    '1971c2': 'var(--primary)',  # 1곳
    '3556c9': 'var(--primary)',  # 1곳
    '7f77dd': 'var(--primary)',  # 1곳
    '635bff': 'var(--primary)',  # 1곳
    '4338ca': 'var(--primary)',  # 1곳
    '60a5fa': 'var(--primary)',  # 1곳
    '3c3489': 'var(--primary)',  # 1곳
    '0a3b6e': 'var(--primary)',  # 1곳
    '5b7fb9': 'var(--primary)',  # 1곳
    '0369a1': 'var(--primary)',  # 1곳
    '3f72b8': 'var(--primary)',  # 1곳
    '1657bc': 'var(--primary)',  # 1곳
    '4e79b8': 'var(--primary)',  # 1곳
    '1a6fe0': 'var(--primary)',  # 1곳
    '1546a0': 'var(--primary)',  # 1곳
    '1b6fe0': 'var(--primary)',  # 1곳
    '143356': 'var(--primary)',  # 1곳

    # T10 — 초록(green) — 롱테일
    '059669': 'var(--green)',  # 5곳
    '0f8a4d': 'var(--green)',  # 5곳
    '1a9e54': 'var(--green)',  # 5곳
    '0ca678': 'var(--green)',  # 4곳
    '0e8056': 'var(--green)',  # 4곳
    '0a7a55': 'var(--green)',  # 3곳
    '047857': 'var(--green)',  # 3곳
    '1fa463': 'var(--green)',  # 3곳
    '1a7f37': 'var(--green)',  # 3곳
    '5bc589': 'var(--green)',  # 2곳
    '1d9e75': 'var(--green)',  # 2곳
    '27500a': 'var(--green)',  # 2곳
    '087f5b': 'var(--green)',  # 2곳
    '14532d': 'var(--green)',  # 2곳
    '00a661': 'var(--green)',  # 2곳
    '11a36b': 'var(--green)',  # 2곳
    '1a7f52': 'var(--green)',  # 2곳
    '00c471': 'var(--green)',  # 1곳
    '0e8f54': 'var(--green)',  # 1곳
    '34d399': 'var(--green)',  # 1곳
    '4ade80': 'var(--green)',  # 1곳
    '085041': 'var(--green)',  # 1곳
    '1f9d57': 'var(--green)',  # 1곳
    '00a05b': 'var(--green)',  # 1곳
    '2b8a3e': 'var(--green)',  # 1곳
    '0a5a45': 'var(--green)',  # 1곳
    '0b6b4f': 'var(--green)',  # 1곳
    '2bb673': 'var(--green)',  # 1곳
    '1e7c4a': 'var(--green)',  # 1곳
    '63e6be': 'var(--green)',  # 1곳
    '066649': 'var(--green)',  # 1곳
    '0f6e4c': 'var(--green)',  # 1곳

    # T10 — 빨강(red) — 롱테일
    '7f1d1d': 'var(--red)',  # 5곳
    'e0455e': 'var(--red)',  # 5곳
    'c0343f': 'var(--red)',  # 4곳
    'f03e3e': 'var(--red)',  # 4곳
    'e03131': 'var(--red)',  # 4곳
    'e0392b': 'var(--red)',  # 4곳
    'f04438': 'var(--red)',  # 3곳
    '8a2a2a': 'var(--red)',  # 3곳
    'ff4444': 'var(--red)',  # 2곳
    '8a2020': 'var(--red)',  # 2곳
    'aa0000': 'var(--red)',  # 2곳
    'da2128': 'var(--red)',  # 1곳
    'e53935': 'var(--red)',  # 1곳
    'b4291b': 'var(--red)',  # 1곳
    '6b1010': 'var(--red)',  # 1곳
    'ff5a3c': 'var(--red)',  # 1곳
    'f87171': 'var(--red)',  # 1곳
    'e11d48': 'var(--red)',  # 1곳
    '791f1f': 'var(--red)',  # 1곳
    'a32d2d': 'var(--red)',  # 1곳
    'ff6b6b': 'var(--red)',  # 1곳
    'a3282e': 'var(--red)',  # 1곳
    '8a1f24': 'var(--red)',  # 1곳
    'e24b4a': 'var(--red)',  # 1곳
    '9a2436': 'var(--red)',  # 1곳

    # T10 — 주황(amber) — 롱테일
    '9a6700': 'var(--amber)',  # 5곳
    '7c4a03': 'var(--amber)',  # 5곳
    'd08700': 'var(--amber)',  # 5곳
    '993c1d': 'var(--amber)',  # 4곳
    '6b4400': 'var(--amber)',  # 3곳
    'fcd34d': 'var(--amber)',  # 3곳
    'ffcb6b': 'var(--amber)',  # 3곳
    'b4690e': 'var(--amber)',  # 3곳
    'ffb84d': 'var(--amber)',  # 2곳
    '8a5a0b': 'var(--amber)',  # 2곳
    'c08d5b': 'var(--amber)',  # 2곳
    '5b3d08': 'var(--amber)',  # 2곳
    '633806': 'var(--amber)',  # 2곳
    '9a3412': 'var(--amber)',  # 2곳
    '7a4f00': 'var(--amber)',  # 2곳
    'ffd700': 'var(--amber)',  # 2곳
    'b36a00': 'var(--amber)',  # 2곳
    'f08c00': 'var(--amber)',  # 2곳
    'a66a00': 'var(--amber)',  # 2곳
    '664d03': 'var(--amber)',  # 1곳
    'ff8b00': 'var(--amber)',  # 1곳
    'e07a00': 'var(--amber)',  # 1곳
    'ffb800': 'var(--amber)',  # 1곳
    'f2c94c': 'var(--amber)',  # 1곳
    '7a5320': 'var(--amber)',  # 1곳
    '8a6d00': 'var(--amber)',  # 1곳
    'e8590c': 'var(--amber)',  # 1곳
    '7a4e00': 'var(--amber)',  # 1곳
    '5c3200': 'var(--amber)',  # 1곳
    '8a5a06': 'var(--amber)',  # 1곳
    'd85a30': 'var(--amber)',  # 1곳
    '6b4300': 'var(--amber)',  # 1곳
    '712b13': 'var(--amber)',  # 1곳
    'c2691a': 'var(--amber)',  # 1곳
    'ff8e3c': 'var(--amber)',  # 1곳
    'fbbf24': 'var(--amber)',  # 1곳
    'f59f00': 'var(--amber)',  # 1곳
    'b26a00': 'var(--amber)',  # 1곳
    '94670a': 'var(--amber)',  # 1곳
    'eab308': 'var(--amber)',  # 1곳
    'e3a93b': 'var(--amber)',  # 1곳
    '7c4a16': 'var(--amber)',  # 1곳
    'b5870a': 'var(--amber)',  # 1곳

    # T10 — 연한 빨강 배경 — 롱테일
    'f3c2c2': 'var(--연한-빨강)',  # 4곳
    'fecaca': 'var(--연한-빨강)',  # 4곳
    'ffc9c9': 'var(--연한-빨강)',  # 4곳
    'fff0f0': 'var(--연한-빨강)',  # 3곳
    'ff7a7a': 'var(--연한-빨강)',  # 2곳
    'fdecee': 'var(--연한-빨강)',  # 2곳
    'ffecec': 'var(--연한-빨강)',  # 2곳
    'f3b0b0': 'var(--연한-빨강)',  # 2곳
    'fbd5d5': 'var(--연한-빨강)',  # 2곳
    'fbd3d3': 'var(--연한-빨강)',  # 2곳
    'fbe9e9': 'var(--연한-빨강)',  # 2곳
    'f5c2c2': 'var(--연한-빨강)',  # 1곳
    'fdeeec': 'var(--연한-빨강)',  # 1곳
    'f5d3cd': 'var(--연한-빨강)',  # 1곳
    'f0a9a9': 'var(--연한-빨강)',  # 1곳
    'f7c9c9': 'var(--연한-빨강)',  # 1곳
    'ff9a9a': 'var(--연한-빨강)',  # 1곳
    'fcebeb': 'var(--연한-빨강)',  # 1곳
    'f7c1c1': 'var(--연한-빨강)',  # 1곳
    'fff0f1': 'var(--연한-빨강)',  # 1곳
    'ffeded': 'var(--연한-빨강)',  # 1곳
    'ffe9ec': 'var(--연한-빨강)',  # 1곳
    'fce6e6': 'var(--연한-빨강)',  # 1곳
    'f4c7cb': 'var(--연한-빨강)',  # 1곳
    'fdecef': 'var(--연한-빨강)',  # 1곳
    'ffeeee': 'var(--연한-빨강)',  # 1곳

    # T10 — 연한 초록 배경 — 롱테일
    'f0fdfa': 'var(--연한-초록)',  # 5곳
    '9be7c9': 'var(--연한-초록)',  # 4곳
    'eafbf0': 'var(--연한-초록)',  # 4곳
    '99f6e4': 'var(--연한-초록)',  # 4곳
    'e6f6ec': 'var(--연한-초록)',  # 4곳
    'e6f7f0': 'var(--연한-초록)',  # 3곳
    'bbf7d0': 'var(--연한-초록)',  # 3곳
    'e1f5ee': 'var(--연한-초록)',  # 3곳
    'eaf7ef': 'var(--연한-초록)',  # 3곳
    'c6e9d4': 'var(--연한-초록)',  # 3곳
    'e6fcf5': 'var(--연한-초록)',  # 3곳
    'e7f7ef': 'var(--연한-초록)',  # 2곳
    'b7ebc6': 'var(--연한-초록)',  # 2곳
    'e7f9ee': 'var(--연한-초록)',  # 2곳
    'e7f6ef': 'var(--연한-초록)',  # 2곳
    'e9f9ef': 'var(--연한-초록)',  # 1곳
    'd5efe0': 'var(--연한-초록)',  # 1곳
    'a7f3d0': 'var(--연한-초록)',  # 1곳
    'a7e8c0': 'var(--연한-초록)',  # 1곳
    'eafaf1': 'var(--연한-초록)',  # 1곳
    'e9fae6': 'var(--연한-초록)',  # 1곳
    'bfe6cd': 'var(--연한-초록)',  # 1곳
    'bbe6c9': 'var(--연한-초록)',  # 1곳
    '9ed6c1': 'var(--연한-초록)',  # 1곳
    'c7e9ce': 'var(--연한-초록)',  # 1곳
    'd1fae5': 'var(--연한-초록)',  # 1곳
    'ddf3e6': 'var(--연한-초록)',  # 1곳
    'ccfbf1': 'var(--연한-초록)',  # 1곳
    'c7edd9': 'var(--연한-초록)',  # 1곳
    'eaf8f1': 'var(--연한-초록)',  # 1곳
    '96f2d7': 'var(--연한-초록)',  # 1곳

    # T10 — 연한 주황 배경 — 롱테일
    'fff8e5': 'var(--연한-주황)',  # 4곳
    'fde9b5': 'var(--연한-주황)',  # 4곳
    'fff7e6': 'var(--연한-주황)',  # 3곳
    'faece7': 'var(--연한-주황)',  # 3곳
    'eacb8e': 'var(--연한-주황)',  # 3곳
    'fff7ed': 'var(--연한-주황)',  # 3곳
    'f5d99a': 'var(--연한-주황)',  # 3곳
    'fff4e5': 'var(--연한-주황)',  # 3곳
    'fff3bf': 'var(--연한-주황)',  # 2곳
    'ffe9a8': 'var(--연한-주황)',  # 2곳
    'fff8f1': 'var(--연한-주황)',  # 2곳
    'fffbf2': 'var(--연한-주황)',  # 2곳
    'fcd9a8': 'var(--연한-주황)',  # 2곳
    'fbebd3': 'var(--연한-주황)',  # 2곳
    'f3ddb4': 'var(--연한-주황)',  # 2곳
    'f3d9b0': 'var(--연한-주황)',  # 2곳
    'f3ebdd': 'var(--연한-주황)',  # 2곳
    'f1dfb0': 'var(--연한-주황)',  # 2곳
    'ffd8a8': 'var(--연한-주황)',  # 2곳
    'fff9db': 'var(--연한-주황)',  # 2곳
    'f2dca0': 'var(--연한-주황)',  # 1곳
    'f6eee6': 'var(--연한-주황)',  # 1곳
    'f6dfbb': 'var(--연한-주황)',  # 1곳
    'fff8e1': 'var(--연한-주황)',  # 1곳
    'fffbea': 'var(--연한-주황)',  # 1곳
    'fed7aa': 'var(--연한-주황)',  # 1곳
    'fff4e0': 'var(--연한-주황)',  # 1곳
    'faf0de': 'var(--연한-주황)',  # 1곳
    'fff6e9': 'var(--연한-주황)',  # 1곳
    'f3e2c6': 'var(--연한-주황)',  # 1곳
    'ebd6ae': 'var(--연한-주황)',  # 1곳
    'fff8db': 'var(--연한-주황)',  # 1곳
    'fcebd3': 'var(--연한-주황)',  # 1곳
    'fce4a6': 'var(--연한-주황)',  # 1곳
    'fff4e2': 'var(--연한-주황)',  # 1곳
    'fef4e6': 'var(--연한-주황)',  # 1곳
    'fff3e6': 'var(--연한-주황)',  # 1곳
    'fff3e0': 'var(--연한-주황)',  # 1곳
    'fff7f0': 'var(--연한-주황)',  # 1곳
    'f4d9be': 'var(--연한-주황)',  # 1곳
    'fff1e2': 'var(--연한-주황)',  # 1곳
    'fdf4e3': 'var(--연한-주황)',  # 1곳
    'e8c48a': 'var(--연한-주황)',  # 1곳
    'fdf4e6': 'var(--연한-주황)',  # 1곳
    'ffe8a3': 'var(--연한-주황)',  # 1곳

    # T10 — 연한 파랑 배경 — 롱테일
    'e8f3ff': 'var(--연한-파랑)',  # 5곳
    'e8f0fe': 'var(--연한-파랑)',  # 4곳
    'f3f8ff': 'var(--연한-파랑)',  # 4곳
    'c7e0ff': 'var(--연한-파랑)',  # 4곳
    'e8f2fe': 'var(--연한-파랑)',  # 3곳
    'c7dbff': 'var(--연한-파랑)',  # 3곳
    'bbd3f5': 'var(--연한-파랑)',  # 3곳
    'e6f0ff': 'var(--연한-파랑)',  # 3곳
    'cfe0ff': 'var(--연한-파랑)',  # 2곳
    'cfe1fb': 'var(--연한-파랑)',  # 2곳
    '9dc2ff': 'var(--연한-파랑)',  # 2곳
    '93c5fd': 'var(--연한-파랑)',  # 2곳
    'eeedfe': 'var(--연한-파랑)',  # 2곳
    'f0f9ff': 'var(--연한-파랑)',  # 2곳
    'bbd6ff': 'var(--연한-파랑)',  # 2곳
    'c5d9f7': 'var(--연한-파랑)',  # 2곳
    'e7f0fb': 'var(--연한-파랑)',  # 2곳
    'eaf2ff': 'var(--연한-파랑)',  # 2곳
    'd6e6ff': 'var(--연한-파랑)',  # 2곳
    'c5d8f0': 'var(--연한-파랑)',  # 1곳
    'eef2ff': 'var(--연한-파랑)',  # 1곳
    'e7f5ff': 'var(--연한-파랑)',  # 1곳
    'e0e7ff': 'var(--연한-파랑)',  # 1곳
    '7fb6ff': 'var(--연한-파랑)',  # 1곳
    'bcd8f4': 'var(--연한-파랑)',  # 1곳
    'e6edf6': 'var(--연한-파랑)',  # 1곳
    'd6e4ff': 'var(--연한-파랑)',  # 1곳
    'c9ddfb': 'var(--연한-파랑)',  # 1곳
    'c7d7fe': 'var(--연한-파랑)',  # 1곳
    'e0f2fe': 'var(--연한-파랑)',  # 1곳
    'c7dcfb': 'var(--연한-파랑)',  # 1곳
    'd8e6ff': 'var(--연한-파랑)',  # 1곳
    'c7d7f0': 'var(--연한-파랑)',  # 1곳
    'f0f6ff': 'var(--연한-파랑)',  # 1곳
    'e8f1fe': 'var(--연한-파랑)',  # 1곳
    '7dd3fc': 'var(--연한-파랑)',  # 1곳
    '9dc3f0': 'var(--연한-파랑)',  # 1곳
    'eaf1fb': 'var(--연한-파랑)',  # 1곳
    'dcebff': 'var(--연한-파랑)',  # 1곳
    'e7f0ff': 'var(--연한-파랑)',  # 1곳
}
# BRAND_KEEP 과 COLOR_MAP 이 겹치면 그 색은 영원히 치환되지 않는다 — 지금은
# 안 겹치는 게 맞는 상태이므로, 실수로 겹치면 즉시 알 수 있게 조기 경보를 둔다.
_OVERLAP = set(COLOR_MAP) & BRAND_KEEP
if _OVERLAP:  # pragma: no cover - 방어적 조기경보
    raise AssertionError(f'COLOR_MAP 과 BRAND_KEEP 이 겹침(둘 다 있으면 영원히 치환 안 됨): {_OVERLAP}')


# ── 정규식 ────────────────────────────────────────────────────────────
_STYLE_BLOCK_RE = re.compile(r'(<style\b[^>]*>)(.*?)(</style>)', re.IGNORECASE | re.DOTALL)
# style= 는 앞이 단어문자/하이픈이 아니어야 진짜 속성 이름이다 (data-style-x= 오탐 방지).
_STYLE_ATTR_RE = re.compile(
    r'(?<![\w-])(style\s*=\s*)("([^"]*)"|\'([^\']*)\')',
    re.IGNORECASE,
)
_JINJA_RE = re.compile(r'\{\{.*?\}\}|\{%.*?%\}', re.DOTALL)
# ★ 뒤에 hex 숫자뿐 아니라 「어떤 이름 글자도」 오면 안 된다.
#   hex 만 막았더니 id 선택자 `#acctline` 의 앞 세 글자 `#acc` 를 색으로 오인해
#   `var(--faint,#aacccc)tline` 으로 바꿔 CSS 규칙을 죽인 사고가 있었다
#   (orders/index.html 417행, 2026-07-31).
_HEX_RE = re.compile(r'#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})(?![0-9a-zA-Z_-])')
_VAR_NAME_RE = re.compile(r'^var\((--[^)]+)\)$')
_CUSTOM_PROP_NAME_RE = re.compile(r'(?:^|[;{])\s*(--[^:;{}\s]+)\s*:')


def _선언중인_커스텀프로퍼티(텍스트: str, pos: int) -> str | None:
    """pos 가 속한 CSS 선언의 좌변 프로퍼티 이름을 돌려준다.

    `--이름: 값` 형태의 커스텀 프로퍼티 선언이면 `--이름` 을, 일반 프로퍼티
    (color:/background: 등)거나 선언 경계 밖이면 None 을 돌려준다.

    세미콜론(;)은 CSS 문법상 괄호 안에 올 수 없으므로, "직전 ; 또는 {"부터
    "그다음 첫 :" 까지가 언제나 이 선언의 프로퍼티 이름이다 — 값 쪽에
    `var(--n200,#hex)` 처럼 중첩된 var() 폴백이 있어도 경계 탐색은 깨지지
    않는다(실측: orders/index.html `.cskb{--line:var(--n200,#E5E8EB)}` 처럼
    깊이 1의 중첩도 있었음 — 직전 텍스트만 보는 검사로는 못 잡았었다)."""
    boundary = max(텍스트.rfind(';', 0, pos), 텍스트.rfind('{', 0, pos))
    colon = 텍스트.find(':', boundary + 1, pos)
    if colon == -1:
        return None
    name = 텍스트[boundary + 1:colon].strip()
    return name if name.startswith('--') else None


def _로컬_커스텀프로퍼티_이름들(텍스트: str) -> Set[str]:
    """이 텍스트(<style> 블록 하나 또는 style="" 값 하나) 안에서 `--이름:` 으로
    직접 선언된 커스텀 프로퍼티 이름을 전부 모은다.

    self-reference(`--line:var(--line)`)뿐 아니라 서로 맞바꾸는 순환
    (`--line:var(--line2);--line2:var(--line);` — 실측: marketplace_guide/
    map.html .dm2)도 CSS 스펙상 똑같이 무효다. 정확한 그래프 순환 탐지 대신
    "이 블록에서 로컬로 다시 선언되는 이름이면, 다른 커스텀 프로퍼티 선언
    안에서 절대 var() 로 참조하지 않는다"는 보수적 규칙으로 두 경우 모두
    막는다 — 실제로 순환이 되는지 따지지 않고 애초에 만들지 않는다."""
    return {m.group(1) for m in _CUSTOM_PROP_NAME_RE.finditer(텍스트)}


def _정규화(hex6또는3: str) -> str:
    """대소문자 무관 + 3자리 축약을 6자리 소문자로 확장한다 (# 제외)."""
    h = hex6또는3.lower()
    if len(h) == 3:
        h = ''.join(ch * 2 for ch in h)
    return h


def _원본hex_확장(hex6또는3: str) -> str:
    """COLOR_MAP 조회용 `_정규화` 와 달리 대소문자는 원본 그대로 보존하고,
    3자리 축약만 6자리로 확장한다(# 제외) — var() 폴백 값으로 그대로 쓴다.

    COLOR_MAP 이 다대일(예: 191f28/292a2f/374151/333d4b 전부 →var(--ink))
    이라, 폴백은 변수의 "대표값"이 아니라 **이 자리에서 실제로 매치된
    원본 hex** 여야 한다 — 그래야 `current` 모드에서 사이트별로 원래
    보이던 색이 한 치의 차이 없이 그대로 복원된다."""
    if len(hex6또는3) == 3:
        return ''.join(ch * 2 for ch in hex6또는3)
    return hex6또는3


def _이미_같은토큰의_폴백인가(텍스트: str, target: str, m: 're.Match[str]') -> bool:
    """이 hex 매치가 이미 `var(--타겟이름,` 바로 뒤 · `)` 바로 앞에 있는가.

    설계 판단 — 스윕은 멱등이어야 한다: COLOR_MAP 이 새 색으로 커지면(Job 2
    롱테일 추가) 운영자는 "다시 훑기(stage A)"를 그대로 재실행하게 된다.
    그런데 이전 실행이 이미 `#191f28` 을 `var(--ink,#191f28)` 로 바꿔 놓은
    자리에 재실행을 그대로 적용하면, 폴백 안의 `#191f28` 이 다시 매치되어
    `var(--ink,var(--ink,#191f28))` 처럼 **이중으로 감싸진다**(실측:
    색치환('<div style="color:var(--ink,#191f28)">x</div>') 로 직접 재현).
    무해해 보이지만 실행할 때마다 감싸는 깊이가 계속 늘어나는 데다, 실행
    시점에 따라 같은 화면의 diff 가 달라지는 건 이 스크립트가 절대 허용하면
    안 되는 것이다.

    반대로 무조건 "var() 안이면 건드리지 않는다"로 막으면, 템플릿이 원래
    손으로 짜둔 서로 다른 변수 이름의 중첩 폴백(예:
    `--sub2:var(--n500,#8b95a1)` 의 `#8b95a1` 은 var(--sub) 로 치환돼야
    한다 — 바깥 var 이름(--n500)과 이 색이 매핑되는 목표 이름(--sub)이
    다르므로 새로운 정보다)까지 막아버려 T7 때부터 있던 정상 동작
    (test_중첩_var_폴백이라도_다른_이름이면_바뀐다)이 깨진다.

    그래서 "안쪽 var() 전체를 건드리지 않는다"가 아니라, **바로 이 자리가
    이미 정확히 같은 타겟 이름의 폴백 위치인가**만 좁게 확인한다 — 그래야
    "이미 끝난 자리"만 정확히 건너뛰고, 새로 채워야 할 자리는 그대로 잡는다.
    """
    var_m = _VAR_NAME_RE.match(target)
    if not var_m:
        return False
    이름 = var_m.group(1)  # 예: '--ink'
    # 매치 바로 뒤가 ')' 여야 "이 var() 호출의 폴백 값 전체"라고 확신할 수 있다.
    if 텍스트[m.end():m.end() + 1] != ')':
        return False
    # 매치 바로 앞이 'var(<공백>--이름<공백>,<공백>' 로 끝나는지 — 뒤에서부터
    # 확인하면 충분하다(앞쪽 문맥은 상관없다). 너무 먼 과거까지 훑지 않게
    # 이 var() 호출이 시작될 만한 합리적 길이로 앞부분만 잘라서 본다.
    앞부분 = 텍스트[max(0, m.start() - 80):m.start()]
    패턴 = re.compile(r'var\(\s*' + re.escape(이름) + r'\s*,\s*$')
    return bool(패턴.search(앞부분))


def _css값_치환(텍스트: str) -> Tuple[str, int]:
    """style="" 값 하나 또는 <style> 블록 하나의 내용에 대해서만 색을 치환한다.

    Jinja 델리미터({{ }} / {% %}) 안쪽은 건드리지 않는다.
    """
    protected: List[Tuple[int, int]] = [(m.start(), m.end()) for m in _JINJA_RE.finditer(텍스트)]

    def _보호됨(pos: int) -> bool:
        return any(s <= pos < e for s, e in protected)

    # 이 블록/속성값 안에서 로컬로 (재)선언되는 커스텀 프로퍼티 이름 전체.
    # 자기참조·순환참조 방지 규칙(아래 _repl)이 참조한다.
    로컬_커스텀프로퍼티 = _로컬_커스텀프로퍼티_이름들(텍스트)

    count = 0

    def _repl(m: 're.Match[str]') -> str:
        nonlocal count
        if _보호됨(m.start()):
            return m.group(0)
        원본 = m.group(1)
        norm = _정규화(원본)
        if norm in BRAND_KEEP:
            return m.group(0)
        target = COLOR_MAP.get(norm)
        if target is None:
            return m.group(0)
        # 멱등성: 이미 이 hex 가 같은 타겟의 var() 폴백 자리면 다시 감싸지
        # 않는다(재실행 시 이중 래핑 방지 — 근거는 함수 docstring 참고).
        if _이미_같은토큰의_폴백인가(텍스트, target, m):
            return m.group(0)
        # 커스텀 프로퍼티 *선언*의 값(중첩 var() 폴백 포함)이 이 블록에서
        # 로컬로 재선언되는 이름을 가리키게 되면 건드리지 않는다. 템플릿마다
        # --ink/--sub/--line 같은 이름으로 자기만의 로컬 팔레트를 이미
        # 선언해둔 곳이 있다(예: .pvfpage{--ink:#191F28;...},
        # .cskb{--line:var(--n200,#E5E8EB)}, .dm2{--line:#F1F3F5;--line2:#E5E8EB}).
        # 이걸 그대로 var() 로 바꾸면 `--ink:var(--ink)` 같은 자기참조는 물론,
        # `--line:var(--line2);--line2:var(--line);` 처럼 서로 맞바꾸는
        # 순환참조도 생긴다 — 둘 다 CSS 스펙상 무효(guaranteed-invalid)가
        # 되어 화면이 조용히 깨진다(실측: T7 1차 적용에서 8개 파일 43곳
        # 발견, 되돌림). 정확한 순환 여부를 따지지 않고, 이 블록에서 로컬로
        # 다시 선언되는 이름이면 무조건 보수적으로 막는다. 이런 자리는
        # 하드코딩 값 그대로 둔다 — 실제 CSS *사용* 자리(color:/background:
        # 등)만 치환 대상이다.
        선언_프로퍼티 = _선언중인_커스텀프로퍼티(텍스트, m.start())
        if 선언_프로퍼티 is not None:
            var_m = _VAR_NAME_RE.match(target)
            if var_m and var_m.group(1) in 로컬_커스텀프로퍼티:
                return m.group(0)
        count += 1
        # 예비값(fallback) 부착: `current` 모드에선 --ink 등이 정의되지
        # 않으므로 브라우저가 두 번째 인자를 그대로 쓴다 — 즉 이 자리는
        # 스윕 전과 픽셀 단위로 동일하게 보인다. `ds` 모드에선 변수가
        # 정의돼 있어 폴백은 무시되고 애플 팔레트가 이긴다. 콤마 뒤 공백
        # 없음(diff 최소화) — target 은 항상 'var(--이름)' 형태(끝이 ')').
        폴백 = _원본hex_확장(원본)
        return target[:-1] + ',#' + 폴백 + ')'

    새텍스트 = _HEX_RE.sub(_repl, 텍스트)
    return 새텍스트, count


def _색치환_및_카운트(본문: str) -> Tuple[str, int]:
    total = 0

    def _style_block(m: 're.Match[str]') -> str:
        nonlocal total
        open_tag, content, close_tag = m.group(1), m.group(2), m.group(3)
        new_content, c = _css값_치환(content)
        total += c
        return open_tag + new_content + close_tag

    본문 = _STYLE_BLOCK_RE.sub(_style_block, 본문)

    def _style_attr(m: 're.Match[str]') -> str:
        nonlocal total
        prefix = m.group(1)
        quoted = m.group(2)
        if quoted.startswith('"'):
            inner = m.group(3) or ''
            new_inner, c = _css값_치환(inner)
            total += c
            return f'{prefix}"{new_inner}"'
        else:
            inner = m.group(4) or ''
            new_inner, c = _css값_치환(inner)
            total += c
            return f"{prefix}'{new_inner}'"

    본문 = _STYLE_ATTR_RE.sub(_style_attr, 본문)
    return 본문, total


def 색치환(본문: str) -> str:
    """style="" 값과 <style> 블록 안의 CSS 색만 COLOR_MAP 기준으로 치환한다.

    class=/id=/data-*, <script> 안의 JS, Jinja 태그 안쪽은 절대 건드리지 않는다.
    BRAND_KEEP 의 색과 COLOR_MAP 에 없는 색은 그대로 둔다.
    """
    새본문, _ = _색치환_및_카운트(본문)
    return 새본문


# ═══════════════════════════════════════════════════════════════════════
# T11(Job3) — 위험 9개 파일의 <style> 블록만 치환 (inline style="" 은 절대 안 건드림)
#
# SKIP_FILES 9개는 통째로 스윕 대상에서 빠져 있었다 — JS 가 색을 읽는 자리가
# 있어서다. 그런데 위험은 "이 파일에 색이 있다"가 아니라 훨씬 좁다:
# `el.style.color` 처럼 인라인 style="" 값을 **문자열 그대로** 읽는 코드가
# `var(--x,#hex)` 로 바뀐 값을 만나면 기대와 다른 문자열을 돌려받는다(스펙상
# style 프로퍼티 접근자는 지정값을 그대로 반환한다 — resolved 되지 않는다).
# 반면 `<style>` 블록의 규칙은 getComputedStyle() 이 항상 결과를 rgb() 로
# 계산해 돌려주므로 var() 로 바꿔도 읽는 쪽 코드는 그대로 동작한다.
#
# 실측(9개 파일 전수 grep, `.style.<color계열속성>` 읽기 자리·getComputedStyle·
# jQuery .css('color'/'background') 전부 확인):
#   - 색을 실제로 "읽는"(rvalue) 코드는 bundles/_matrix_v3.html 의 마켓 로고
#     팝오버 한 곳뿐 — `window.getComputedStyle(box).backgroundColor` 로
#     계산된 값을 읽는다. 이 요소(.mkt-logo-box)의 배경색은 항상 인라인
#     `style="...background:{{ mk.logo_color }};..."` 로만 채워지는 Jinja
#     동적 값이라(DB 저장 사용자 지정색), 애초에 스캔 범위(literal hex)
#     밖이고 <style> 블록과 무관하다 — 이 치환으로 절대 안 깨진다.
#   - 나머지 8개 파일과 _matrix_v3.html 의 다른 자리들은 전부 `.style.X = …`
#     (쓰기)뿐이며, 이는 `<script>` 안 JS 리터럴이라 스캔 범위(style=""
#     속성/<style> 블록) 밖이라 처음부터 안전하다.
#   → 9개 파일 전부 <style> 블록만 치환해도 안전하다고 판단, 전부 포함한다.
# ═══════════════════════════════════════════════════════════════════════

def _스타일블록만_치환_및_카운트(본문: str) -> Tuple[str, int]:
    """<style> 블록 안의 CSS 색만 치환한다 — style="" 속성은 절대 건드리지 않는다.

    _색치환_및_카운트 와 달리 `_STYLE_ATTR_RE.sub` 단계를 아예 실행하지 않는다
    (호출 자체를 생략 — 부분적으로 스캔한 뒤 버리는 게 아니라 애초에 안 본다).
    """
    total = 0

    def _style_block(m: 're.Match[str]') -> str:
        nonlocal total
        open_tag, content, close_tag = m.group(1), m.group(2), m.group(3)
        new_content, c = _css값_치환(content)
        total += c
        return open_tag + new_content + close_tag

    본문 = _STYLE_BLOCK_RE.sub(_style_block, 본문)
    return 본문, total


def 스타일블록만_색치환(본문: str) -> str:
    """<style> 블록 안의 색만 COLOR_MAP 기준으로 치환한다. style="" 속성,
    class=/id=/data-*, <script> 안 JS, Jinja 태그 안쪽은 전부 그대로 둔다.

    위험 9개 파일(SKIP_FILES) 전용 — JS 가 인라인 style="" 을 문자열 그대로
    읽는 자리가 있어 그 부분은 절대 건드리면 안 되지만, <style> 블록 규칙은
    getComputedStyle() 로만 읽히므로 안전하다(근거는 모듈 위 docstring).
    """
    새본문, _ = _스타일블록만_치환_및_카운트(본문)
    return 새본문


def 스타일블록만_흰배경_서페이스로(본문: str) -> str:
    """<style> 블록 안의 `background:#fff` 만 `var(--surface,#fff)` 로 바꾼다.

    [2026-07-31] 왜 따로 필요한가 —
      흰색은 COLOR_MAP 에 **일부러 없다**(같은 #fff 가 바탕일 수도 글자일 수도 있어
      기계적으로 못 정한다). 그래서 D단계가 `background:` 선언 안일 때만 바꾼다.
      그런데 위험 9개 파일에는 D단계가 안 걸려 있었다 — `--risky-style-only` 는
      COLOR_MAP 치환만 했기 때문이다.
      그 결과 마진계산기의 `.card{background:#FFFFFF}` 같은 흰 판이 검정 타입에서
      그대로 남았다(라이브 실측: 위험파일 <style> 에만 197곳).

      style="" 속성은 여기서도 안 건드린다 — JS 가 그 문자열을 읽는 자리가 있다.
      <style> 블록 규칙은 getComputedStyle() 로만 읽히므로 안전하다.
    """
    def _style_block(m: 're.Match[str]') -> str:
        open_tag, content, close_tag = m.group(1), m.group(2), m.group(3)
        new_content, _ = _흰배경_서페이스로(content)
        return open_tag + new_content + close_tag

    return _STYLE_BLOCK_RE.sub(_style_block, 본문)


def 위험파일_스타일블록만_훑기(적용: bool) -> '훑기결과':
    """SKIP_FILES 9개만 대상으로, <style> 블록의 색만 치환한다.

    일반 훑기() 는 SKIP_FILES 를 읽지도 않고 건너뛴다 — 이 함수는 그 9개를
    **일부러** 열어서 <style> 블록만 좁게 훑는 별도 경로다. style="" 속성은
    이 함수 경로에서 절대 스캔되지 않는다(위 _스타일블록만_치환_및_카운트).
    """
    결과 = 훑기결과(적용=적용, 단계='위험9-style만')

    if not TEMPLATES_DIR.exists():
        return 결과

    for rel in sorted(SKIP_FILES):
        path = TEMPLATES_DIR / rel
        if not path.exists():
            continue
        결과.스캔파일수 += 1
        원본 = path.read_text(encoding='utf-8')
        새본문, count = _스타일블록만_치환_및_카운트(원본)
        if count > 0:
            결과.변경파일수 += 1
            결과.총치환수 += count
            결과.파일별.append(파일결과(경로=rel, 치환수=count))
            if 적용:
                path.write_text(새본문, encoding='utf-8')

    return 결과


# ═══════════════════════════════════════════════════════════════════════
# T8 B단계 — 그림자 제거 · 음수 자간 0 · 12px 미만 올림
# T9 C단계 — 글자크기 7등급 · 여백 7단 · 둥근모서리 4단
#
# 색치환과 같은 스캔 범위(style="" 값 / <style> 블록만)를 그대로 재사용한다
# (아래 _단계별_치환). class=/id=/data-*, <script> 안 JS, Jinja 태그 안쪽은
# 애초에 이 스캔 범위 밖이라 구조적으로 안전하다.
#
# ── 그림자(B단계) 설계 판단 — border 로 안 바꾸고 아예 지운다 ─────────
# 원래 지시는 "box-shadow → border:1px solid var(--line)" 였다. 그런데
# 실측(webapp/templates 전수 grep)해 보니 그림자 208곳 중 76곳이 같은
# 선언 블록 안에 이미 border 계열 속성(border/border-color 등)을 갖고
# 있었고, 그중 실제 사례가 이렇다:
#
#   accounts/crawl_login.html
#   .cl-inp:focus{outline:none;border-color:var(--color-primary);
#                 box-shadow:0 0 0 3px var(--color-primary-light)}
#
# 여기서 box-shadow 자리에 `border:1px solid var(--line)` 를 새로 붙이면,
# CSS 단축(shorthand) 속성 규칙상 `border:` 는 border-color/width/style을
# 전부 초기화한다 — 즉 방금 지정한 `border-color:var(--color-primary)`
# (포커스 강조색)가 뒤에 오는 새 border 선언에 조용히 덮여 사라진다.
# 포커스 인디케이터가 회색으로 뭉개지는 실제 시각 버그다.
#
# 나머지도 상당수(예: accounts/sourcing.html .sj-status-dot.ok/.fail/.warn
# 의 상태색 헤일로 링, .dot.run 의 포커스 링)가 "카드 깊이"가 아니라
# "상태·포커스를 색으로 알려주는 헤일로" 용도다. 이런 자리를 일괄
# `var(--line)` 회색 테두리로 바꾸면 상태 구분에 쓰던 의미(초록=정상,
# 빨강=실패 등)가 사라진다.
#
# → border 를 새로 추가하지 않고 box-shadow 선언 자체를 지운다.
#   - box-shadow 는 원래 레이아웃에 영향이 없는 속성이므로(요소 바깥에
#     그려질 뿐 박스 크기·위치를 바꾸지 않는다), 제거해도 레이아웃
#     변화가 없다 — border 를 새로 추가하는 것과 달리 안전이 자명하다.
#   - 이미 border 를 가진 76곳은 그 border 가 그대로 "그림자 대신 1px
#     선으로 층을 만든다"는 규칙(docs/디자인-규칙.md)을 충족한다.
#   - border 가 없던 나머지는 그림자만 사라져 다소 밋밋해질 수는
#     있어도, 값을 덮어쓰거나 색 의미를 훼손하는 깨짐은 없다.
#   - 단축속성 override·이중 테두리·상태색 훼손 위험을 전부 원천
#     차단하면서, "그림자를 쓰지 않는다"는 규칙 자체는 완전히 지킨다.
#
# ── 둥근모서리(C단계) 알약 경계 — 100px 대신 50px ─────────────────────
# 지시문은 "100px 이상은 알약이라 안 건드린다" 였다. 그런데 실측하니
# 99px 값이 22곳이나 실사용 중이었다(예: bundles/new.html
# .pc-cnt{padding:1px 11px;border-radius:99px}, inventory/data/items.html
# 배지 등) — 전부 padding 1~3px 짜리 작은 배지라 99px 은 명백히 "무조건
# 알약이 되게" 쓴 관용 값이다(요소 높이가 반지름보다 작으면 CSS 는
# 자동으로 완전히 둥글게 클램프한다). 이걸 4단 반올림(→18px)하면 배지가
# 전부 각진 모양으로 바뀌어 눈에 띄게 깨진다.
#   실측값 분포를 보면 30px 다음이 바로 99px 이라 30~98 구간이
#   완전히 비어 있다 — 경계를 100 대신 50 으로 낮춰도 반올림 대상
#   (30px 이하, 애플 실측 카드 라운드 값들)에는 전혀 영향이 없고
#   99px/999px 알약만 안전하게 보존된다.
# ═══════════════════════════════════════════════════════════════════════

_VAR_CALC_RE = re.compile(r'(?:var|calc)\(', re.IGNORECASE)


def _보호구간(텍스트: str) -> List[Tuple[int, int]]:
    """이 텍스트 안에서 절대 값 취급으로 건드리면 안 되는 구간을 모은다.

    Jinja 델리미터({{ }}/{% %}) 안쪽 + var(...)/calc(...) 안쪽(중첩 포함).
    실측: bundles/edit.html `font-size: var(--fs-h3, 19px)` 처럼 var() 의
    폴백 값으로 px 리터럴이 들어있는 자리가 실재해서, 숫자만 보고
    치환하면 변수 선언 자체가 깨진다."""
    spans = [(m.start(), m.end()) for m in _JINJA_RE.finditer(텍스트)]
    for m in _VAR_CALC_RE.finditer(텍스트):
        depth = 1
        j = m.end()
        n = len(텍스트)
        while j < n and depth > 0:
            if 텍스트[j] == '(':
                depth += 1
            elif 텍스트[j] == ')':
                depth -= 1
            j += 1
        spans.append((m.start(), j))
    return spans


def _구간에_보호됨(spans: List[Tuple[int, int]], pos: int) -> bool:
    return any(s <= pos < e for s, e in spans)


def _가까운값(v: float, steps: Tuple[float, ...]) -> float:
    """steps(오름차순) 중 v 에 가장 가까운 값. 동률이면 작은 쪽(steps 에서
    먼저 나오는 쪽)을 돌려준다 — "애매하면 작은 쪽" 규칙(디자인-규칙.md)."""
    best = steps[0]
    best_d = abs(v - best)
    for s in steps[1:]:
        d = abs(v - s)
        if d < best_d:
            best = s
            best_d = d
    return best


# ── B단계 : 그림자 제거 ────────────────────────────────────────────────
# 셀렉터 오탐 방지: 앞이 단어문자/하이픈이면 진짜 속성 선언이 아니다
# (예: 벤더 접두사 -webkit-box-shadow, 혹은 이름이 우연히 겹치는 선택자).
# 값 쪽 문자 클래스에 큰따옴표/작은따옴표도 방어적으로 제외해 둔다 — 이
# 함수는 항상 _단계별_치환 을 통해 style="" 값 하나로 격리된 다음에만
# 호출돼야 하지만(따옴표 밖으로 넘어갈 일이 구조적으로 없어야 하지만),
# 실제로 이 격리를 건너뛰고 원본 HTML 전체에 바로 돌리는 실수가 났을 때
# (실측: 최초 훑기() 배선 버그 — box-shadow 가 style="" 의 마지막 선언이면
# 닫는 따옴표를 세미콜론이 아니라며 그냥 건너뛰어 다음 태그의 style="" 속성
# 시작부까지 통째로 먹어버렸다 — inventory/adjust/form.html 등 7개 파일에서
# 실측) 따옴표를 만나면 더는 못 넘어가게 이중으로 막는다.
_SHADOW_RE = re.compile(
    r'(?<![\w-])box-shadow\s*:\s*(?!none\b)[^;{}"\']+;?', re.IGNORECASE,
)


def _그림자_제거(텍스트: str) -> Tuple[str, int]:
    spans = _보호구간(텍스트)
    count = 0

    def _repl(m: 're.Match[str]') -> str:
        nonlocal count
        if _구간에_보호됨(spans, m.start()):
            return m.group(0)
        count += 1
        return ''

    return _SHADOW_RE.sub(_repl, 텍스트), count


# ── B단계 : 음수 자간 → 0 ──────────────────────────────────────────────
_NEG_LS_RE = re.compile(
    r'(?<![\w-])(letter-spacing\s*:\s*)-[\d.]+(?:em|px|rem|%)?', re.IGNORECASE,
)


def _음수자간_0으로(텍스트: str) -> Tuple[str, int]:
    spans = _보호구간(텍스트)
    count = 0

    def _repl(m: 're.Match[str]') -> str:
        nonlocal count
        if _구간에_보호됨(spans, m.start()):
            return m.group(0)
        count += 1
        return m.group(1) + '0'

    return _NEG_LS_RE.sub(_repl, 텍스트), count


# ── B단계/C단계 공용 : font-size 리터럴 매치 ───────────────────────────
_FS_RE = re.compile(
    r'(?<![\w-])(font-size\s*:\s*)([\d.]+)px', re.IGNORECASE,
)


def _최소글자_11로(텍스트: str) -> Tuple[str, int]:
    spans = _보호구간(텍스트)
    count = 0

    def _repl(m: 're.Match[str]') -> str:
        nonlocal count
        if _구간에_보호됨(spans, m.start()):
            return m.group(0)
        v = float(m.group(2))
        # [2026-08-13 사장님] 바닥선 11 → 12. 실측: 11px 가 1,086곳으로 제일 많았고
        #   「판매중」 같은 딱지가 안 보인다는 지적이 나왔다. 12 는 이미 이 프로그램에서
        #   가장 흔한 크기라 표가 벌어질 위험이 가장 낮다.
        if v >= 12:
            return m.group(0)
        count += 1
        return m.group(1) + '12px'

    return _FS_RE.sub(_repl, 텍스트), count


def _B단계_및_카운트(텍스트: str) -> Tuple[str, int]:
    total = 0
    텍스트, c = _그림자_제거(텍스트); total += c
    텍스트, c = _음수자간_0으로(텍스트); total += c
    텍스트, c = _최소글자_11로(텍스트); total += c
    return 텍스트, total


def _B단계_적용_및_카운트(본문: str) -> Tuple[str, int]:
    """훑기() 가 쓰는 진입점. style="" 값/<style> 블록으로 격리한 뒤에만
    _B단계_및_카운트 를 호출한다 — 절대 원본 HTML 전체에 바로 돌리지 않는다
    (이 격리를 건너뛰면 실측 버그가 재현된다: box-shadow 가 style="" 의
    마지막 선언일 때 닫는 따옴표를 못 넘어야 할 것을 넘어가 다음 태그의
    속성까지 먹어버린다)."""
    return _단계별_치환(본문, _B단계_및_카운트)


def B단계(본문: str) -> str:
    """그림자 제거 · 음수 자간 0 · 12px 미만 글자를 12px로 올린다.

    스캔 범위는 색치환과 동일(style="" 값 / <style> 블록만) — class=/id=/
    data-*, <script> 안 JS, Jinja 태그 안쪽은 건드리지 않는다.
    """
    새본문, _ = _B단계_적용_및_카운트(본문)
    return 새본문


# ── C단계 : 글자크기 7등급 ──────────────────────────────────────────────
_FS_STEPS: Tuple[float, ...] = (11, 12, 14, 17, 24, 32, 48)


def _글자크기_7단(텍스트: str) -> Tuple[str, int]:
    spans = _보호구간(텍스트)
    count = 0

    def _repl(m: 're.Match[str]') -> str:
        nonlocal count
        if _구간에_보호됨(spans, m.start()):
            return m.group(0)
        v = float(m.group(2))
        target = _가까운값(v, _FS_STEPS)
        if target == v:
            return m.group(0)
        count += 1
        return m.group(1) + ('%gpx' % target)

    return _FS_RE.sub(_repl, 텍스트), count


# ── C단계 : 여백(padding/margin/gap, 방향별 포함) 7단 ──────────────────
# 선택자 오탐 방지(예: 가상의 `.mypadding:hover{...}`)를 위해 앞이
# 단어문자/하이픈이면 매치하지 않는다. column-gap/row-gap 은 명시적으로
# 별도 브랜치로 포함한다(gap 의 하이픈 접두사라 위 lookbehind 만으로는
# 안 잡히므로).
_SP_DECL_RE = re.compile(
    r'(?<![\w-])((?:column-gap|row-gap|padding|margin|gap)'
    r'(?:-(?:top|right|bottom|left))?\s*:\s*)([^;"\'}\n]+)',
    re.IGNORECASE,
)
_PX_TOKEN_RE = re.compile(r'(-?[\d.]+)px')
_SP_STEPS: Tuple[float, ...] = (0, 4, 8, 12, 16, 24, 32, 48)


def _여백_7단(텍스트: str) -> Tuple[str, int]:
    count = 0

    def _decl_repl(m: 're.Match[str]') -> str:
        nonlocal count
        prefix, value = m.group(1), m.group(2)
        local_spans = _보호구간(value)

        def _token_repl(tm: 're.Match[str]') -> str:
            nonlocal count
            if _구간에_보호됨(local_spans, tm.start()):
                return tm.group(0)
            v = float(tm.group(1))
            sign = -1 if v < 0 else 1
            target = sign * _가까운값(abs(v), _SP_STEPS)
            if target == v:
                return tm.group(0)
            count += 1
            return ('%g' % target) + 'px'

        return prefix + _PX_TOKEN_RE.sub(_token_repl, value)

    return _SP_DECL_RE.sub(_decl_repl, 텍스트), count


# ── C단계 : 둥근모서리 4단 (알약 값은 보존) ─────────────────────────────
_RAD_DECL_RE = re.compile(
    r'(?<![\w-])(border-radius\s*:\s*)([^;"\'}\n]+)', re.IGNORECASE,
)
_RAD_STEPS: Tuple[float, ...] = (0, 8, 12, 18)
_RAD_알약_경계 = 50  # 이 값 이상은 알약(pill) 의도로 보고 안 건드린다(사유는 모듈 docstring)


def _둥근모서리_4단(텍스트: str) -> Tuple[str, int]:
    count = 0

    def _decl_repl(m: 're.Match[str]') -> str:
        nonlocal count
        prefix, value = m.group(1), m.group(2)
        local_spans = _보호구간(value)

        def _token_repl(tm: 're.Match[str]') -> str:
            nonlocal count
            if _구간에_보호됨(local_spans, tm.start()):
                return tm.group(0)
            v = float(tm.group(1))
            if v < 0 or v >= _RAD_알약_경계:
                return tm.group(0)
            target = _가까운값(v, _RAD_STEPS)
            if target == v:
                return tm.group(0)
            count += 1
            return ('%g' % target) + 'px'

        return prefix + _PX_TOKEN_RE.sub(_token_repl, value)

    return _RAD_DECL_RE.sub(_decl_repl, 텍스트), count


def _C단계_및_카운트(텍스트: str) -> Tuple[str, int]:
    total = 0
    텍스트, c = _글자크기_7단(텍스트); total += c
    텍스트, c = _여백_7단(텍스트); total += c
    텍스트, c = _둥근모서리_4단(텍스트); total += c
    return 텍스트, total


def _C단계_적용_및_카운트(본문: str) -> Tuple[str, int]:
    """훑기() 가 쓰는 진입점. _B단계_적용_및_카운트 와 동일한 이유로 반드시
    _단계별_치환 을 거친다."""
    return _단계별_치환(본문, _C단계_및_카운트)


def C단계(본문: str) -> str:
    """font-size 를 7등급, padding/margin/gap 을 7단, border-radius 를
    4단(알약값 제외)으로 반올림한다. 스캔 범위는 B단계와 동일."""
    새본문, _ = _C단계_적용_및_카운트(본문)
    return 새본문


# ═══════════════════════════════════════════════════════════════════════
# D단계 — 흰 배경(#fff/#ffffff)만 서페이스 토큰으로. 글자색은 절대 안 건드림.
#
# 배경: A단계(색치환)는 #ffffff/#000000 을 처음부터 COLOR_MAP·스캔에서
# 제외했다 — 이 두 값은 「배경」으로도 「색이 칠해진 요소 위의 글자색」으로도
# 둘 다 쓰이는데, 하나의 토큰(--surface)이 두 역할을 동시에 만족할 수 없어서다
# (실측: 버튼 위 흰 글자 color:#fff 를 var(--surface) 로 바꾸면 다크모드에서
# --surface 가 #1D1D1F 로 바뀌어 버튼 글자가 그 버튼 배경과 같은 색이 되어
# 사라진다 — 정반대 방향의 새 무자비 버그).
#
# 그런데 그 제외가 만든 사각지대가 이번 실측 결함의 절반이다: 카드가
# `background:#fff` 로 하드코딩된 채 다크모드에 들어가면, 카드 배경은
# 흰색 그대로 남고 글자만 --ink(다크에선 밝은색)로 바뀌어 흰 바탕에 밝은
# 글자 = 사실상 안 보인다(89~134곳/모드, 사장님 실측).
#
# → 속성을 구분해서 다시 훑는다:
#   - background / background-color 선언 **안**의 #fff·#ffffff 만
#     var(--surface,#원본) 로 바꾼다 — 배경은 명확히 "카드/페이지 표면" 역할.
#   - color: 선언 안의 #fff 는 절대 안 건드린다 — 색 있는 버튼 위 흰 글자처럼
#     "배경과 무관하게 항상 흰 글자여야 하는" 자리라 --surface 로 바꾸면
#     다크모드에서 버튼과 같은 색이 되어 사라진다(위 사각지대와 반대 방향의
#     동일한 버그를 새로 만들게 된다).
#   - background-image/-position/-size/-attachment/-repeat/-clip/-origin
#     처럼 "background" 로 시작하지만 실제로는 배경색이 아닌 속성은
#     프로퍼티 이름 매칭 자체에서 제외한다(정규식이 뒤에 다른 글자가
#     오면 실패하도록 구성 — background-color 만 별도로 허용).
#   - var(...)/calc(...) 안(중첩 포함)의 #fff 는 이미 치환된 자리이므로
#     다시 감싸지 않는다(B/C단계와 같은 _보호구간 재사용 — 재실행 시
#     이중 래핑을 막아 멱등을 보장한다).
#   - 커스텀 프로퍼티 *선언*(`--surface:#fff` 처럼 프로퍼티 이름이
#     `--`로 시작하는 자리)은 이 정규식이 애초에 매치하지 않는다 —
#     매칭 대상 프로퍼티 이름이 정확히 "background"/"background-color"
#     뿐이라 구조적으로 자기참조·순환을 만들 수 없다.
#
# background:#000000(검정 배경)은 이 단계에서 일부러 안 건드린다 — #fff 와
# 달리 검정 배경은 이번에 실측된 결함(카드가 계속 희게 남아 밝은 글자가
# 묻히는 것)을 일으키지 않는다(다크모드 자체가 --bg:#000 이라 이미 어울림).
# 반대로 #000 을 var(--surface,#000) 로 바꾸면, 라이트 .ds 모드에서
# --surface 가 #FFFFFF 가 되어 "의도적으로 검정으로 고정한" 요소(예:
# 테마와 무관하게 항상 검정인 배지·오버레이)가 갑자기 흰 배경이 되고,
# 그 위에 원래 있던 흰 글자(color:#fff, 이 단계가 안 건드리는 자리)가
# 그대로 남아 흰 바탕에 흰 글자 — 지금 고치는 결함을 반대 방향으로
# 재현하게 된다. 정적 정규식만으로는 "페이지 배경 대역"과 "항상 검정인
# 요소"를 구별할 수 없어, 확신 없는 치환보다 안 건드리는 쪽을 택한다.
# ═══════════════════════════════════════════════════════════════════════

_WHITE_BG_DECL_RE = re.compile(
    r'(?<![\w-])(background(?:-color)?\s*:\s*)([^;"\'}\n]+)', re.IGNORECASE,
)
# [2026-08-01] `white` 라는 **이름**으로 적힌 흰색도 잡는다.
#   `#fff` 만 보다가 `background: white` 를 통째로 놓쳤다 —
#   판매처 계정 화면의 바깥 판(.up-shell)이 검정 타입에서 흰색으로 남아
#   그 위 글자가 대비 1.09 가 됐다(실측).
_WHITE_HEX_TOKEN_RE = re.compile(r'#(fff|ffffff)(?![0-9a-zA-Z_-])|(?<![-\w])white(?![-\w])',
                                 re.IGNORECASE)


def _흰배경_서페이스로(텍스트: str) -> Tuple[str, int]:
    count = 0

    def _decl_repl(m: 're.Match[str]') -> str:
        nonlocal count
        prefix, value = m.group(1), m.group(2)
        local_spans = _보호구간(value)  # var()/calc() 중첩 + Jinja 보호 재사용

        def _token_repl(tm: 're.Match[str]') -> str:
            nonlocal count
            if _구간에_보호됨(local_spans, tm.start()):
                return tm.group(0)
            원본 = tm.group(1)
            count += 1
            if 원본 is None:            # `white` 라는 이름으로 적힌 경우
                return 'var(--surface,#FFFFFF)'
            return 'var(--surface,#' + _원본hex_확장(원본) + ')'

        return prefix + _WHITE_HEX_TOKEN_RE.sub(_token_repl, value)

    return _WHITE_BG_DECL_RE.sub(_decl_repl, 텍스트), count


def _D단계_및_카운트(텍스트: str) -> Tuple[str, int]:
    return _흰배경_서페이스로(텍스트)


def _D단계_적용_및_카운트(본문: str) -> Tuple[str, int]:
    """훑기() 가 쓰는 진입점. B/C단계와 동일하게 반드시 _단계별_치환 을 거쳐
    style="" 값 / <style> 블록으로 격리한 뒤에만 정규식을 돌린다."""
    return _단계별_치환(본문, _D단계_및_카운트)


def D단계(본문: str) -> str:
    """background/background-color 선언 안의 #fff·#ffffff 만
    var(--surface,#원본) 로 바꾼다. color: 안의 #fff·#ffffff, 그리고
    background:#000/#000000 은 이 단계에서 절대 안 건드린다(사유는
    모듈 위 D단계 docstring 블록 참고)."""
    새본문, _ = _D단계_적용_및_카운트(본문)
    return 새본문


def _단계별_치환(본문: str, 값함수) -> Tuple[str, int]:
    """style="" 값 하나 또는 <style> 블록 하나 단위로 값함수를 적용한다.

    색치환의 _색치환_및_카운트 와 스캔 범위(style="" / <style>)가 동일한
    로직이라 B단계/C단계가 공유하는 얇은 래퍼로 분리했다."""
    total = 0

    def _style_block(m: 're.Match[str]') -> str:
        nonlocal total
        open_tag, content, close_tag = m.group(1), m.group(2), m.group(3)
        new_content, c = 값함수(content)
        total += c
        return open_tag + new_content + close_tag

    본문 = _STYLE_BLOCK_RE.sub(_style_block, 본문)

    def _style_attr(m: 're.Match[str]') -> str:
        nonlocal total
        prefix = m.group(1)
        quoted = m.group(2)
        if quoted.startswith('"'):
            inner = m.group(3) or ''
            new_inner, c = 값함수(inner)
            total += c
            return f'{prefix}"{new_inner}"'
        else:
            inner = m.group(4) or ''
            new_inner, c = 값함수(inner)
            total += c
            return f"{prefix}'{new_inner}'"

    본문 = _STYLE_ATTR_RE.sub(_style_attr, 본문)
    return 본문, total


@dataclass
class 파일결과:
    경로: str  # webapp/templates/ 기준 상대경로, forward slash
    치환수: int


@dataclass
class 훑기결과:
    적용: bool
    단계: str
    스캔파일수: int = 0
    스킵파일수: int = 0
    변경파일수: int = 0
    총치환수: int = 0
    파일별: List[파일결과] = field(default_factory=list)


def 훑기(적용: bool, 단계: str) -> 훑기결과:
    """webapp/templates/ 를 훑어 색을 치환한다.

    SKIP_FILES 는 절대 건드리지 않는다(읽지도 않음). 적용=False 면 미리보기만
    하고 아무 파일도 쓰지 않는다. 적용=True 여야만 실제로 디스크에 쓴다.
    """
    결과 = 훑기결과(적용=적용, 단계=단계)

    if not TEMPLATES_DIR.exists():
        return 결과

    변환 = {
        'B': _B단계_적용_및_카운트,
        'C': _C단계_적용_및_카운트,
        'D': _D단계_적용_및_카운트,
    }.get(단계, _색치환_및_카운트)

    for path in sorted(TEMPLATES_DIR.rglob('*.html')):
        rel = path.relative_to(TEMPLATES_DIR).as_posix()
        if rel in SKIP_FILES:
            결과.스킵파일수 += 1
            continue

        결과.스캔파일수 += 1
        원본 = path.read_text(encoding='utf-8')
        새본문, count = 변환(원본)
        if count > 0:
            결과.변경파일수 += 1
            결과.총치환수 += count
            결과.파일별.append(파일결과(경로=rel, 치환수=count))
            if 적용:
                path.write_text(새본문, encoding='utf-8')

    return 결과


def _cli() -> None:
    import argparse

    parser = argparse.ArgumentParser(description='design_sweep — 하드코딩 hex 색 → CSS 변수 치환')
    parser.add_argument('--apply', action='store_true', help='실제로 파일에 쓴다 (기본은 미리보기)')
    parser.add_argument('--stage', default='A', help='단계 라벨 (기본 A)')
    parser.add_argument('--risky-style-only', action='store_true',
                         help='SKIP_FILES 9개의 <style> 블록만 색 치환 (inline style="" 은 안 건드림)')
    parser.add_argument('--examples', type=int, default=5, help='전후 예시 몇 줄 보여줄지')
    args = parser.parse_args()

    if args.risky_style_only:
        결과 = 위험파일_스타일블록만_훑기(적용=args.apply)
    else:
        결과 = 훑기(적용=args.apply, 단계=args.stage)
    print(f'[design_sweep] 단계={결과.단계} 적용={결과.적용}')
    print(f'  스캔 파일: {결과.스캔파일수}개 (스킵 {결과.스킵파일수}개)')
    print(f'  변경 파일: {결과.변경파일수}개')
    print(f'  총 치환: {결과.총치환수}건')
    for fr in sorted(결과.파일별, key=lambda x: -x.치환수)[:20]:
        print(f'    {fr.경로}: {fr.치환수}건')


if __name__ == '__main__':
    _cli()
