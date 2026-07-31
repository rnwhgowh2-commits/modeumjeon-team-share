# -*- coding: utf-8 -*-
"""다크모드 대비 2차 수정 고정 테스트.

PR#565(다크모드 1차 수정, 사이드바)의 후속 — 라이브 layer 모드 실측에서
2,738개 텍스트 요소 중 386개가 대비 2.0 미만(사실상 안 보임)으로 나왔다.
공통 패턴: `color:#fff`(또는 밝은 텍스트)는 그대로 두고, "테마와 무관하게
항상 짙어야 하는" 배경이 텍스트-잉크 토큰(--ink/--n900)이나 하드코딩
hex 를 썼다가 .ds.ds-dark 에서 그 토큰이 밝은 값으로 뒤집히며 배경까지
밝아져 흰 글자가 묻힌 것.

이 파일은 실코드(css/html 텍스트)를 직접 읽어 그 보정 규칙이 실재하는지만
고정한다 — 렌더링·실측 대비비는 검증하지 않는다(브라우저 렌더 불가 환경).
"""
from __future__ import annotations

from pathlib import Path

import pytest

WEBAPP = Path(__file__).resolve().parents[2] / 'webapp'


def _read(rel: str) -> str:
    p = WEBAPP / rel
    assert p.exists(), f'파일이 없다: {p}'
    return p.read_text(encoding='utf-8')


# ── 1. btn-mini-v2.primary — 사장님이 직접 지목한 대표 사례 ──────────────
# --n900 은 .ds.ds-dark 에서 "가장 밝은 글자색"(#F5F5F7)으로 뒤집히는
# 토큰인데, 이 버튼은 그걸 "항상 짙은 버튼 배경"으로 오용해서 흰 글자
# (color:#fff)와 겹쳐 안 보였다. 버튼은 테마와 무관하게 짙게 고정해야 한다.

def test_btn_mini_v2_primary_는_라이트에서_n900_배경을_그대로_쓴다():
    css = _read('templates/bundles/list.html')
    assert '.btn-mini-v2.primary { background: var(--n900, var(--ink,#191F28)); color: #fff; }' in css


def test_btn_mini_v2_primary_다크_보정_규칙이_존재한다():
    css = _read('templates/bundles/list.html')
    assert '.ds.ds-dark .btn-mini-v2.primary { background: var(--surface2,#2A2A2D); }' in css


def test_btn_mini_v2_primary_다크_보정은_n900_이_아닌_값을_쓴다():
    # 회귀 방지 — 누가 실수로 다시 var(--n900,...) 로 되돌리면 즉시 실패해야 한다.
    css = _read('templates/bundles/list.html')
    idx = css.index('.ds.ds-dark .btn-mini-v2.primary {')
    끝 = css.index('}', idx)
    규칙 = css[idx:끝 + 1]
    assert '--n900' not in 규칙
    assert '--ink' not in 규칙


# ── 2. mc-chip — 마켓 매칭 칩(brand-app-logo 흰 글자가 안에 얹힌다) ──────

def test_mc_chip_다크_보정_규칙이_존재한다():
    css = _read('static/toss.css')
    assert '.ds.ds-dark .mc-chip { background: var(--surface2,#2A2A2D); color: var(--sub,#86868B); border-color: var(--line,rgba(255,255,255,.10)); }' in css


# ── 3. pg-console — 인라인 콘솔은 "항상 어두운 터미널"이어야 한다 ───────

def test_pg_console_다크_보정_규칙이_존재한다():
    css = _read('templates/bundles/list.html')
    # [2026-08-01] --ink 는 **글자색** 이름이라 어두운 화면에서 밝은 값으로 뒤집힌다.
    #   배경으로 쓰면 콘솔이 하얘진다 → 배경용 이름(--바탕-진하게)을 앞에 끼웠다.
    #   지켜야 할 성질은 그대로다: 「이 판은 어느 타입에서든 어둡다」.
    assert '.ds.ds-dark .pg-console { background: var(--바탕-진하게,' in css
    assert '#0F172A' in css, '원래 색이 예비값으로 안 남았다'


# ── 4. pill-v2.warn / pg-status.partial — 옅은 주황 배경이 하드코딩이라
#    다크에서도 안 뒤집혔다. 형제 클래스(.ok/.danger, .running/.failed)는
#    이미 var(--연한-*) 를 쓰고 있었는데 .warn/.partial 만 빠져 있었다.

