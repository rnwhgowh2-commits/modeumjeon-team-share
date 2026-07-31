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
    # #9b59b6 는 COLOR_MAP/BRAND_KEEP 어디에도 없는 색을 일부러 골랐다
    # (T7 에서 4F67FF 가 COLOR_MAP 에 들어와 이 테스트의 "없는 색" 전제가
    #  깨졌었음 — 색을 바꿔 전제를 다시 참으로 만든다).
    본문 = (
        '<div style="border:1px solid {% if pref %}#9b59b6{% else %}#E5E8EB{% endif %}">'
        'x</div>'
    )
    결과 = 색치환(본문)
    assert '#9b59b6' in 결과  # COLOR_MAP 에 없는 색 — 그대로
    assert '#E5E8EB' not in 결과
    assert 'var(--line)' in 결과


# ── 규칙 9: 커스텀 프로퍼티 *선언*의 값은 안 바뀐다(자기참조/순환 방지) ─
# T7 1차 적용에서 실제로 터진 버그: 템플릿이 --ink/--line 같은 이름으로
# 자기만의 로컬 팔레트를 이미 선언해둔 곳이 있었다(marketplace_guide/map.html
# .dm2, orders/index.html, sets/flow.html :root 등). 이 선언의 값을
# var(--ink) 로 바꾸면 `--ink:var(--ink)` 처럼 자기참조가 되어 CSS 스펙상
# 무효(guaranteed-invalid)가 되고, 그 스코프 안의 색이 조용히 깨진다.

def test_커스텀프로퍼티_선언의_값은_이름이_같아도_안바뀐다():
    본문 = '<div style="--ink:#191f28;color:var(--ink)">x</div>'
    assert 색치환(본문) == 본문


def test_커스텀프로퍼티_선언_여러개_연속에서도_안바뀐다():
    # 실제 사례 재현: marketplace_guide/map.html .dm2 — --line 의 값(F1F3F5)은
    # var(--line2) 로 매핑되는데 --line2 도 바로 옆에서 로컬 선언되고,
    # --line2 의 값(E5E8EB)은 반대로 var(--line) 으로 매핑된다 — 서로
    # 맞바꾸는 순환이라 둘 다 안 바뀐다. --ink/--sub/--faint 도 자기 자신과
    # 같은 이름이라 안 바뀐다. --bg(F8FAFB→var(--n100))만 로컬에 --n100 이란
    # 이름이 없어 안전하므로 바뀐다.
    본문 = (
        '<style>.dm2{--ink:#191F28;--sub:#8B95A1;--faint:#B0B8C1;'
        '--line:#F1F3F5;--line2:#E5E8EB;--bg:#F8FAFB;}</style>'
    )
    결과 = 색치환(본문)
    assert '--ink:#191F28' in 결과
    assert '--sub:#8B95A1' in 결과
    assert '--faint:#B0B8C1' in 결과
    assert '--line:#F1F3F5' in 결과
    assert '--line2:#E5E8EB' in 결과
    assert '--bg:var(--n100)' in 결과


def test_커스텀프로퍼티가_아닌_일반_선언은_그대로_바뀐다():
    # 같은 블록 안이라도 color:/background: 같은 진짜 CSS 사용 자리는 바뀐다.
    본문 = (
        '<style>.dm2{--ink:#191F28;color:#191F28;background:#f9fafb}</style>'
    )
    결과 = 색치환(본문)
    assert '--ink:#191F28' in 결과       # 선언 값 — 그대로
    assert 'color:var(--ink)' in 결과     # 사용 자리 — 치환
    assert 'background:var(--bg)' in 결과  # 사용 자리 — 치환


def test_root_스코프_자기선언도_안바뀐다():
    # 실제 사례 재현: sets/flow.html :root{--bg:#f9fafb;...}
    본문 = '<style>:root{--bg:#f9fafb;--red:#dc2626;}</style>'
    결과 = 색치환(본문)
    assert 결과 == 본문


def test_중첩_var_폴백_안의_자기참조도_안바뀐다():
    # 실제 사례 재현: orders/index.html
    # .cskb{--line:var(--n200,#E5E8EB);--bg:var(--n100,#F9FAFB)}
    # #E5E8EB→var(--line), #F9FAFB→var(--bg) 인데 둘 다 자기 자신과 같은
    # 이름의 선언 *안*(var() 폴백)에 있다 — 직전 텍스트만 보면
    # `var(--n200,` 때문에 "--line:" 바로 뒤가 아니라서 못 잡는다.
    본문 = '<style>.cskb{--line:var(--n200,#E5E8EB);--bg:var(--n100,#F9FAFB);}</style>'
    결과 = 색치환(본문)
    assert 결과 == 본문


def test_중첩_var_폴백이라도_다른_이름이면_바뀐다():
    # --sub 선언 안의 폴백 색(#8b95a1→var(--sub))은 이름이 다른
    # 프로퍼티(--sub2) 선언 안에 있으므로 자기참조가 아니다 — 바뀌어야 한다.
    본문 = '<style>.x{--sub2:var(--n500,#8b95a1);}</style>'
    결과 = 색치환(본문)
    assert '--sub2:var(--n500,var(--sub))' in 결과


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


def test_color_map은_120개():
    # T6 시드 10개 + T7 추가 110개.
    assert len(COLOR_MAP) == 120


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
