# -*- coding: utf-8 -*-
"""design_sweep 안전 규칙 고정 테스트 (T6).

이 스윕은 실제로 776종·10,402곳의 하드코딩 색을 건드릴 도구라서, "어디를
안 건드리는가"가 "어디를 건드리는가" 만큼 중요하다. 여기 테스트들은 일부러
적대적으로 짰다 — 실제 템플릿에서 관찰된 패턴(예: inventory/settings/
integration.html 의 Jinja 조건부 CSS, bulk/partials/_settings.html 의
JS 색 대입)을 그대로 재현해서 스윕이 잘못 건드리면 바로 실패하게 한다.
"""
from __future__ import annotations

import re

import pytest

import scripts.design_sweep as ds
from scripts.design_sweep import (
    BRAND_KEEP,
    COLOR_MAP,
    SKIP_FILES,
    TEMPLATES_DIR,
    _정규화,
    색치환,
    훑기,
)


# ── 규칙 7: SKIP_FILES ───────────────────────────────────────────────

def test_skip_files는_정확히_9개():
    assert len(SKIP_FILES) == 9


def test_skip_files는_위험파일들을_포함한다():
    expected = {
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
    assert SKIP_FILES == expected


# ── 규칙 3: 정규화(대소문자·3자리 축약) ──────────────────────────────

@pytest.mark.parametrize('raw,expected', [
    ('191f28', '191f28'),
    ('191F28', '191f28'),
    ('E5E8EB', 'e5e8eb'),
    ('abc', 'aabbcc'),
    ('ABC', 'aabbcc'),
    ('fff', 'ffffff'),
])
def test_정규화(raw, expected):
    assert _정규화(raw) == expected


def test_대소문자_둘다_치환된다():
    a = 색치환('<div style="color:#191f28">x</div>')
    b = 색치환('<div style="color:#191F28">x</div>')
    assert a == '<div style="color:var(--ink)">x</div>'
    assert b == '<div style="color:var(--ink)">x</div>'


# ── 규칙 1: class=/id=/data-* 절대 금지 ──────────────────────────────

def test_class_속성값은_절대_안바뀐다():
    본문 = '<div class="c-191f28">x</div>'
    assert 색치환(본문) == 본문


def test_id_속성값은_절대_안바뀐다():
    본문 = '<div id="e5e8eb-panel">x</div>'
    assert 색치환(본문) == 본문


def test_data_속성값은_절대_안바뀐다():
    본문 = '<div data-color="#191F28">x</div>'
    assert 색치환(본문) == 본문


def test_class_id_data가_있어도_style만_바뀐다():
    본문 = (
        '<div class="c-191f28" id="e5e8eb-panel" data-color="#191F28" '
        'style="color:#191f28">x</div>'
    )
    결과 = 색치환(본문)
    assert 'class="c-191f28"' in 결과
    assert 'id="e5e8eb-panel"' in 결과
    assert 'data-color="#191F28"' in 결과
    assert 'style="color:var(--ink)"' in 결과


def test_data_style로_시작하는_속성명은_style로_오탐되지_않는다():
    본문 = '<div data-style-hint="#191f28">x</div>'
    assert 색치환(본문) == 본문


# ── 규칙 2: style= 와 <style> 블록 안은 바뀐다 ────────────────────────

def test_style_속성_안의_색은_바뀐다():
    본문 = '<div style="border:1px solid #E5E8EB">x</div>'
    assert 색치환(본문) == '<div style="border:1px solid var(--line)">x</div>'


def test_style_블록_안의_색은_바뀐다():
    본문 = '<style>.foo{color:#4E5968;background:#f9fafb}</style>'
    결과 = 색치환(본문)
    assert 'color:var(--글자-기본)' in 결과
    assert 'background:var(--bg)' in 결과


def test_style_속성_홑따옴표도_바뀐다():
    본문 = "<div style='color:#8b95a1'>x</div>"
    assert 색치환(본문) == "<div style='color:var(--sub)'>x</div>"


# ── 규칙 4: BRAND_KEEP ───────────────────────────────────────────────

def test_brand_keep은_비어있지_않다():
    assert len(BRAND_KEEP) > 0


def test_brand_keep과_color_map은_안겹친다():
    assert set(COLOR_MAP) & BRAND_KEEP == set()


def test_brand_keep_색은_style안에서도_안바뀐다(monkeypatch):
    # 실제 COLOR_MAP 시드 10개와는 안 겹치므로, 규칙 자체를 고정하기 위해
    # 일부러 겹치는 상황을 만들어 검사한다 (BRAND_KEEP 우선순위 확인).
    monkeypatch.setitem(ds.COLOR_MAP, 'ff5a5f', 'var(--가짜)')
    monkeypatch.setattr(ds, 'BRAND_KEEP', ds.BRAND_KEEP | {'ff5a5f'})
    본문 = '<div style="color:#ff5a5f">쿠팡</div>'
    assert 색치환(본문) == 본문


# ── 규칙 5: JS 색 대입은 절대 안 건드린다 (스캔 범위 밖) ─────────────

def test_js_색대입은_style_밖이라_안건드린다():
    본문 = "<script>el.style.color = '#191F28';</script>"
    assert 색치환(본문) == 본문


def test_js_객체리터럴_색상값도_안건드린다():
    본문 = (
        "<script>const MK={coupang:{c:'#B91C1C'}, naver:{c:'#03c75a'}};"
        "</script>"
    )
    assert 색치환(본문) == 본문


def test_getComputedStyle_읽기도_안건드린다():
    본문 = "<script>if (getComputedStyle(el).color === '#191f28') { }</script>"
    assert 색치환(본문) == 본문


# ── 규칙 6: Jinja 태그 자체는 안 건드리되, 분기 출력의 CSS 값은 바뀐다 ─

def test_jinja_표현식_안의_문자열리터럴은_안건드린다():
    본문 = '<div style="color:{{ \'#191f28\' }}">x</div>'
    assert 색치환(본문) == 본문


def test_jinja_태그_구조는_깨지지_않는다():
    본문 = (
        '<div style="border:1px solid {% if x %}#4F67FF{% else %}#E5E8EB{% endif %}">'
        'x</div>'
    )
    결과 = 색치환(본문)
    assert '{% if x %}' in 결과
    assert '{% else %}' in 결과
    assert '{% endif %}' in 결과


def test_jinja_조건부_분기의_CSS값은_COLOR_MAP에_있으면_바뀐다():
    # 실제 사례: inventory/settings/integration.html 의
    # style="border:1px solid {% if %}...{% else %}#E5E8EB{% endif %}"
    본문 = (
        '<div style="border:1px solid {% if pref %}#4F67FF{% else %}#E5E8EB{% endif %}">'
        'x</div>'
    )
    결과 = 색치환(본문)
    assert '#4F67FF' in 결과  # COLOR_MAP 에 없는 색 — 그대로
    assert '#E5E8EB' not in 결과
    assert 'var(--line)' in 결과


# ── 규칙 8: COLOR_MAP 에 없는 색은 추측하지 않는다 ────────────────────

def test_map에_없는_색은_그대로():
    본문 = '<div style="color:#123abc">x</div>'
    assert 색치환(본문) == 본문


def test_map에_없는_3자리_축약도_그대로():
    본문 = '<div style="color:#abc">x</div>'
    assert 색치환(본문) == 본문


# ── COLOR_MAP 대상 변수가 tokens.css 에 실재하는지 ───────────────────

def test_color_map_타겟변수는_tokens_css에_실재한다():
    tokens_path = TEMPLATES_DIR.parent / 'static' / 'tokens.css'
    css = tokens_path.read_text(encoding='utf-8')
    var_names = {
        re.match(r'var\((--[^)]+)\)', v).group(1) for v in COLOR_MAP.values()
    }
    for var in sorted(var_names):
        assert re.search(re.escape(var) + r'\s*:', css), f'{var} 가 tokens.css 에 없음'


def test_color_map은_10개():
    assert len(COLOR_MAP) == 10


# ── 훑기(): 파일 스캔·SKIP·미리보기/적용 ──────────────────────────────

@pytest.fixture()
def fake_templates(tmp_path, monkeypatch):
    root = tmp_path / 'templates'
    (root / 'a').mkdir(parents=True)
    (root / 'bundles').mkdir(parents=True)

    p1 = root / 'a' / 'ok.html'
    p1.write_text('<div style="color:#191f28">x</div>', encoding='utf-8')

    p2 = root / 'bundles' / '_matrix_v3.html'  # SKIP_FILES 항목
    p2.write_text('<div style="color:#191f28">skip me</div>', encoding='utf-8')

    p3 = root / 'no_change.html'
    p3.write_text('<div class="c-191f28">no css color here</div>', encoding='utf-8')

    monkeypatch.setattr(ds, 'TEMPLATES_DIR', root)
    return root, p1, p2, p3


def test_훑기_dry_run은_파일을_쓰지않는다(fake_templates):
    root, p1, p2, p3 = fake_templates
    원본1 = p1.read_text(encoding='utf-8')
    결과 = 훑기(적용=False, 단계='A')
    assert p1.read_text(encoding='utf-8') == 원본1  # 안 바뀜(dry run)
    assert 결과.변경파일수 == 1  # ok.html 만 (matrix_v3 는 스킵, no_change 는 대상 없음)
    assert 결과.총치환수 == 1
    assert 결과.스킵파일수 == 1


def test_훑기_skip_file은_읽지도_않고_건드리지도_않는다(fake_templates):
    root, p1, p2, p3 = fake_templates
    원본2 = p2.read_text(encoding='utf-8')
    훑기(적용=True, 단계='A')
    assert p2.read_text(encoding='utf-8') == 원본2  # _matrix_v3.html 은 절대 변경 금지


def test_훑기_적용True면_실제로_쓴다(fake_templates):
    root, p1, p2, p3 = fake_templates
    훑기(적용=True, 단계='A')
    assert p1.read_text(encoding='utf-8') == '<div style="color:var(--ink)">x</div>'


def test_훑기_결과에_단계가_담긴다(fake_templates):
    결과 = 훑기(적용=False, 단계='B')
    assert 결과.단계 == 'B'
    assert 결과.적용 is False
