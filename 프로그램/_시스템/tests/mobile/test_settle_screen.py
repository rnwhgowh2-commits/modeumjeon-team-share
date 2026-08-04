# -*- coding: utf-8 -*-
"""E-1 정산 요약 폰 화면(/mobile/settle) — 기간 칩 + KPI 2칸 + 마켓별 막대.

사장님 확정(2026-08-04, 「모음전 폰 화면 일괄 시안 v1.html」 fE1): 기간 칩
(이번 주/지난 주/이번 달) + KPI 2칸(정산 예정/완료) + 마켓별 가로 막대(오른쪽
tabular 금액). **시안=코드**(chips·kgrid·bar 부품 구조 그대로).

무엇을 지키나
    ① 화면 200 + 시안 구조(chips·kgrid 2칸·bar 부품 CSS) + 메뉴 등록.
    ② 기간 칩 배선 — 템플릿 data-period 값 ⊆ 서버 PERIODS. 서버는 모르는
       period 를 400 으로 거절하고, 기간마다 **다른 행**을 읽는다(지난주 행이
       이번 주 합에 섞이면 빨강).
    ③ 🔴 정산액·근거의 단일 원천 = `sell_source._settlement_for`(마진계산기
       정산=주문내역 단일원천 — 그 함수 그대로). 라우트가 금액을 스스로 다시
       정하면(재유도) monkeypatch 시험이 잡는다. 분류(확정/추정/취소/미확인)는
       `pipeline._TAG_RANK` 에서 유도 — 같은 서열 두 곳 금지.
    ④ 모르면 '-' — 미확인(none) 행의 금액은 **합에 안 넣고 건수로만** 센다
       (0 으로 둔갑 금지). 저장분이 아예 없으면 store_empty 로 밝히고 폰은
       '-' + 이유를 그린다. 저장분 없는 마켓은 missing 으로 밝힌다(부분합을
       전체인 척 금지).
    ⑤ 막대 눈금 정직성 — 최대 마켓 = 100% 상대 눈금임을 화면에 밝히고,
       각 막대에 실제 금액이 붙는다(폭 하드코딩 금지 — Math.max 계산).
    ⑥ 주소 drift — 템플릿의 askServer 주소 전수가 실라우트에 있다.
    ⑦ 폴링 없음(setInterval 금지) · ISO Date 파싱 없음(서버 포맷 문자열만).

★ '낱말이 어딘가 있나'로 검사하지 않는다 — API 는 JSON 값 자체를, 템플릿은
  그 줄·규칙 본문을 정규식으로 못 박는다(형제 화면에서 네 번 헛통과한 함정).
"""
import datetime as _dt
import re
from pathlib import Path

import pytest

# flask_app 픽스처는 tests/mobile/conftest.py 에 있다.

_TPL = Path(__file__).resolve().parents[2] / 'webapp' / 'templates' / 'mobile' / 'settle.html'


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


def _tpl_src() -> str:
    assert _TPL.exists(), f'템플릿이 없다: {_TPL}'
    return _TPL.read_text(encoding='utf-8')


def _kst_today() -> _dt.date:
    """시험 쪽 독립 계산 — 라우트의 날짜 산식을 가져다 쓰면 자기 대조가 된다."""
    kst = _dt.timezone(_dt.timedelta(hours=9))
    return _dt.datetime.now(kst).date()


# ════════════════════════════════════════════════════════════
#  준비물 — 저장분(market_order_lines)에 정산 갈래별 행을 심는다
# ════════════════════════════════════════════════════════════

_UID = 'MST-{}'   # line_uid 접두 — 시험 행만 정확히 지우기 위한 표식


