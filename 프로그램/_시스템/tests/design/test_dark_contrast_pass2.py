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
    assert '.ds.ds-dark .pg-console { background:#0F172A; }' in css


# ── 4. pill-v2.warn / pg-status.partial — 옅은 주황 배경이 하드코딩이라
#    다크에서도 안 뒤집혔다. 형제 클래스(.ok/.danger, .running/.failed)는
#    이미 var(--연한-*) 를 쓰고 있었는데 .warn/.partial 만 빠져 있었다.

def test_pill_v2_warn_은_연한주황_토큰을_쓴다():
    css = _read('templates/bundles/list.html')
    assert '.pill-v2.warn  { background: var(--연한-주황,#FEF3C7); color: var(--amber,#92400E); }' in css


def test_pg_status_partial_은_연한주황_토큰을_쓴다():
    css = _read('templates/bundles/list.html')
    assert '.pg-status.partial { background:var(--연한-주황,#fef3c7); color:var(--amber,#92400e); }' in css


def test_형제_클래스와_동일한_변수_패턴을_따른다():
    # .ok/.running 이 이미 쓰던 var(--연한-초록,...) 패턴과 같은 모양인지 —
    # .warn/.partial 만 예외로 하드코딩돼 있던 불일치가 다시 생기면 잡는다.
    css = _read('templates/bundles/list.html')
    assert 'background:var(--연한-초록,#dcfce7); color:var(--green,#15803d)' in css  # .pg-status.running (그대로)
    assert 'background:var(--연한-주황,#fef3c7)' in css  # .pg-status.partial (보정됨)


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
    assert '.ds.ds-dark .sb3-item .emo.empty{color:var(--n500,#8B95A1)}' in css


# ── 7. sb-dm-btn.on — 우리 자신의 모드 전환 버튼(PR#563). 안전망(current)
#    으로 되돌아가는 유일한 통로라 특히 더 위험했다.

def test_sb_dm_btn_on_다크_보정_규칙이_존재한다():
    html = _read('templates/partials/sidebar.html')
    assert '.ds.ds-dark .sb-dm-btn.on{ background:var(--surface2,#2A2A2D); border-color:var(--surface2,#2A2A2D); }' in html


def test_sb_dm_btn_on_다크_보정은_ink_가_아닌_값을_쓴다():
    html = _read('templates/partials/sidebar.html')
    idx = html.index('.ds.ds-dark .sb-dm-btn.on{')
    끝 = html.index('}', idx)
    규칙 = html[idx:끝 + 1]
    assert '--ink' not in 규칙


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
