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
    # [2차] CS 유형 칩·마진 기간 칩도 같은 .mo-chip 을 재사용한다(data-cs/data-mg,
    #  data-pane 없음) — 상단 알약(2-A)만 data-pane 으로 골라 4개를 못 박는다.
    panes = [c['pane'] for c in ch.chips if c['pane']]
    assert panes == ['list', 'ship', 'cs', 'margin'], f'칩 4개(2-A)가 아니다: {panes}'
    # 목록·송장·CS 칩 개수칸 — 초기값 '-'
    for c in ch.chips:
        if c['pane'] in ('list', 'ship', 'cs'):
            assert c['n_id'] == f"mo-cnt-{c['pane']}", f"개수칸 id 가 없다: {c}"
            assert c['n_text'] == '-', \
                f"칩 {c['pane']} 개수 초기값이 - 가 아니다: {c['n_text']!r}"
    # 목록 판 + 2차 판 3개(송장·CS·마진 — 내용 검증은 test_orders_panes.py)
    assert 'id="mo-pane-list"' in html
    for p in ('ship', 'cs', 'margin'):
        assert f'id="mo-pane-{p}"' in html, f'{p} 판이 없다'


def test_각_판은_더_깊은_작업의_PC_링크를_준다(client):
    """[2차 개정] 「준비 중」 자리표시는 실판으로 바뀌었다 — 대신 폰에서 못 하는
    깊은 작업(엑셀 일괄·확인 처리·월 분석)의 PC 주소는 계속 안내한다."""
    html = _orders_html(client)
    assert '/orders/?tab=ship' in html
    assert '/orders/?tab=cs' in html
    assert '/orders/?tab=margin' in html


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
    # [2026-08-06 4차] rows → visRows()(기간 + 마켓·계정 칩). 하드코딩 숫자를 막는다는
    #   이 시험의 뜻은 그대로 — 여전히 계산식 배선만 통과한다.
    assert re.search(r"setCnt\('mo-cnt-list',\s*trusted\?visRows\(\)\.length:null\)", src), \
        '목록 칩이 visRows().length 배선이 아니다(못 불러왔으면 - )'
    assert re.search(r"setCnt\('mo-cnt-ship',\s*trusted\?shipN:null\)", src), \
        '송장 칩이 계산 변수(shipN) 배선이 아니다(못 불러왔으면 - )'
    # [2차 개정] CS 칩 = CS 판과 **같은 목록**(claims+문의)의 총계 함수(csTotal) 배선.
    #   1차의 rows 상태 정규식 수(csN)는 문의를 못 세 판(전체 N)과 다른 답을 냈다 —
    #   같은 화면에 같은 이름의 수 두 정의 금지. 자세한 단일 원천 시험은 test_orders_panes.py.
    assert re.search(r"setCnt\('mo-cnt-cs',\s*csTotal\(\)\)", src), \
        'CS 칩이 csTotal()(판과 같은 원천) 배선이 아니다'
    # 송장 수는 실제로 rows 를 거른 결과다(변수 이름만 남기고 숫자를 넣는 변이 차단).
    assert re.search(r"var\s+shipN\s*=\s*shipRowsOf\(\)\.length", src)
    assert re.search(r"function\s+shipRowsOf\(\)\{return visRows\(\)\.filter\(", src)


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


def test_전마켓_실패면_품절위험도_대시_다():
    """[검토 C1] rows 가 빈 이유는 둘이다 — ①조회 성공·주문 0건 ②전 마켓 실패.

    ②에서 「0 건」을 그리면 '모르면 확인 불가 — 없다고 단정 금지' 위반이고,
    같은 화면의 신규·매출('-')과 원칙이 갈라진다. 분기 줄 자체를 못 박는다.
    """
    src = _tpl_src()
    # [2026-08-06 4차] 이 갈래가 loadExtras 의 삼항식에서 renderRisk() **안**으로 옮겨졌다
    #   (마켓·계정을 고를 때마다 다시 판정해야 해서). 지키는 뜻은 셋 그대로 —
    #   ①전 마켓 실패 = '-'  ②조회 성공·0건 = '0 건'  ③판정을 못 받았으면 = '-'.
    assert re.search(
        r"if\(!okAny\)\{setKpi\('mo-kpi-risk','-'\);return;\}", src), \
        '전 마켓 실패 갈래가 없다 — 실패를 「품절 위험 0건」으로 단정하게 된다'
    assert re.search(
        r"if\(!sub\.length\)\{setKpi\('mo-kpi-risk','0<small> 건</small>'\);return;\}", src), \
        '조회 성공·주문 0건 갈래가 없다 — 사실인 0 을 - 로 흐리면 안 된다'
    assert re.search(r"setKpi\('mo-kpi-risk',\s*n==null\?'-':", src), \
        '재고 판정을 못 받았을 때 - 로 두는 갈래가 없다 — 0 으로 지어내면 안 된다'
    # riskN 은 판정(ffOk)이 없으면 null 을 준다 — 0 을 돌려주면 위 갈래가 무력해진다.
    assert re.search(r"function riskN\(sub\)\{\s*if\(!ffOk\)return null;", src), \
        'riskN 이 판정 실패를 null 로 말하지 않는다'