@pytest.fixture
def seeded(flask_app):
    """이번 주(오늘) 5행 + 지난주 1행.

    갈래: real(확정 10,000) · estimated(추정 5,000) · none(미확인 — 금액 없음) ·
    zero_cancel(취소완료 — 정산 0 확정) · 11번가 real(3,000·마켓 2번째) ·
    지난주 real(20,000 — 이번 주 합에 섞이면 안 된다).

    🔴 데이터를 **만드는** 픽스처다 — 진짜 DB(PostgreSQL)면 안 돈다.
    """
    from tests.mobile.conftest import require_sqlite
    require_sqlite()

    from lemouton.markets.models_orders import MarketOrderLine
    from shared.db import SessionLocal

    today = _kst_today()
    monday = today - _dt.timedelta(days=today.weekday())
    last_week_day = monday - _dt.timedelta(days=2)      # 지난주 토요일
    d_now = today.strftime('%Y-%m-%d') + ' 10:00:00'
    d_last = last_week_day.strftime('%Y-%m-%d') + ' 10:00:00'

    def _row(market_key, 판매처, no, date, status, settle, tag, extra=None):
        r = {'_line_uid': f'{market_key}|{_UID.format(no)}', '판매처': 판매처,
             '오픈마켓주문번호': _UID.format(no), '주문일': date, '주문상태': status,
             '상품명': '시험상품', '수량': 1, '배송비': 0}
        if settle is not None:
            r['정산예정금액'] = settle
        if tag is not None:
            r['_settle_source'] = tag
        r.update(extra or {})
        return MarketOrderLine(line_uid=r['_line_uid'], market=market_key,
                               order_no=r['오픈마켓주문번호'], order_date=date,
                               status=status, row=r)

    lines = [
        _row('coupang', '쿠팡', 'A1', d_now, '배송완료', 10000, 'real'),
        _row('coupang', '쿠팡', 'A2', d_now, '배송완료', 5000, 'estimated'),
        # 미확인 — 금액·근거 없음(쿠팡이라 추정 산식도 없다 → none 확정)
        _row('coupang', '쿠팡', 'A3', d_now, '배송완료', None, None),
        _row('coupang', '쿠팡', 'A4', d_now, '취소완료', None, 'zero_cancel'),
        _row('eleven11', '11번가', 'B1', d_now, '배송완료', 3000, 'real'),
        _row('coupang', '쿠팡', 'C1', d_last, '배송완료', 20000, 'real'),
    ]
    s = SessionLocal()
    try:
        for ln in lines:
            s.merge(ln)
        s.commit()
        yield {'today': d_now[:10], 'last': d_last[:10]}
    finally:
        try:
            s.query(MarketOrderLine).filter(
                MarketOrderLine.order_no.like(_UID.format('%'))).delete(
                synchronize_session=False)
            s.commit()
        finally:
            s.close()


# ════════════════════════════════════════════════════════════
#  ① 화면 · 메뉴
# ════════════════════════════════════════════════════════════

def test_화면이_뜨고_시안_구조가_있다(client):
    r = client.get('/mobile/settle')
    assert r.status_code == 200, f'정산 요약 폰 화면이 안 열린다(status={r.status_code})'
    html = r.get_data(as_text=True)
    # fE1 구조 — 기간 칩 3개 + KPI 그릇 + 막대 그릇.
    assert re.search(r'class="chips"', html), '기간 칩 줄(.chips)이 없다'
    assert html.count('data-period=') >= 3, '기간 칩이 3개 미만이다'
    assert 'id="st-kpis"' in html, 'KPI 그릇(st-kpis)이 없다'
    assert 'id="st-bars"' in html, '막대 그릇(st-bars)이 없다'
    # 시안 부품 CSS 가 규칙 본문으로 실재한다(낱말 아님).
    src = _tpl_src()
    for cls, needle in (('.chip.on', 'background'), ('.kgrid', 'grid-template-columns'),
                        ('.btrk', 'border-radius'), ('.bfill', 'background'),
                        ('.num', 'tabular-nums')):
        m = re.search(re.escape(cls) + r'[^{]*\{([^}]*)\}', src)
        assert m, f'시안 부품 {cls} 규칙이 없다'
        assert needle.split(':')[0] in m.group(1), f'{cls} 규칙에 {needle} 이 없다'
    # KPI 2칸 — 이름은 정직 어휘(완료→확정: 입금 사실은 데이터에 없다).
    assert '정산 예정' in src and '정산 확정' in src, \
        'KPI 이름(정산 예정/정산 확정)이 시안 구조에서 빠졌다'


def test_메뉴_목록에_실렸다():
    from webapp.routes.mobile_shell import PHONE_NATIVE_ROWS
    rows = [it for it in PHONE_NATIVE_ROWS if it['url'] == '/mobile/settle']
    assert rows, '/mobile/settle 이 PHONE_NATIVE_ROWS 에 없다 — 메뉴에서 못 들어간다'
    assert rows[0]['name'] == '정산 요약'
    # PC 주문·마진 화면(/orders·margin-embed)엔 admin 게이트가 없다 — 폰만 잠그면
    # 두 화면이 다른 답을 낸다(D-1 과 같은 원칙).
    assert not rows[0].get('admin_only'), 'PC 정산 화면은 안 잠겨 있는데 폰만 잠갔다'


# ════════════════════════════════════════════════════════════
#  ② 기간 칩 배선
# ════════════════════════════════════════════════════════════

