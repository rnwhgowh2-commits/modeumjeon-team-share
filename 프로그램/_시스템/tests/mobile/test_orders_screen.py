# -*- coding: utf-8 -*-
"""배치5 — 주문 폰 전용 화면(/mobile/orders) 1차: 뼈대 + 목록 칩.

사장님 확정(2026-08-04, 시안 v1): 1-C(2줄 압축 줄+금액열) · 2-A(상단 알약 칩+개수)
· 3-C(요약 3칸은 주문 화면 위 — **홈에는 숫자 금지**, 바로가기만).

무엇을 지키나
    ① 화면이 열리고(200) 뼈대(KPI 3칸·칩 4개·목록 판)가 있다 — 초기값은 전부 '-'
       (지어낸 숫자 금지: 서버 답을 받기 전에 그럴듯한 수를 미리 그려 두지 않는다).
    ② 🔴 같은 숫자 두 곳 금지 — 홈(home.html)에 KPI id(mo-kpi-*)가 **없어야** 하고,
       홈에는 「주문 보러 가기」 바로가기만 있다(3-C 그대로).
    ③ 칩 개수는 **배선**이다 — rows 에서 계산한 변수로만 넣는다. 하드코딩 숫자로
       바꾸면 여기서 잡힌다(낱말 검사가 아니라 배선 줄 자체를 못 박는다).
    ④ 1-C 줄 구조 — 금액열은 오른쪽 정렬 + tabular-nums(자릿수 세로 정렬).
       앞 배치들과 같은 방식으로 CSS 규칙 **본문**을 파싱해 확인한다.
    ⑤ 시각은 서버가 만든 KST 문자열('YYYY-MM-DD HH:MM:SS')만 잘라 쓴다 —
       `new Date(문자열)` 파싱 금지(시간대 없는 ISO → 폰에서 9시간 어긋난 실사고).
    ⑥ 인증 실패는 JSON 이 아니라 HTML 로 온다 — content-type 을 거르는 askServer 만
       쓴다(crawl.html 관례).
    ⑦ 모르는 값은 '-' — 마진 null·집계 실패를 0 으로 지어내지 않는다.

★ '낱말이 어딘가 있나'로 검사하지 않는다(형제 화면에서 네 번 헛통과한 함정) —
  HTML 은 파서로, JS·CSS 는 그 줄/규칙 본문을 정규식으로 못 박는다.
"""
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

# 형제 모듈의 메뉴 파서 재사용(사본 금지) — (주소, 배지) 짝으로 판정한다.
from test_menu_single_source import _MenuRows

# flask_app 픽스처는 tests/mobile/conftest.py 에 있다.

_TPL = Path(__file__).resolve().parents[2] / 'webapp' / 'templates' / 'mobile' / 'orders.html'
_HOME = Path(__file__).resolve().parents[2] / 'webapp' / 'templates' / 'mobile' / 'home.html'


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


def _orders_html(client):
    """주문 화면 HTML — 200 이 아니면 여기서 세운다.

    (본문이 비면 '없는 쪽' 시험이 저절로 통과한다 — crawl_html 과 같은 처방.)
    """
    r = client.get('/mobile/orders')
    assert r.status_code == 200, \
        f'주문 화면이 안 열린다(status={r.status_code}) — 아래 시험은 의미가 없다'
    return r.get_data(as_text=True)


def _tpl_src() -> str:
    assert _TPL.exists(), f'템플릿이 없다: {_TPL}'
    return _TPL.read_text(encoding='utf-8')


class _IdText(HTMLParser):
    """id → 텍스트. '초기값이 -인가'를 파서로 본다(문자열 검색은 주석에도 속는다)."""

    def __init__(self):
        super().__init__()
        self.texts: dict[str, str] = {}
        self._stack: list[str] = []

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        self._stack.append(d.get('id') or '')

    def handle_endtag(self, tag):
        if self._stack:
            self._stack.pop()

    def handle_data(self, data):
        for _id in self._stack:
            if _id:
                self.texts[_id] = self.texts.get(_id, '') + data.strip()


