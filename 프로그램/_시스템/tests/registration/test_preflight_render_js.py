# -*- coding: utf-8 -*-
"""점검 표의 「올라갈 상품명」 렌더 — bulk_manual.js 를 Node 로 실제 태운다.

★ [2026-07-24 2차 리뷰] 이 파일이 없던 동안, 「올라갈 상품명」 렌더를 통째로 지워도
  죽는 테스트가 **0건**이었다(변이 생존). 상품명을 바꾸는 기능인데 사장님이 「무엇이
  무엇으로 바뀌어 올라가는지」를 보는 화면에 회귀 방지 장치가 없었던 셈이다.

방식은 이 저장소 선례를 따른다 — `tests/margin/test_margin_rules_js.py` 가
배포되는 .js 를 node 로 직접 실행한다. bulk_manual.js 는 DOM 을 만지는 IIFE 라
통째로 require 할 수 없으므로, **배포본에서 함수 원문을 떼어** node 에서 태운다
(원문을 떼어 쓰므로 함수가 사라지거나 이름이 바뀌면 여기서 바로 터진다).
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

JS = (pathlib.Path(__file__).resolve().parents[2]
      / 'webapp' / 'static' / 'bulk_manual.js')


def _extract(fn_name: str) -> str:
    """`function 이름(...) { … }` 원문을 중괄호 짝으로 떼어낸다."""
    src = JS.read_text(encoding='utf-8')
    m = re.search(r'^\s*function\s+' + re.escape(fn_name) + r'\s*\(', src, re.M)
    assert m, f'{fn_name} 이(가) bulk_manual.js 에 없습니다 — 렌더가 사라졌습니다'
    i = src.index('{', m.end() - 1)
    depth = 0
    for j in range(i, len(src)):
        if src[j] == '{':
            depth += 1
        elif src[j] == '}':
            depth -= 1
            if depth == 0:
                return src[m.start():j + 1]
    raise AssertionError(f'{fn_name} 의 중괄호 짝이 안 맞습니다')


def _run(js_body: str, call: str):
    script = (
        "const esc = (s) => String(s == null ? '' : s).replace(/[&<>\"']/g,"
        " (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));\n"
        "const PRE_LABEL = {ready:'올릴 수 있음', blocked:'제외', need_brand:'브랜드 필요',"
        " need_category:'카테고리 필요', missing:'보충 필요'};\n"
        "const PRE_DOT = {ready:'ok', blocked:'danger', need_brand:'danger'};\n"
        "const PRE_MARKET = {smartstore:'스마트스토어', coupang:'쿠팡'};\n"
        "function foreignAssetsHtml(){ return ''; }\n"
        # confirmBoxHtml 은 일괄등록(PR#440)이 preflightHtml 에 넣은 확정 칸이다.
        # 기본 스텁을 두되, js_body 가 진짜 함수를 실으면 아래 정의가 이걸 덮는다
        # (뒤 선언이 이긴다) — 「올라갈 상품명 열 + 확정 칸 공존」 테스트가 그렇게 태운다.
        "function confirmBoxHtml(){ return ''; }\n"
        + js_body + "\n"
        "console.log(JSON.stringify(" + call + "));\n")
    r = subprocess.run(['node', '-e', script], capture_output=True, text=True,
                       encoding='utf-8')
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip())


pytestmark = pytest.mark.skipif(shutil.which('node') is None, reason='node 없음')


def test_바뀐_상품명을_원본과_함께_보여준다():
    body = _extract('procNameHtml')
    p = {'name': 'NIKE 에어포스 1', 'tags': [],
         'applied': [{'item': 'name', 'field': 'name',
                      'before': '에어포스 1', 'after': 'NIKE 에어포스 1',
                      'label': '상품명', 'note': ''}],
         'skipped': []}
    html = _run(body, 'procNameHtml(' + json.dumps(p, ensure_ascii=False) + ')')
    assert 'NIKE 에어포스 1' in html, '가공된 상품명이 화면에 안 나옵니다'
    assert '에어포스 1' in html and '원본' in html, '원본이 안 보여 비교가 안 됩니다'


def test_어떤_규칙이_손댔는지_펼쳐_볼_수_있다():
    body = _extract('procNameHtml')
    p = {'name': '숏 자켓', 'tags': ['신상'],
         'applied': [{'item': 'name', 'field': 'replacements', 'label': '상품명 · 치환표',
                      'before': '숏 재킷', 'after': '숏 자켓', 'note': '치환: 재킷 → 자켓'},
                     {'item': 'name', 'field': 'name', 'label': '상품명',
                      'before': '숏 재킷', 'after': '숏 자켓', 'note': ''}],
         'skipped': []}
    html = _run(body, 'procNameHtml(' + json.dumps(p, ensure_ascii=False) + ')')
    assert '치환표' in html and '재킷 → 자켓' in html
    assert '신상' in html, '만든 태그가 안 보입니다'


def test_막힌_행에는_올라갈_상품명을_보여주지_않는다():
    """절대 안 올라갈 이름을 「올라갈 상품명」이라고 굵게 보여주면 안 된다(리뷰 I-4).
    서버가 name 을 비워 보내고, 화면은 그걸 '—' 로 그린다."""
    body = _extract('procNameHtml')
    html = _run(body, "procNameHtml({name:'', tags:[], applied:[], skipped:[]})")
    assert html == '—', html


def test_점검_표에_올라갈_상품명_열과_확정칸이_공존한다():
    """★ [머지 2026-07-24] 일괄등록(확정 칸)과 가공(상품명 열)이 **같은 preflightHtml**
    을 건드린다. 병합이 잘못되면 한쪽이 사라진다 — 둘 다 렌더되는지 실제로 태운다."""
    body = '\n'.join(_extract(n) for n in
                     ('procNameHtml', 'confirmBoxHtml', 'preflightHtml'))
    rows = [
        {'market': 'smartstore', 'status': 'ready', 'reason': '',
         'category_code': '123', 'category_source': 'given',
         'caveats': [], 'foreign_assets': [], 'confirm_supported': False,
         'process': {'name': 'NIKE 에어포스 1', 'tags': [], 'skipped': [],
                     'applied': [{'item': 'name', 'field': 'name',
                                  'label': '상품명', 'note': '',
                                  'before': '에어포스 1',
                                  'after': 'NIKE 에어포스 1'}]}},
        # 「올라갔는지 모름」 행 — 확정 칸이 떠야 한다(일괄등록 C2).
        {'market': 'lotteon', 'status': 'uncertain', 'reason': '올라갔는지 모릅니다',
         'category_code': 'LO1', 'category_source': 'given', 'caveats': [],
         'foreign_assets': [], 'confirm_supported': True,
         'market_product_id': 'LO999',
         'process': {'name': '', 'tags': [], 'skipped': [], 'applied': []}},
    ]
    html = _run(body, 'preflightHtml(1, ' + json.dumps(rows, ensure_ascii=False) + ')')
    assert '<th>올라갈 상품명</th>' in html, '가공: 상품명 열이 없습니다'
    assert 'NIKE 에어포스 1' in html
    assert '이 상품번호로 확정' in html, '일괄등록: 확정 칸이 사라졌습니다'
    # 헤더 칸 수와 본문 칸 수가 같아야 표가 안 어긋난다.
    assert html.count('<th>') == 6, html.count('<th>')


def test_HTML_을_넣어도_그대로_실행되지_않는다():
    """상품명은 소싱처가 준 값이다 — 이스케이프가 빠지면 그게 곧 XSS 다."""
    body = _extract('procNameHtml')
    p = {'name': '<img src=x onerror=alert(1)>', 'tags': [], 'skipped': [],
         'applied': [{'item': 'name', 'field': 'name', 'label': '상품명', 'note': '',
                      'before': '원본', 'after': '<img src=x onerror=alert(1)>'}]}
    html = _run(body, 'procNameHtml(' + json.dumps(p, ensure_ascii=False) + ')')
    assert '<img' not in html and '&lt;img' in html, html


def test_초안_생성_카드에_가공_미리보기가_나온다():
    """「가공 규칙이 만드는 상품명」 카드 + 「저장값은 그대로」 안내 — 리뷰 I3 의 절반."""
    body = '\n'.join(_extract(n) for n in
                     ('fuStock', 'fuFilled', 'procNameHtml', 'preflightHtml', 'fuRowHtml'))
    row = {
        'ok': True, 'draft_id': 7, 'created': True, 'source_site': 'musinsa',
        'filled': {'name': '병행수입 숏 패딩', 'brand': '', 'source_category_path': '의류',
                   'options': 0, 'sellable_options': 0, 'stock_quantity': 5,
                   'images': 1, 'detail_html': True, 'sale_price': 0},
        'warnings': [], 'human_only': [], 'changes': [], 'missing': [],
        'process': {'name': '[정품] 숏 패딩', 'tags': [], 'applied': [], 'skipped': []},
    }
    html = _run(body, 'fuRowHtml(' + json.dumps(row, ensure_ascii=False) + ')')
    assert '[정품] 숏 패딩' in html, '가공 미리보기가 안 나옵니다'
    assert '저장된 이름은' in html, '저장값이 그대로라는 안내가 없습니다'


def test_초안_생성_카드가_막힌_사유를_접지_않는다():
    body = '\n'.join(_extract(n) for n in
                     ('fuStock', 'fuFilled', 'procNameHtml', 'preflightHtml', 'fuRowHtml'))
    row = {
        'ok': True, 'draft_id': 8, 'created': True, 'source_site': 'musinsa',
        'filled': {'name': '숏 패딩', 'brand': '', 'source_category_path': '의류',
                   'options': 0, 'sellable_options': 0, 'stock_quantity': 5,
                   'images': 1, 'detail_html': True, 'sale_price': 0},
        'warnings': [], 'human_only': [], 'changes': [], 'missing': [],
        'process': {'name': '숏 패딩', 'tags': [], 'applied': [],
                    'skipped': [{'code': 'NO_BRAND_FOR_RULES', 'blocking': True,
                                 'label': '가공 규칙',
                                 'reason': '브랜드가 정해지지 않았습니다'}]},
    }
    html = _run(body, 'fuRowHtml(' + json.dumps(row, ensure_ascii=False) + ')')
    assert '브랜드가 정해지지 않았습니다' in html, '막힌 사유가 화면에 안 뜹니다'