def test_부분_로딩중임이_화면에_보인다():
    """[검토 I1] 첫 마켓 응답 뒤 KPI·매출은 부분값이다(ESM 늦으면 ~60초).

    다 온 척 보이면 안 된다 — 진행(N/전체) 표시가 배선돼 있어야 한다.
    """
    src = _tpl_src()
    assert re.search(r"불러오는 중\s*'\s*\+\s*loadDone\s*\+\s*'/'\s*\+\s*MARKETS\.length", src), \
        '부분 로딩 표시(불러오는 중 N/전체)가 없다 — 부분값이 최종값처럼 보인다'
    assert '부분값' in src, '로딩 중 숫자가 부분값이라는 안내가 없다'


def test_발송대기_정규식은_PC와_같다():
    """[검토] WAIT 정규식은 PC 템플릿의 사본이다(315KB 원본은 불가침이라 참조 불가).

    사본은 어긋나는 순간이 문제다 — 두 파일의 `var WAIT=/.../` 줄을 추출해
    **동일성**을 못 박는다. PC 쪽 정의가 바뀌면 이 시험이 폰 사본 갱신을 강제한다.
    """
    pc = (Path(__file__).resolve().parents[2] / 'webapp' / 'templates'
          / 'orders' / 'index.html').read_text(encoding='utf-8')
    mo = _tpl_src()

    def wait_of(src, name):
        m = re.search(r'var WAIT=(/[^/]+/);', src)
        assert m, f'{name} 에서 var WAIT=/.../ 줄을 못 찾았다'
        return m.group(1)

    assert wait_of(pc, 'PC(orders/index.html)') == wait_of(mo, '폰(mobile/orders.html)'), \
        '발송대기(WAIT) 정의가 PC 와 폰에서 갈라졌다 — 「송장」 칩 수와 PC KPI 가 다른 답을 낸다'


# ────────────────── [3차] 목록 기간 칩(오늘·7일·30일·직접) ──────────────────

class _PdChips(HTMLParser):
    """#mo-pd-chips 안의 기간 칩 — (data-pd, on 여부, 라벨). 낱말 grep 금지 —
    파서로 버튼 자체를 본다(주석·JS 문자열에 속지 않는다)."""

    def __init__(self):
        super().__init__()
        self.chips: list[dict] = []
        self._in_row = False
        self._cur = None
        self._depth = 0

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if d.get('id') == 'mo-pd-chips':
            self._in_row = True
            self._depth = 0
            return
        if not self._in_row:
            return
        self._depth += 1
        if tag == 'button' and 'mo-chip' in (d.get('class') or '').split():
            self._cur = {'pd': d.get('data-pd'), 'label': '',
                         'on': 'on' in (d.get('class') or '').split(),
                         'pane': d.get('data-pane')}

    def handle_data(self, data):
        if self._cur is not None:
            self._cur['label'] += data.strip()

    def handle_endtag(self, tag):
        if not self._in_row:
            return
        if tag == 'button' and self._cur is not None:
            self.chips.append(self._cur)
            self._cur = None
        if self._depth == 0:
            self._in_row = False
        else:
            self._depth -= 1


def test_기간_칩_4개가_있고_기본은_7일이다(client):
    """[6차] 사장님 요청(2026-08-06) — 오늘·어제·3일·7일·14일·1달·기간 직접 7개.
    마진 판(C-4)과 같은 .mo-chip 문법. 기본 선택(on)은 7일(기존 동작 불변)."""
    html = _orders_html(client)
    p = _PdChips()
    p.feed(html)
    pds = [c['pd'] for c in p.chips]
    assert pds == ['today', 'yday', '3', '7', '14', '30', 'custom'], \
        f'기간 칩이 확정안과 다르다: {pds}'
    labels = [c['label'] for c in p.chips]
    assert labels == ['오늘', '어제', '3일', '7일', '14일', '1달', '기간 직접'], \
        f'칩 라벨이 확정안과 다르다: {labels}'
    on = [c['pd'] for c in p.chips if c['on']]
    assert on == ['7'], f'기본 선택이 7일이 아니다: {on}'
    # 상단 알약(2-A)과 섞이지 않는다 — 기간 칩엔 data-pane 이 없어야 한다
    #   (있으면 ① 뼈대 시험의 「칩 4개(2-A)」 판정까지 오염된다).
    assert all(c['pane'] is None for c in p.chips), \
        f'기간 칩에 data-pane 이 섞였다(판 전환 칩과 다른 부류): {p.chips}'