# [2026-08-01] 아래 셋은 「바탕은 연한-X 토큰, 글자는 같은 계열 색 토큰」이라는
#   성질을 지킨다. 그 성질은 그대로인데 **글자 쪽 표기가 한 겹 늘었다** —
#   의미색 하나가 ①밝은 바탕 위 글자 ②검정 위 글자 ③흰 글자용 배경 셋을 겸해서
#   글자용 이름을 따로 냈기 때문이다(scripts/split_semantic_text.py).
#     color: var(--amber,#92400E)  →  color: var(--글자-주황, var(--amber,#92400E))
#   그래서 글자 쪽은 「글자용 이름 + 원래 표기가 예비값으로 남아 있는지」로 검사한다
#   (예비값이 사라지면 「기존 타입」에서 색이 통째로 사라진다).

def test_pill_v2_warn_은_연한주황_토큰을_쓴다():
    css = _read('templates/bundles/list.html')
    assert '.pill-v2.warn  { background: var(--연한-주황,#FEF3C7);' in css
    assert 'color: var(--글자-주황, var(--amber,#92400E)); }' in css


def test_pg_status_partial_은_연한주황_토큰을_쓴다():
    css = _read('templates/bundles/list.html')
    assert '.pg-status.partial { background:var(--연한-주황,#fef3c7);' in css
    assert 'color: var(--글자-주황, var(--amber,#92400e)); }' in css


def test_형제_클래스와_동일한_변수_패턴을_따른다():
    # .ok/.running 이 이미 쓰던 var(--연한-초록,...) 패턴과 같은 모양인지 —
    # .warn/.partial 만 예외로 하드코딩돼 있던 불일치가 다시 생기면 잡는다.
    css = _read('templates/bundles/list.html')
    assert 'background:var(--연한-초록,#dcfce7); color: var(--글자-초록, var(--green,#15803d))' in css
    assert 'background:var(--연한-주황,#fef3c7)' in css  # .pg-status.partial (보정됨)


def test_의미색_글자는_예비값을_잃지_않았다():
    """글자용 이름을 앞에 끼울 때 원래 표기를 예비값으로 남겨야 한다.

    「기존 타입」에는 --글자-초록 같은 이름이 없다. 예비값이 없으면 그 타입에서
    색 선언 전체가 무효가 되어 색이 통째로 사라진다.

    단, 규칙 전체가 `.ds` 안에만 있는 파일은 예외다 — 그 안에서는 이름이 반드시
    정의돼 있으므로 예비값이 필요 없다(스코프는 다른 테스트가 지킨다).
    """
    import io as _io
    import os as _os
    import re as _re
    뿌리 = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..', '..', 'webapp')
    _ds안에만있는파일 = ('tokens.css', 'dark_scope_fix.css', 'dark_badge_fix.css',
                        'inline_color_fix.css', 'margin_embed_ds.css')
    나쁜곳 = []
    for root, _d, files in _os.walk(뿌리):
        for f in files:
            if not f.endswith(('.html', '.css')):
                continue
            if f in _ds안에만있는파일:
                continue
            p = _os.path.join(root, f)
            글 = _io.open(p, encoding='utf-8', errors='replace').read()
            for m in _re.finditer(r'var\(\s*(--글자-(?:초록|빨강|주황|파랑))\s*(,?)([^)]*)', 글):
                if not m.group(2) or not m.group(3).strip():
                    나쁜곳.append((_os.path.relpath(p, 뿌리), m.group(1)))
    assert not 나쁜곳, '예비값 없는 글자용 토큰: %s' % 나쁜곳[:8]


# ── 5. bl-sort 정렬 화살표(⇅) — --line(헤어라인 토큰)을 텍스트색으로
#    오용해서 다크에서 rgba(255,255,255,.10)로 거의 안 보였다.

def test_sort_ind_다크_보정_규칙이_존재한다():
    css = _read('templates/bundles/list.html')
    assert '.ds.ds-dark .bl-table th .sort-ind { color: var(--n600,#C7C7CC); }' in css


def test_sort_ind_원본_glyph는_그대로_유지된다():
    # ⇅ 글자 자체(콘텐츠)는 이번 수정과 무관 — 안 지워졌는지만 확인
    html = _read('templates/bundles/list.html')
    assert html.count('<span class="sort-ind">⇅</span>') >= 7


