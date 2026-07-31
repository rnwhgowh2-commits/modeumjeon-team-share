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
_HEX_RE = re.compile(r'#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})(?![0-9a-fA-F])')
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
        norm = _정규화(m.group(1))
        if norm in BRAND_KEEP:
            return m.group(0)
        target = COLOR_MAP.get(norm)
        if target is None:
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
        return target

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

    for path in sorted(TEMPLATES_DIR.rglob('*.html')):
        rel = path.relative_to(TEMPLATES_DIR).as_posix()
        if rel in SKIP_FILES:
            결과.스킵파일수 += 1
            continue

        결과.스캔파일수 += 1
        원본 = path.read_text(encoding='utf-8')
        새본문, count = _색치환_및_카운트(원본)
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
    parser.add_argument('--examples', type=int, default=5, help='전후 예시 몇 줄 보여줄지')
    args = parser.parse_args()

    결과 = 훑기(적용=args.apply, 단계=args.stage)
    print(f'[design_sweep] 단계={결과.단계} 적용={결과.적용}')
    print(f'  스캔 파일: {결과.스캔파일수}개 (스킵 {결과.스킵파일수}개)')
    print(f'  변경 파일: {결과.변경파일수}개')
    print(f'  총 치환: {결과.총치환수}건')
    for fr in sorted(결과.파일별, key=lambda x: -x.치환수)[:20]:
        print(f'    {fr.경로}: {fr.치환수}건')


if __name__ == '__main__':
    _cli()