def test_칩의_period_값은_서버가_아는_값뿐이다():
    """템플릿 data-period ⊆ 라우트 PERIODS — 칩 하나가 400 만 내는 죽은 단추 방지."""
    from webapp.routes.mobile_settle import PERIODS
    vals = set(re.findall(r'data-period="([^"]+)"', _tpl_src()))
    assert vals, '기간 칩(data-period)이 템플릿에 없다'
    assert vals <= set(PERIODS), f'서버가 모르는 기간 칩이 있다: {vals - set(PERIODS)}'
    assert len(vals) == 3, '기간 칩은 시안대로 3개(이번 주/지난 주/이번 달)여야 한다'


def test_모르는_period_는_400(client):
    r = client.get('/mobile/settle/api/summary?period=yesterday')
    assert r.status_code == 400
    assert r.get_json()['ok'] is False


def test_기간마다_다른_행을_읽는다(client, seeded):
    """지난주 행(20,000)이 이번 주 합에 섞이면 빨강 — period 무시 변조 차단."""
    jw = client.get('/mobile/settle/api/summary?period=this_week').get_json()
    jl = client.get('/mobile/settle/api/summary?period=last_week').get_json()
    assert jw['ok'] and jl['ok']
    assert jw['kpi']['confirmed']['sum'] == 13000, \
        f"이번 주 확정 합이 10,000+3,000 이 아니다: {jw['kpi']['confirmed']}"
    assert jl['kpi']['confirmed']['sum'] == 20000, \
        f"지난주 확정 합이 20,000 이 아니다: {jl['kpi']['confirmed']}"
    # 이번 달 — 오늘 행은 항상 들어간다(저장분 DB 읽기라 월 범위도 가볍다).
    jm = client.get('/mobile/settle/api/summary?period=this_month').get_json()
    assert jm['ok']
    assert jm['kpi']['confirmed']['sum'] >= 13000


# ════════════════════════════════════════════════════════════
#  ③ 단일 원천 — _settlement_for · _TAG_RANK
# ════════════════════════════════════════════════════════════

def test_갈래별_합이_정확하다(client, seeded):
    j = client.get('/mobile/settle/api/summary?period=this_week').get_json()
    assert j['ok']
    assert j['kpi']['pending'] == {'sum': 5000, 'rows': 1}
    assert j['kpi']['confirmed'] == {'sum': 13000, 'rows': 2}
    # 🔴 미확인은 **건수로만** — 금액을 0 으로 합에 넣으면 여기서 잡는다.
    assert j['unknown_rows'] == 1
    assert j['cancel_rows'] == 1
    # 마켓별 막대 — 큰 순서. 금액은 서버 값 그대로.
    mk = {m['key']: m for m in j['markets']}
    assert mk['coupang']['confirmed'] == 10000
    assert mk['coupang']['pending'] == 5000
    assert mk['coupang']['total'] == 15000
    assert mk['coupang']['unknown_rows'] == 1
    assert mk['eleven11']['total'] == 3000
    totals = [m['total'] for m in j['markets']]
    assert totals == sorted(totals, reverse=True), '막대가 큰 순서가 아니다'


def test_정산액은_settlement_for_한_곳에서만_나온다(client, seeded, monkeypatch):
    """🔴 재유도 금지 — 라우트가 `sell_source._settlement_for` 를 안 거치고 행의
    금액을 직접 읽으면(같은 산식 두 곳) 이 시험이 잡는다."""
    import lemouton.margin.sell_source as _ss
    monkeypatch.setattr(_ss, '_settlement_for', lambda row: (7777, 'real'))
    j = client.get('/mobile/settle/api/summary?period=this_week').get_json()
    assert j['ok']
    # 이번 주 5행 전부 (7777, real) → 확정 5건 × 7,777.
    assert j['kpi']['confirmed'] == {'sum': 7777 * 5, 'rows': 5}, \
        '정산액이 _settlement_for 를 거치지 않는다 — 단일 원천 위반'
    assert j['kpi']['pending'] == {'sum': 0, 'rows': 0}


def test_분류는_TAG_RANK_에서_유도된다():
    """확정/추정/취소 태그 집합 = pipeline._TAG_RANK 서열에서 유도(사본 금지)."""
    from lemouton.margin.pipeline import _TAG_RANK
    from webapp.routes.mobile_settle import _CANCEL_TAGS, _CONFIRMED_TAGS, _PENDING_TAGS
    assert _CONFIRMED_TAGS == {t for t, r in _TAG_RANK.items() if r == 3}
    assert _PENDING_TAGS == {t for t, r in _TAG_RANK.items() if r == 2}
    assert _CANCEL_TAGS == {t for t, r in _TAG_RANK.items() if r == 1}