def test_기간은_pdRange_배선이고_기본은_7일_창이다():
    """하드코딩 from/to 는 제거됐고, loadAll 은 pdRange()가 준 창으로만 조회한다.
    기본 갈래(칩 안 눌렀을 때)는 옛 하드코딩과 같은 7일 창임을 문자열로 못 박는다."""
    src = _tpl_src()
    # 초기 상태 = 7일
    assert re.search(r"var pdSel='7',\s*pdFrom='',\s*pdTo='';", src), \
        '기간 초기 상태(pdSel=7)가 없다 — 기본 동작 불변 약속이 깨진다'
    # loadAll 이 pdRange 배선으로 조회한다(하드코딩 제거 후에도 이 줄이 창의 유일한 원천)
    assert re.search(r"var pr=pdRange\(\), from=pr\.from, to=pr\.to;", src), \
        'loadAll 이 pdRange() 배선이 아니다'
    assert not re.search(r"var from=kstDay\(6\*86400000\), to=kstDay\(0\);", src), \
        '옛 하드코딩 from/to 가 남아 있다(기간 칩이 무시된다)'
    # [6차] 창·긴이름·짧은이름을 PD_DEFS 한 표에서 정의한다 — 세 함수에 흩어져 있으면
    #   칩을 하나 더할 때 한 곳을 빠뜨려 「14일을 보는데 7일이라 말하는」 거짓 화면이 된다.
    for key, days, label, short in [('today', 0, '오늘', '오늘'),
                                    ('3', 2, '최근 3일', '3일'),
                                    ('7', 6, '최근 7일', '7일'),
                                    ('14', 13, '최근 14일', '14일'),
                                    ('30', 29, '최근 1달', '1달')]:
        assert re.search(r"'?%s'?:\s*\{days:%d,\s*label:'%s',\s*short:'%s'\}"
                         % (key, days, label, short), src), \
            f'PD_DEFS 에 {key}({label}) 정의가 없거나 창이 다르다'
    # 🔴 「어제」만 오늘을 안 포함하는 하루 창이다(시작=끝=어제).
    assert re.search(r"yday:\s*\{yday:true", src), 'PD_DEFS 에 어제 정의가 없다'
    assert re.search(r"if\(d\.yday\)\{var y=kstDay\(86400000\);\s*return \{from:y, to:y\};\}", src), \
        '어제가 하루 창(시작=끝=어제)이 아니다 — 오늘이 섞이면 거짓 화면'
    # 기본 갈래(모르는 값이면 7일) — 옛 하드코딩과 같은 창
    assert re.search(r"PD_DEFS\[pdSel\]\|\|PD_DEFS\['7'\]", src), \
        'pdRange 기본 갈래가 7일이 아니다'
    assert re.search(r"return \{from:kstDay\(d\.days\*86400000\), to:kstDay\(0\)\};", src), \
        '기간 창이 PD_DEFS.days 배선이 아니다'


def test_직접_기간_날짜칸은_16px_44px_이고_시작이_끝보다_늦으면_조회하지_않는다(client):
    html = _orders_html(client)
    # 날짜 입력 두 칸 — type=date + mo-date 클래스(마크업을 못 박는다)
    for _id in ('mo-pd-from', 'mo-pd-to'):
        assert re.search(r'<input type="date" class="mo-inp mo-date" id="%s"' % _id, html), \
            f'날짜 칸이 없다: {_id}'
    src = _tpl_src()
    rule = _css_rule(src, '.mo-inp.mo-date')
    flat = rule.replace(' ', '')
    m = re.search(r'font-size:([\d.]+)px', flat)
    assert m and float(m.group(1)) >= 16, \
        'iOS 는 16px 미만 입력칸 포커스에서 화면을 확대한다 — 날짜 칸 글자가 16px 미만'
    m = re.search(r'min-height:([\d.]+)px', flat)
    assert m and float(m.group(1)) >= 44, '날짜 칸 손끝 목표가 44px 미만'
    assert 'box-sizing:border-box' in flat, '날짜 칸에 box-sizing 이 없다(패딩이 높이를 흔든다)'
    # 시작>끝 — 조회하지 않고 안내만(분기 줄 자체를 못 박는다: loadAll 전에 return)
    assert re.search(r"if\(f>t\)\{[^}]*?msg\.className='mo-ed-msg bad show'; return;", src, re.S), \
        '시작>끝 안내·차단 갈래가 없다'
    # custom 무효면 loadAll 자체가 조회를 거부한다(빈 from/to 로 서버 기본 창이 몰래 조회 금지)
    assert re.search(r"function loadAll\(\)\{\s*if\(!pdValid\(\)\)return;", src), \
        'loadAll 에 pdValid 관문이 없다'
    assert re.search(r"return !!\(pdFrom&&pdTo&&pdFrom<=pdTo\);", src), \
        'pdValid 가 빈 칸·시작>끝을 거르지 않는다'


