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
    B단계,
    C단계,
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
    # 조회(어느 변수로 매핑할지)는 대소문자 무관이지만, 폴백 값은 원본
    # hex 를 그대로 보존한다 — 그래서 소문자 입력과 대문자 입력의 결과가
    # (변수는 같아도) 폴백 표기는 서로 다르다.
    a = 색치환('<div style="color:#191f28">x</div>')
    b = 색치환('<div style="color:#191F28">x</div>')
    assert a == '<div style="color:var(--ink,#191f28)">x</div>'
    assert b == '<div style="color:var(--ink,#191F28)">x</div>'


# ── 예비값(fallback): current 모드 안전망 ────────────────────────────
# `var(--타겟)` 만으로는 `--타겟` 이 정의되지 않은 화면(class="ds" 없는
# `current` 모드)에서 선언 전체가 무효가 되어 스윕 전과 다른 색(상속값)이
# 나온다. 예비값을 항상 동반해야 `current` 모드가 스윕 전과 픽셀 단위로
# 동일하게 유지된다.

def test_치환_결과는_콤마와_원본hex_예비값을_동반한다():
    본문 = '<div style="color:#E5E8EB">x</div>'
    결과 = 색치환(본문)
    assert 결과 == '<div style="color:var(--line,#E5E8EB)">x</div>'
    assert ', #' not in 결과  # 콤마 뒤 공백 없음(diff 최소화)


def test_예비값은_토큰의_대표값이_아니라_이_자리의_원본hex다():
    # COLOR_MAP 은 다대일이다 — 191f28 과 292a2f 는 둘 다 var(--ink) 로
    # 가지만, 서로 다른 사이트에서 서로 다른 원본색으로 쓰였을 수 있다.
    # 예비값이 "토큰의 대표값(예: 191f28)"으로 고정되면 292a2f 를 쓰던
    # 화면의 색이 살짝 달라진다 — 반드시 매치된 그 자리의 원본이어야 한다.
    a = 색치환('<div style="color:#191f28">x</div>')
    b = 색치환('<div style="color:#292a2f">x</div>')
    assert 'var(--ink,#191f28)' in a
    assert 'var(--ink,#292a2f)' in b
    assert 'var(--ink,#191f28)' not in b
    assert 'var(--ink,#292a2f)' not in a


def test_3자리_축약_예비값은_6자리로_확장되지만_대소문자는_보존된다():
    # 'ddd' → 정규화 조회는 'dddddd'(var(--line)) 로 맞지만, 예비값은
    # 원본 대소문자를 유지한 채 6자리로만 확장한다.
    본문 = '<div style="border-color:#DDD">x</div>'
    assert 색치환(본문) == '<div style="border-color:var(--line,#DDDDDD)">x</div>'


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
    assert 'style="color:var(--ink,#191f28)"' in 결과


def test_data_style로_시작하는_속성명은_style로_오탐되지_않는다():
    본문 = '<div data-style-hint="#191f28">x</div>'
    assert 색치환(본문) == 본문


# ── 규칙 2: style= 와 <style> 블록 안은 바뀐다 ────────────────────────

def test_style_속성_안의_색은_바뀐다():
    본문 = '<div style="border:1px solid #E5E8EB">x</div>'
    assert 색치환(본문) == '<div style="border:1px solid var(--line,#E5E8EB)">x</div>'


def test_style_블록_안의_색은_바뀐다():
    본문 = '<style>.foo{color:#4E5968;background:#f9fafb}</style>'
    결과 = 색치환(본문)
    assert 'color:var(--글자-기본,#4E5968)' in 결과
    assert 'background:var(--bg,#f9fafb)' in 결과


def test_style_속성_홑따옴표도_바뀐다():
    본문 = "<div style='color:#8b95a1'>x</div>"
    assert 색치환(본문) == "<div style='color:var(--sub,#8b95a1)'>x</div>"


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
    assert 'var(--line,#E5E8EB)' in 결과


