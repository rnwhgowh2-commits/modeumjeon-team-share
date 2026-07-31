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


# ── T6 시드 — 측정 상위 10개 색 (T7 이후 더 늘어남) ──────────────────
# 대상 변수는 webapp/static/tokens.css 에 전부 존재함을 확인했다 (line 151~169).
COLOR_MAP: Dict[str, str] = {
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