class _Chips(HTMLParser):
    """class=mo-chip 인 버튼들 — (data-pane, 라벨, 개수칸 id·텍스트)."""

    def __init__(self):
        super().__init__()
        self.chips: list[dict] = []
        self._cur = None
        self._in_n = False

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        cls = (d.get('class') or '').split()
        if 'mo-chip' in cls:
            self._cur = {'pane': d.get('data-pane'), 'label': '',
                         'n_id': None, 'n_text': ''}
        elif self._cur is not None and tag == 'span' and 'n' in cls:
            self._in_n = True
            self._cur['n_id'] = d.get('id')

    def handle_data(self, data):
        if self._cur is None:
            return
        if self._in_n:
            self._cur['n_text'] += data.strip()
        else:
            self._cur['label'] += data.strip()

    def handle_endtag(self, tag):
        if tag == 'span':
            self._in_n = False
        elif tag == 'button' and self._cur is not None:
            self.chips.append(self._cur)
            self._cur = None


def _css_rule(src: str, selector: str) -> str:
    """selector 의 규칙 본문 — 없으면 여기서 세운다."""
    m = re.search(re.escape(selector) + r'\s*\{([^}]*)\}', src)
    assert m, f'CSS 규칙이 없다: {selector}'
    return m.group(1)


# ────────────────────────── ① 뼈대 ──────────────────────────

def test_주문화면이_열리고_KPI_칩_목록_뼈대가_있다(client):
    html = _orders_html(client)
    ids = _IdText()
    ids.feed(html)
    # 3-C 요약 3칸 — 초기값은 '-' (서버 답 전에 숫자를 지어내지 않는다)
    for k in ('mo-kpi-new', 'mo-kpi-sales', 'mo-kpi-risk'):
        assert k in ids.texts, f'KPI 칸이 없다: {k}'
        assert ids.texts[k] == '-', \
            f'KPI {k} 초기값이 - 가 아니다: {ids.texts[k]!r} (지어낸 숫자 금지)'
    ch = _Chips()
    ch.feed(html)
    panes = [c['pane'] for c in ch.chips]
    assert panes == ['list', 'ship', 'cs', 'margin'], f'칩 4개(2-A)가 아니다: {panes}'
    # 목록·송장·CS 칩 개수칸 — 초기값 '-'
    for c in ch.chips:
        if c['pane'] in ('list', 'ship', 'cs'):
            assert c['n_id'] == f"mo-cnt-{c['pane']}", f"개수칸 id 가 없다: {c}"
            assert c['n_text'] == '-', \
                f"칩 {c['pane']} 개수 초기값이 - 가 아니다: {c['n_text']!r}"
    # 목록 판 + 준비 중 판 3개(정직한 자리표시 — 가짜 데이터 금지)
    assert 'id="mo-pane-list"' in html
    for p in ('ship', 'cs', 'margin'):
        assert f'id="mo-pane-{p}"' in html, f'{p} 판이 없다'
        assert '준비 중' in html


def test_준비중_판은_가짜_데이터가_아니라_PC_링크를_준다(client):
    html = _orders_html(client)
    # 송장·CS 준비 중 판 — 지금 당장 쓸 수 있는 PC 화면 주소를 안내한다.
    assert '/orders/?tab=ship' in html
    assert '/orders/?tab=cs' in html


# ────────────────── ② 같은 숫자 두 곳 금지(3-C) ──────────────────

def test_홈에는_KPI_숫자가_없고_주문_바로가기만_있다(client):
    src = _HOME.read_text(encoding='utf-8')
    assert 'mo-kpi' not in src, \
        '홈에 KPI 칸(mo-kpi*)이 있다 — 요약 숫자는 주문 화면 한 곳에만(3-C 확정)'
    assert '/mobile/orders' in src, '홈에 「주문 보러 가기」 바로가기가 없다'
    r = client.get('/mobile')
    assert r.status_code == 200
    home = r.get_data(as_text=True)
    assert 'mo-kpi-new' not in home and 'mo-kpi-sales' not in home \
        and 'mo-kpi-risk' not in home
    assert '/mobile/orders' in home


# ────────────────── ③ 칩 개수 배선(하드코딩 금지) ──────────────────

def test_칩_개수는_rows_에서_계산한_변수로만_넣는다():
    src = _tpl_src()
    # 배선 줄 자체를 못 박는다 — setCnt('mo-cnt-ship', 4) 처럼 숫자를 박으면 실패.
    assert re.search(r"setCnt\('mo-cnt-list',\s*rows\.length\)", src), \
        '목록 칩이 rows.length 배선이 아니다'
    assert re.search(r"setCnt\('mo-cnt-ship',\s*shipN\)", src), \
        '송장 칩이 계산 변수(shipN) 배선이 아니다'
    assert re.search(r"setCnt\('mo-cnt-cs',\s*csN\)", src), \
        'CS 칩이 계산 변수(csN) 배선이 아니다'
    # 그 변수는 실제로 rows 를 거른 결과다(변수 이름만 남기고 숫자를 넣는 변이 차단).
    assert re.search(r"var\s+shipN\s*=\s*rows\.filter\(", src)
    assert re.search(r"var\s+csN\s*=\s*rows\.filter\(", src)