# ── 규칙 9: 커스텀 프로퍼티 *선언*의 값은 안 바뀐다(자기참조/순환 방지) ─
# T7 1차 적용에서 실제로 터진 버그: 템플릿이 --ink/--line 같은 이름으로
# 자기만의 로컬 팔레트를 이미 선언해둔 곳이 있었다(marketplace_guide/map.html
# .dm2, orders/index.html, sets/flow.html :root 등). 이 선언의 값을
# var(--ink) 로 바꾸면 `--ink:var(--ink)` 처럼 자기참조가 되어 CSS 스펙상
# 무효(guaranteed-invalid)가 되고, 그 스코프 안의 색이 조용히 깨진다.

def test_커스텀프로퍼티_선언의_값은_이름이_같아도_안바뀐다():
    본문 = '<div style="--ink:#191f28;color:var(--ink)">x</div>'
    assert 색치환(본문) == 본문


def test_자기참조_가드는_예비값_붙는다고_뚫리지_않는다():
    # 예비값 도입 후에도 이 가드는 여전히 전부-아니면-전무다 — `--ink:
    # var(--ink,#191f28)` 처럼 반쪽만 안전해 보이는 자기참조를 만들지
    # 않는다(그런 선언도 CSS 스펙상 guaranteed-invalid 라 예비값이 있어도
    # 소용없다). 색치환 자체를 건너뛰어야 한다.
    본문 = '<style>.x{--ink:#191F28;}</style>'
    결과 = 색치환(본문)
    assert 결과 == 본문
    assert 'var(--ink' not in 결과


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
    assert '--bg:var(--n100,#F8FAFB)' in 결과


def test_커스텀프로퍼티가_아닌_일반_선언은_그대로_바뀐다():
    # 같은 블록 안이라도 color:/background: 같은 진짜 CSS 사용 자리는 바뀐다.
    본문 = (
        '<style>.dm2{--ink:#191F28;color:#191F28;background:#f9fafb}</style>'
    )
    결과 = 색치환(본문)
    assert '--ink:#191F28' in 결과       # 선언 값 — 그대로
    assert 'color:var(--ink,#191F28)' in 결과     # 사용 자리 — 치환
    assert 'background:var(--bg,#f9fafb)' in 결과  # 사용 자리 — 치환


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
    assert '--sub2:var(--n500,var(--sub,#8b95a1))' in 결과


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
    assert p1.read_text(encoding='utf-8') == '<div style="color:var(--ink,#191f28)">x</div>'


def test_훑기_결과에_단계가_담긴다(fake_templates):
    결과 = 훑기(적용=False, 단계='B')
    assert 결과.단계 == 'B'
    assert 결과.적용 is False


# ═══════════════════════════════════════════════════════════════════════
# T8 B단계 — 그림자 제거·음수 자간 0·11px 미만 올림
#
# 설계 판단(그림자): 지시문은 "box-shadow → border:1px solid var(--line)"
# 였지만, 실측 결과 이 치환은 안전하지 않다 — 208곳 중 76곳이 같은 선언
# 블록 안에 이미 border/border-color 를 갖고 있고, 그 중 실제 사례
# (accounts/crawl_login.html .cl-inp:focus)는 `border-color:var(--color-
# primary)` 뒤에 `border:1px solid var(--line)` 를 새로 붙이면 CSS
# 단축속성 규칙상 뒤에 오는 border 가 앞의 border-color 를 통째로
# 덮어써 포커스 색이 조용히 사라진다. 그 외에도 다수(28곳)가 상태점·
# 포커스 링처럼 "카드 깊이"가 아니라 "상태색 헤일로"라 하드코딩된 회색
# 선으로 바꾸면 의미가 달라진다. → border 를 추가하지 않고 box-shadow
# 선언 자체를 제거한다(그림자는 원래 레이아웃에 아무 영향이 없었으므로
# 제거도 레이아웃에 영향이 없다 — 가장 안전한 선택). 이미 border 를
# 가진 76곳은 그 border 가 그대로 "선으로 층을 만든다"는 규칙을
# 충족하고, 없는 132곳은 그림자만 사라져 다소 밋밋해지지만 깨지지는
# 않는다.
# ═══════════════════════════════════════════════════════════════════════

def test_boxshadow_있으면_제거된다():
    본문 = '<div style="box-shadow:0 2px 8px rgba(0,0,0,.1)">x</div>'
    assert B단계(본문) == '<div style="">x</div>'