# ════════════════════════════════════════════════════════════
#  ④ 모르면 '-' · 부분 데이터 밝히기
# ════════════════════════════════════════════════════════════

def test_저장분이_아예_없으면_store_empty(client, monkeypatch):
    """coverage 가 빈손이면 0 을 그리지 않고 store_empty 로 밝힌다 → 폰은 '-'."""
    from lemouton.markets import order_store as _os
    monkeypatch.setattr(_os, 'coverage', lambda **kw: [])
    monkeypatch.setattr(_os, 'load', lambda *a, **kw: [])
    j = client.get('/mobile/settle/api/summary?period=this_week').get_json()
    assert j['ok']
    assert j['store_empty'] is True
    assert j['markets'] == []


def test_저장분_없는_마켓은_missing_으로_밝힌다(client, seeded):
    """지원 마켓 중 저장분이 없는 마켓 라벨이 missing 에 나온다(부분합 명시)."""
    from lemouton.markets.order_export import market_label, supported_markets
    j = client.get('/mobile/settle/api/summary?period=this_week').get_json()
    assert j['ok']
    from lemouton.markets import order_store as _os
    covered = {c['market'] for c in _os.coverage()}
    want = sorted(market_label(m) for m in supported_markets() if m not in covered)
    assert j['missing'] == want


def test_읽기_실패는_에러로_말한다(client, monkeypatch):
    """저장분 읽기가 죽으면 0 이 아니라 실패를 말한다 → 폰은 '-' + 이유."""
    from lemouton.markets import order_store as _os

    def _boom(*a, **kw):
        raise RuntimeError('db down')
    monkeypatch.setattr(_os, 'load', _boom)
    r = client.get('/mobile/settle/api/summary?period=this_week')
    assert r.status_code == 500
    assert r.get_json()['ok'] is False


def test_폰은_값_없으면_빼기표를_그린다():
    """render 갈래 — null → '-'(0·빈칸 둔갑 금지) + 실패·store_empty 갈래."""
    src = _tpl_src()
    assert re.search(r"==\s*null\s*\?\s*'-'", src), "값 없음 → '-' 갈래가 폰 JS 에 없다"
    assert re.search(r"store_empty", src), 'store_empty(저장분 없음) 갈래가 없다'
    assert '저장된 주문이 없어요' in src, 'store_empty 이유 문구가 없다'


# ════════════════════════════════════════════════════════════
#  ⑤ 막대 눈금 정직성
# ════════════════════════════════════════════════════════════

def test_막대는_최대_마켓_기준_상대눈금임을_밝힌다():
    src = _tpl_src()
    m = re.search(r'{%\s*block extra_script\s*%}(.*?){%\s*endblock\s*%}', src, re.S)
    assert m, 'extra_script 블록이 없다'
    js = m.group(1)
    # 폭은 계산이다 — Math.max 로 최대값을 구해 비율을 낸다(하드코딩 금지).
    assert 'Math.max' in js, '막대 폭이 최대값 계산(Math.max)으로 나오지 않는다'
    assert not re.search(r"bfill[^>]*width:\s*\d+%", js), '막대 폭이 하드코딩돼 있다'
    # 눈금 설명 — 상대 눈금임을 화면 글자로 밝힌다(숨은 눈금 금지).
    assert '가장 큰 마켓' in src, '상대 눈금 설명(가장 큰 마켓 대비)이 화면에 없다'


# ════════════════════════════════════════════════════════════
#  ⑥ 주소 drift · ⑦ 폴링/ISO 금지
# ════════════════════════════════════════════════════════════

def test_폰이_부르는_주소가_전부_실라우트다(flask_app):
    src = _tpl_src()
    urls = set(re.findall(r"askServer\('([^']+)'", src))
    assert urls, 'askServer 주소가 하나도 없다 — 추출 정규식이 죽었다'
    rules = {r.rule for r in flask_app.url_map.iter_rules()}
    for u in urls:
        path = u.split('?', 1)[0]
        assert path in rules, f'폰이 부르는 {path} 가 실라우트에 없다(주소 drift)'


def test_폴링과_ISO_날짜파싱이_없다():
    src = _tpl_src()
    assert 'setInterval' not in src, '정산 요약은 폴링하지 않는다(요청 시 1회)'
    assert 'new Date(' not in src, \
        'ISO 문자열 Date 파싱 금지 — 기간 표기는 서버 포맷 문자열을 그대로 그린다'