# ────────────────── ④ 1-C 줄 구조(금액열) ──────────────────

def test_금액열은_오른쪽_정렬에_tabular_nums_다():
    src = _tpl_src()
    num = _css_rule(src, '.mo-num')
    assert 'font-variant-numeric:tabular-nums' in num.replace(' ', ''), \
        '.mo-num 에 tabular-nums 가 없다 — 자릿수 세로 정렬이 무너진다'
    rr = _css_rule(src, '.mo-rr-r')
    flat = rr.replace(' ', '')
    assert 'text-align:right' in flat, '.mo-rr-r 이 오른쪽 정렬이 아니다'
    assert 'flex-shrink:0' in flat, '.mo-rr-r 이 줄아붙는다(flex-shrink:0 없음)'
    # 왼쪽 칸은 min-width:0 — 없으면 긴 상품명이 금액열을 밀어낸다(1-C 핵심).
    rl = _css_rule(src, '.mo-rr-l')
    assert 'min-width:0' in rl.replace(' ', '')
    # 줄 그리기 코드가 실제로 그 클래스를 쓴다(규칙만 있고 안 쓰는 변이 차단).
    assert 'mo-rr-r' in src and re.search(r'class="mo-num"', src)


# ────────────────── ⑤ 시각 — KST 문자열만 ──────────────────

def test_서버_시각_문자열을_Date_로_파싱하지_않는다():
    src = _tpl_src()
    # new Date() / new Date(Date.now()±ms) 만 허용 — 문자열 파싱은 전부 금지.
    bad = re.search(r'new Date\((?!\)|Date\.now)', src)
    assert not bad, 'new Date(서버값) 파싱이 있다 — 시간대 없는 문자열은 9시간 어긋난다'
    # 주문일은 서버 KST 문자열('YYYY-MM-DD HH:MM:SS')을 잘라서만 쓴다.
    assert re.search(r"\['주문일'\]\s*\|\|\s*''\)\.slice\(", src), \
        '주문일을 slice 로 잘라 쓰는 코드가 없다'


# ────────────────── ⑥ askServer(HTML 응답 거르기) ──────────────────

def test_JSON_아닌_응답은_파싱_전에_거른다():
    src = _tpl_src()
    assert re.search(r"content-type", src), 'content-type 검사가 없다'
    assert "new Error('not-json')" in src, \
        '인증 실패 HTML 을 JSON 으로 파싱하다 터지는 길이 열려 있다(askServer 관례)'
    assert 'r.ok' in src, '상태코드 검사 없이 본문부터 읽는다'


# ────────────────── ⑦ 모르면 '-' ──────────────────

def test_마진_모르면_대시_품절위험_실패도_대시():
    src = _tpl_src()
    # 마진 null → '-' (0 으로 지어내지 않는다)
    assert re.search(r"margin\s*==\s*null.*?'-'", src, re.S), \
        '마진 null 을 - 로 그리는 갈래가 없다'
    # 품절 위험(fulfillment) 실패 → '-' 로 되돌린다(옛 값·0 으로 남기지 않는다)
    assert re.search(r"setKpi\('mo-kpi-risk',\s*'-'\)", src), \
        '품절 위험 실패 시 - 로 되돌리는 갈래가 없다'
    assert re.search(r"setKpi\('mo-kpi-sales',\s*'-'\)", src), \
        '매출 집계 불가 시 - 로 되돌리는 갈래가 없다'


# ────────────────── 메뉴 등재(전체 메뉴) ──────────────────

def test_전체메뉴에_주문줄이_폰전용_배지로_실린다(client):
    r = client.get('/mobile/menu')
    assert r.status_code == 200
    p = _MenuRows()
    p.feed(r.get_data(as_text=True))
    rows = [x for x in p.rows if x['url'] == '/mobile/orders']
    assert rows, '전체 메뉴에 /mobile/orders 줄이 없다 — 주소를 직접 쳐야 하는 사고 재발'