def test_boxshadow_none은_그대로():
    본문 = '<div style="box-shadow:none">x</div>'
    assert B단계(본문) == 본문


def test_boxshadow_가운데선언이어도_앞뒤가_안깨진다():
    본문 = '<div style="color:red;box-shadow:0 2px 4px rgba(0,0,0,.1);background:blue">x</div>'
    assert B단계(본문) == '<div style="color:red;background:blue">x</div>'


def test_boxshadow가_마지막_선언이어도_안깨진다():
    본문 = '<div style="color:red;box-shadow:0 2px 4px rgba(0,0,0,.1)">x</div>'
    결과 = B단계(본문)
    assert 'box-shadow' not in 결과
    assert 'color:red' in 결과
    assert re.match(r'^<div style="color:red;?">x</div>$', 결과)


def test_boxshadow가_첫선언이어도_안깨진다():
    본문 = '<div style="box-shadow:0 2px 4px rgba(0,0,0,.1);color:red">x</div>'
    assert B단계(본문) == '<div style="color:red">x</div>'


def test_boxshadow_제거는_기존_border_color를_망가뜨리지_않는다():
    # 실측 재현: accounts/crawl_login.html .cl-inp:focus — border-color 뒤에
    # border 단축속성을 새로 붙이면 앞의 색 지정이 통째로 사라진다.
    # 이 위험 때문에 border 를 추가하지 않고 그림자만 지운다.
    본문 = (
        '<style>.cl-inp:focus{outline:none;border-color:var(--color-primary);'
        'box-shadow:0 0 0 3px var(--color-primary-light)}</style>'
    )
    결과 = B단계(본문)
    assert 'border-color:var(--color-primary)' in 결과
    assert 'box-shadow' not in 결과
    assert 'border:1px solid' not in 결과


def test_boxshadow는_JS_문자열대입은_안건드린다():
    본문 = "<script>el.style.boxShadow='0 2px 4px #000';</script>"
    assert B단계(본문) == 본문


def test_boxshadow는_class_속성값은_안건드린다():
    본문 = '<div class="has-box-shadow-lg" style="box-shadow:0 2px 4px #000">x</div>'
    결과 = B단계(본문)
    assert 결과 == '<div class="has-box-shadow-lg" style="">x</div>'


def test_음수_자간_em은_0으로():
    본문 = '<div style="letter-spacing:-0.02em">x</div>'
    assert B단계(본문) == '<div style="letter-spacing:0">x</div>'


def test_음수_자간_px_소수점_선행0없이도():
    본문 = "<div style='letter-spacing:-.5px'>x</div>"
    assert B단계(본문) == "<div style='letter-spacing:0'>x</div>"


def test_양수_자간은_안바뀐다():
    본문 = '<div style="letter-spacing:0.04em">x</div>'
    assert B단계(본문) == 본문


def test_자간_0은_안바뀐다():
    본문 = '<div style="letter-spacing:0">x</div>'
    assert B단계(본문) == 본문


def test_11px_미만_글자는_11px로_올라간다():
    본문 = '<div style="font-size:9px">x</div>'
    assert B단계(본문) == '<div style="font-size:11px">x</div>'


def test_10_5px도_11px로():
    본문 = '<div style="font-size:10.5px">x</div>'
    assert B단계(본문) == '<div style="font-size:11px">x</div>'


def test_11px_이상은_B단계에서_안건드린다():
    본문 = '<div style="font-size:22px">x</div>'
    assert B단계(본문) == 본문


def test_font_size_var_폴백_안의_px는_B단계에서도_안건드린다():
    # 실측 재현: bundles/edit.html font-size:var(--fs-h3, 19px) —
    # var() 폴백 안의 px 를 문자열 매치로 잘못 건드리면 변수 선언이 깨진다.
    본문 = '<div style="font-size: var(--fs-h3, 9px)">x</div>'
    assert B단계(본문) == 본문