def test_기간_전환도_기존_loadSeq_세대번호_규약을_그대로_탄다():
    """칩 변경 → loadAll 재호출뿐(새 조회 경로 발명 금지). 늦게 온 옛 기간 응답은
    loadAll 안의 seq 검사(seq!==loadSeq → 버림)가 처리한다 — 그 배선을 못 박는다."""
    src = _tpl_src()
    # 기간 칩 핸들러가 loadAll 을 부른다(별도 fetch 금지)
    m = re.search(
        r"document\.querySelectorAll\('#mo-pd-chips \.mo-chip'\)\.forEach\(function\(ch\)\{"
        r".*?pdSel=ch\.dataset\.pd;.*?loadAll\(\);", src, re.S)
    assert m, '기간 칩이 loadAll 재호출 배선이 아니다'
    assert re.search(r"if\(pdSel==='custom'\)\{pdApply\(\);return;\}", src), \
        '「기간 직접」 갈래(pdApply — 유효할 때만 조회)가 없다'
    # loadAll 의 세대번호 발급 + 응답측 폐기 검사(기존 규약 그대로)
    assert re.search(r"var seq=\+\+loadSeq;", src), 'loadAll 의 세대번호 발급이 사라졌다'
    assert src.count('if(seq!==loadSeq)return;') >= 4, \
        '늦게 온 옛 응답을 버리는 seq 검사가 줄었다(기간 전환 시 옛 기간 데이터가 덮어쓴다)'
    # 날짜 입력도 같은 경로(pdApply → loadAll)
    assert re.search(r"getElementById\('mo-pd-from'\)\.addEventListener\('change',pdApply\)", src)
    assert re.search(r"getElementById\('mo-pd-to'\)\.addEventListener\('change',pdApply\)", src)


def test_빈_목록_안내는_고른_기간을_그대로_말한다():
    """30일을 보는데 「최근 7일 주문이 없어요」라 말하면 거짓 화면 — pdLabel 배선을 못 박는다."""
    src = _tpl_src()
    # [2026-08-06 4차] 안내가 기간에 더해 고른 마켓·계정(selLabel)까지 말한다 —
    #   기간 라벨 배선을 못 박는다는 뜻은 그대로다.
    assert re.search(r"esc\(pdLabel\(\)\)", src), \
        '빈 목록 안내가 기간 라벨 배선이 아니다'
    assert re.search(r"selLabel\(\)[^\n]*' 주문이 없어요", src), \
        '빈 목록 안내가 고른 마켓·계정을 말하지 않는다(왜 비었는지 알 수 없다)'
    assert not re.search(r"최근 7일 주문이 없어요", src), \
        '「최근 7일」 하드코딩 안내가 남아 있다(다른 기간에서 거짓 화면)'
    # [6차] 날짜를 아직 안 고른 「기간 직접」이 「 ~ 」라는 빈 문구로 새 나갔다
    #   (송장 판 설명이 「불러온 기간:  ~ 」로 보였다 — 실측으로 잡음).
    assert re.search(r"\(pdFrom&&pdTo\)\?\(pdFrom\+' ~ '\+pdTo\):'날짜 고르기 전'", src), \
        '날짜 고르기 전 「기간 직접」 라벨이 빈 「 ~ 」로 새 나간다'


# ────── [잔여 정합성] 기간을 말하는 **정적 문구**도 칩을 따라간다 ──────

class _AttrById(HTMLParser):
    """id → 그 태그의 속성 dict. title 같은 **속성**을 파서로 본다.

    (낱말 grep 은 주석·JS 문자열에 속는다 — 형제 시험들과 같은 처방.)
    """

    def __init__(self):
        super().__init__()
        self.attrs_by_id: dict[str, dict] = {}

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if d.get('id'):
            self.attrs_by_id[d['id']] = d