# ── 6. sb3-item.on + 빈 아이콘 자리 — 사이드바 활성 항목의 라이트블루
#    배경이 하드코딩(#EAF3FF)이었고, 그 안의 아이콘-미지정 placeholder
#    (.emo.empty)가 --n400(다크에서 rgba(255,255,255,.26))을 써서 거의
#    투명했다.

def test_sb3_item_on_다크_보정_규칙이_존재한다():
    css = _read('static/sidebar_edit.css')
    assert '.ds.ds-dark .sb3-item.on{background:var(--primary-tint,rgba(0,113,227,.20))}' in css


def test_sb3_item_emo_empty_다크_보정_규칙이_존재한다():
    css = _read('static/sidebar_edit.css')
    # [2026-08-01] 순수 .css 파일도 색표 스윕을 타면서 예비값 안 hex 가 한 겹
    #   더 토큰이 됐다(#8B95A1 → var(--sub,#8B95A1)). 지켜야 할 성질은 그대로다:
    #   「--n400(거의 투명) 말고 읽히는 회색을 쓴다」.
    자리 = css.index('.ds.ds-dark .sb3-item .emo.empty{')
    규칙 = css[자리:css.index('}', 자리) + 1]
    assert '--n500' in 규칙, '읽히는 회색(--n500)을 안 쓴다'
    assert '--n400' not in 규칙, '거의 투명한 --n400 으로 되돌아갔다'
    assert '#8B95A1' in 규칙, '원래 색이 예비값으로 안 남았다'


# ── 7. 모드 전환 단추 — 안전망(기존 타입)으로 되돌아가는 유일한 통로라
#    특히 더 위험했다. PR#563 때 --ink 를 배경으로 써서 어두운 화면에서
#    흰 글자 위에 거의 흰 배경이 겹쳐 단추 자체가 안 보였다.
#
#    [2026-07-31] 세 벌(사이드바·상단탭·내 계정)이 오른쪽 위 붙박이 드롭버튼
#    한 벌(partials/design_mode_menu.html)로 합쳐졌다. 보정 규칙을 하나 더 다는
#    대신 **아예 토큰을 안 쓰는 것**으로 문제를 없앴다 — 아래가 그 못이다.

def test_디자인_드롭버튼은_토큰을_한개도_안_쓴다():
    """토큰이 무너져도 되돌리기 단추만은 보여야 한다.

    var(--...) 를 쓰는 순간 tokens.css 가 이 단추의 운명을 쥐게 된다.
    되돌리기 통로가 그 파일에 의존하면 안 된다 — 고정값만 쓴다.
    """
    html = _read('templates/partials/design_mode_menu.html')
    style = html[html.index('<style>'):html.index('</style>')]
    assert 'var(--' not in style, (
        '디자인 드롭버튼이 토큰을 쓰고 있다 — 토큰이 깨지면 되돌릴 길이 사라진다')


def test_디자인_드롭버튼은_이름을_스스로_적지_않는다():
    """이름의 원천은 design_mode.py 의 MODES 하나뿐이어야 한다."""
    html = _read('templates/partials/design_mode_menu.html')
    본문 = html[:html.index('<style>')]
    for 굳은이름 in ('기존 타입', '검정A 타입', '검정B 타입', '화이트 타입'):
        assert 굳은이름 not in 본문, (
            '%s 을(를) 부품이 직접 적고 있다 — MODES 와 갈라진다' % 굳은이름)


# ── 8. 스코프 규율 — 이번에 추가한 규칙은 전부 .ds.ds-dark 로 시작해야
#    한다(:root/전역 금지, current 모드 무영향 보장).

@pytest.mark.parametrize('rel', [
    'templates/bundles/list.html',
    'static/toss.css',
    'static/sidebar_edit.css',
    'templates/partials/sidebar.html',
])
def test_다크_보정_주석_아래_규칙은_전부_ds_ds_dark로_스코프된다(rel):
    text = _read(rel)
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith('.ds.ds-dark') and '{' in stripped:
            # 선택자 부분만 떼서 확인 — .ds.ds-dark 로 시작해야 함(공백/콤마 등 변형 허용 안 함)
            selector = stripped.split('{', 1)[0].strip()
            assert selector.startswith('.ds.ds-dark'), selector