# ═══════════════════════════════════════════════════════════════════════
# T9 C단계 — 글자크기 7등급·여백 7단·둥근모서리 4단
#
# 설계 판단(둥근모서리 알약 경계): 지시문은 "100px 이상은 알약"이었지만
# 실측 결과 99px 이 배지·필터 알약에 22곳 실사용되고 있었다(예: bundles/
# new.html .pc-cnt{padding:1px 11px;border-radius:99px}). 30px 이하와
# 99px/999px 사이에는 실측값이 하나도 없어(30 다음이 바로 99) 경계를
# 100 대신 50 으로 낮춰도 반올림 대상(30px 이하)에는 영향이 없고,
# 99px 알약만 안전하게 보존된다. → 50px 이상은 그대로 둔다.
# ═══════════════════════════════════════════════════════════════════════

def test_글자크기_13px는_동률_작은쪽_12px로():
    본문 = '<div style="font-size:13px">x</div>'
    assert C단계(본문) == '<div style="font-size:12px">x</div>'


def test_글자크기_15_5px는_동률_작은쪽_14px로():
    본문 = '<div style="font-size:15.5px">x</div>'
    assert C단계(본문) == '<div style="font-size:14px">x</div>'


def test_글자크기_28px는_동률_작은쪽_24px로():
    본문 = '<div style="font-size:28px">x</div>'
    assert C단계(본문) == '<div style="font-size:24px">x</div>'


def test_글자크기_16px는_더_가까운_17px로():
    본문 = '<div style="font-size:16px">x</div>'
    assert C단계(본문) == '<div style="font-size:17px">x</div>'


def test_글자크기_이미_규칙값이면_안바뀐다():
    본문 = '<div style="font-size:17px">x</div>'
    assert C단계(본문) == 본문


def test_글자크기_var_폴백_px는_C단계에서도_안건드린다():
    본문 = '<div style="font-size: var(--fs-h3, 19px)">x</div>'
    assert C단계(본문) == 본문


def test_여백_padding_다중값_각각_반올림_동률작은쪽():
    본문 = '<div style="padding:6px 10px 6px 10px">x</div>'
    assert C단계(본문) == '<div style="padding:4px 8px 4px 8px">x</div>'


def test_여백_margin_auto는_안건드린다():
    본문 = '<div style="margin:0 auto">x</div>'
    assert C단계(본문) == 본문


def test_여백_음수는_부호_유지하며_반올림():
    본문 = '<div style="margin:-6px">x</div>'
    assert C단계(본문) == '<div style="margin:-4px">x</div>'


def test_여백_gap도_적용된다():
    본문 = '<div style="gap:10px">x</div>'
    assert C단계(본문) == '<div style="gap:8px">x</div>'


def test_여백_퍼센트는_안건드린다():
    본문 = '<div style="padding:0 5%">x</div>'
    assert C단계(본문) == 본문


def test_여백_var_안의_px는_안건드리고_바깥값만_반올림():
    본문 = '<div style="padding:var(--sp-2, 10px) 6px">x</div>'
    결과 = C단계(본문)
    assert 'var(--sp-2, 10px)' in 결과
    assert 결과.endswith('4px">x</div>')


def test_여백_column_gap은_안전한_경계에서만_매치된다():
    # column-gap: 앞에 하이픈이 붙어 있어도(선택자 오탐 방지 lookbehind)
    # "gap:" 부분부터 정상적으로 값이 반올림된다.
    본문 = '<div style="column-gap:10px">x</div>'
    assert C단계(본문) == '<div style="column-gap:8px">x</div>'


def test_여백_클래스이름_충돌은_오탐되지_않는다():
    # 만약 셀렉터가 …padding 으로 끝나고 바로 :hover 가 온다면(가상 사례),
    # 여백 정규식이 선택자를 여백 선언으로 오인해선 안 된다.
    본문 = '<style>.mypadding:hover{color:red}</style>'
    assert C단계(본문) == 본문


def test_둥근모서리_30px는_18px로():
    본문 = '<div style="border-radius:30px">x</div>'
    assert C단계(본문) == '<div style="border-radius:18px">x</div>'


def test_둥근모서리_99px_알약은_안건드린다():
    본문 = '<div style="border-radius:99px">x</div>'
    assert C단계(본문) == 본문


def test_둥근모서리_999px_알약은_안건드린다():
    본문 = '<div style="border-radius:999px">x</div>'
    assert C단계(본문) == 본문