def _pd_chip_handler(src: str) -> str:
    """기간 칩 클릭 핸들러 본문만 잘라낸다(먼 곳의 호출에 속지 않게)."""
    m = re.search(r"#mo-pd-chips \.mo-chip'\)\.forEach\(function\(ch\)\{(.{0,800}?)\n  \}\);",
                  src, re.S)
    assert m, '기간 칩 클릭 핸들러를 못 찾았다'
    return m.group(1)


def test_송장판_송장없음_설명은_고른_기간을_말한다(client):
    """🔴 「불러온 7일분」 하드코딩 — 모수는 기간 칩이 정한 rows 라 30일·직접 기간에서
    거짓 설명이 된다. 정적 title 에 기간이 없고, pdLabel() 로 갱신되는 배선을 못 박는다."""
    html = _orders_html(client)
    p = _AttrById()
    p.feed(html)
    lab = p.attrs_by_id.get('mo-ship-noinv-l')
    assert lab is not None, \
        '「송장 없음」 라벨에 id(mo-ship-noinv-l)가 없다 — JS 가 설명을 갱신할 손잡이가 없다'
    title = lab.get('title') or ''
    assert '7일' not in title and '30일' not in title, \
        f'「송장 없음」 설명에 기간이 하드코딩됐다: {title!r}'

    src = _tpl_src()
    # 배선 — title 을 pdLabel() 로 다시 쓰는 줄 자체
    assert re.search(
        r"getElementById\('mo-ship-noinv-l'\);\s*\n?\s*if\(el\)el\.title='[^']*'\+pdLabel\(\)",
        src), '「송장 없음」 설명이 pdLabel() 배선이 아니다'
    # 기간이 바뀌는 자리마다 같이 갱신된다 — 렌더·칩·직접기간 세 경로
    assert re.search(r"function render\(\)\{\s*pdSyncTexts\(\);", src), \
        'render() 가 기간 문구를 갱신하지 않는다(마켓 응답 뒤 옛 설명이 남는다)'
    assert 'pdSyncTexts();' in _pd_chip_handler(src), \
        '기간 칩을 눌러도 설명이 안 바뀐다'
    assert re.search(r"pdFrom=f; pdTo=t;\s*\n?\s*pdSyncTexts\(\);", src), \
        '「기간 직접」 날짜를 바꿔도 설명이 안 바뀐다'


def test_마진판_week_칩_라벨도_고른_기간을_말한다(client):
    """마진 week 의 모수 = mgSubset → rows(기간 칩 창)다. 라벨만 「7일」로 못박히면
    30일을 보면서 「7일」이라 말하는 거짓 화면 — 매출 KPI 라벨과 같은 처방을 못 박는다."""
    html = _orders_html(client)
    p = _AttrById()
    p.feed(html)
    chip = p.attrs_by_id.get('mo-mg-week')
    assert chip is not None, '마진 week 칩에 id(mo-mg-week)가 없다 — 라벨 갱신 손잡이가 없다'
    assert chip.get('data-mg') == 'week', f'id 가 엉뚱한 칩에 붙었다: {chip}'

    src = _tpl_src()
    assert re.search(
        r"getElementById\('mo-mg-week'\);\s*\n?\s*if\(mw\)mw\.textContent=pdShort\(\)", src), \
        '마진 week 칩 라벨이 pdShort() 배선이 아니다'
    # 모수는 여전히 **목록과 같은 창** — 라벨만 바꾸고 뜻이 갈라지면 안 된다.
    #   [2026-08-06 4차] 그 창이 rows → visRows()(기간 + 마켓·계정)로 넓어졌고,
    #   목록(renderList)도 같은 함수를 쓰므로 「목록과 같다」는 뜻은 그대로다.
    assert re.search(r"function mgSubset\(\)\{[^}]*?return visRows\(\)\.slice\(\);", src, re.S), \
        'week 모수가 목록과 같은 창(visRows)이 아니다 — 라벨과 뜻이 갈라진다'


# ────────────────── 메뉴 등재(전체 메뉴) ──────────────────

def test_전체메뉴에_주문줄이_폰전용_배지로_실린다(client):
    r = client.get('/mobile/menu')
    assert r.status_code == 200
    p = _MenuRows()
    p.feed(r.get_data(as_text=True))
    rows = [x for x in p.rows if x['url'] == '/mobile/orders']
    assert rows, '전체 메뉴에 /mobile/orders 줄이 없다 — 주소를 직접 쳐야 하는 사고 재발'