def test_둥근모서리_다중값_상단만_반올림():
    본문 = '<div style="border-radius:14px 14px 0 0">x</div>'
    assert C단계(본문) == '<div style="border-radius:12px 12px 0 0">x</div>'


def test_둥근모서리_50퍼센트_원은_안건드린다():
    본문 = '<div style="border-radius:50%">x</div>'
    assert C단계(본문) == 본문


def test_둥근모서리_var는_안건드린다():
    본문 = '<div style="border-radius:var(--r-sm)">x</div>'
    assert C단계(본문) == 본문


def test_둥근모서리_이미_규칙값이면_안바뀐다():
    본문 = '<div style="border-radius:12px">x</div>'
    assert C단계(본문) == 본문


# ── 훑기(): 단계 B/C 배선 ──────────────────────────────────────────────

@pytest.fixture()
def fake_templates_shadow(tmp_path, monkeypatch):
    root = tmp_path / 'templates'
    root.mkdir(parents=True)
    p1 = root / 'shadow.html'
    p1.write_text('<div style="box-shadow:0 2px 4px #000">x</div>', encoding='utf-8')
    monkeypatch.setattr(ds, 'TEMPLATES_DIR', root)
    return root, p1


def test_훑기_B단계로_실제_그림자가_제거된다(fake_templates_shadow):
    root, p1 = fake_templates_shadow
    결과 = 훑기(적용=True, 단계='B')
    assert p1.read_text(encoding='utf-8') == '<div style="">x</div>'
    assert 결과.단계 == 'B'
    assert 결과.총치환수 == 1


def test_훑기_B단계는_style_바깥으로_절대_안_넘어간다(tmp_path, monkeypatch):
    # 실측 재현 버그: 훑기() 가 격리 래퍼(_단계별_치환)를 거치지 않고
    # _B단계_및_카운트 를 원본 HTML 전체에 바로 돌렸을 때, box-shadow 가
    # style="" 의 "마지막" 선언(뒤에 세미콜론 없이 바로 닫는 따옴표)이면
    # 닫는 따옴표를 못 넘어가야 할 정규식이 다음 태그의 style="" 속성
    # 시작부까지 통째로 먹어버렸다(inventory/adjust/form.html 등 7개
    # 파일에서 실제로 발생 — 형제 요소의 여는 태그·다음 style 속성이
    # 통째로 사라짐). 단위 테스트(B단계() 직접 호출)는 이미 격리된 함수라
    # 이 배선 버그를 못 잡았다 — 반드시 훑기() 경로로, 형제 요소가 있는
    # 다중요소 문서로 검증한다.
    root = tmp_path / 'templates'
    root.mkdir(parents=True)
    p1 = root / 'form.html'
    원본 = (
        '<div style="background:#fff;display:flex;box-shadow:0 10px 40px rgba(0,0,0,0.2)">\n'
        '  <div style="padding:18px 22px;border-bottom:1px solid var(--line)">'
        '<h3>제품 추가</h3></div>\n'
        '</div>'
    )
    p1.write_text(원본, encoding='utf-8')
    monkeypatch.setattr(ds, 'TEMPLATES_DIR', root)
    훑기(적용=True, 단계='B')
    결과 = p1.read_text(encoding='utf-8')
    assert 결과 == (
        '<div style="background:#fff;display:flex;">\n'
        '  <div style="padding:18px 22px;border-bottom:1px solid var(--line)">'
        '<h3>제품 추가</h3></div>\n'
        '</div>'
    )


@pytest.fixture()
def fake_templates_fontsize(tmp_path, monkeypatch):
    root = tmp_path / 'templates'
    root.mkdir(parents=True)
    p1 = root / 'fs.html'
    p1.write_text('<div style="font-size:13px">x</div>', encoding='utf-8')
    monkeypatch.setattr(ds, 'TEMPLATES_DIR', root)
    return root, p1


def test_훑기_C단계로_실제_크기가_반올림된다(fake_templates_fontsize):
    root, p1 = fake_templates_fontsize
    결과 = 훑기(적용=True, 단계='C')
    assert p1.read_text(encoding='utf-8') == '<div style="font-size:12px">x</div>'
    assert 결과.단계 == 'C'
