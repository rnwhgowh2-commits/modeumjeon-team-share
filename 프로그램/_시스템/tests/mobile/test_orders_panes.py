# -*- coding: utf-8 -*-
"""배치5-2차 — 주문 폰 화면의 송장(A-1+A-4)·CS(B-2)·마진(C-4) 알약 채움.

사장님 확정(2026-08-04, 「모음전 폰 화면 일괄 시안 v1.html」 — 스펙 §6):
    A 송장 = A-1+A-4 합침(위 현황 3칸 + 아래 대기 목록, 줄 눌러 그 자리 입력)
    B CS   = B-2(유형 칩으로 거르는 목록 — cs/claims.json + cs/inquiries.json)
    C 마진 = C-4(기간 칩 + 숫자 6칸)

무엇을 지키나 (전부 배선·정의를 못 박는다 — 낱말 검사 금지)
    ① 🔴 송장 저장 = **기존 PC 엔드포인트**(/orders/invoice/send) 재사용 — 새 쓰기
       경로 발명 금지(스펙 §6). 템플릿의 모든 askServer 주소가 orders.py 실라우트에
       존재하는지 전수 대조(drift 시험).
    ② 🔴 같은 숫자 두 정의 금지 — CS 는 위 알약 개수·전체 칩·목록이 전부
       csItems() 한 목록에서 나온다. 1차의 rows 정규식 수(csN)는 제거됐어야 한다.
    ③ 발송대기 = 「송장」 칩과 송장 판 KPI 가 같은 함수(shipRowsOf) — 두 수가
       갈라질 수 없는 구조를 못 박는다.
    ④ 모르면 '-' — 오늘 발송(flow-daily 실패)·CS 부분 실패·마진(price-diff 실패,
       원가 모름)은 0 이 아니라 '-'. 부분값은 「N/M건 기준」으로 밝힌다.
    ⑤ C-4 「이번 달」 — 마켓 실조회가 월 단위론 못 감당(6마켓 7일 실측 ~60초).
       숫자를 지어내는 대신 이유+PC 링크를 그린다. month 갈래에서 합계 계산 금지.
    ⑥ 판정 원천은 서버 주입 — SENDABLE(invoice_send.SUPPORTED_SEND)·
       SHIPPED(order_export._SHIPPED_STATES)를 JS 에 손으로 적지 않는다.
    ⑦ PC 와의 사본(COURIERS·hasInvoice)은 동일성을 못 박는다(WAIT 시험과 같은 처방).
    ⑧ 렌더된 화면의 JS 가 실제로 파싱된다(node --check — node 없으면 skip).
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from test_orders_screen import _IdText, _orders_html, _tpl_src

_SYS = Path(__file__).resolve().parents[2]
_PC = _SYS / 'webapp' / 'templates' / 'orders' / 'index.html'
_ROUTES = _SYS / 'webapp' / 'routes' / 'orders.py'


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


def _pc_src() -> str:
    return _PC.read_text(encoding='utf-8')


# ────────────── ① 송장 저장 = 기존 엔드포인트(새 쓰기 경로 금지) ──────────────

def test_송장_저장은_기존_PC_전송_엔드포인트를_그대로_쓴다():
    src = _tpl_src()
    # 주소 자체를 못 박는다 — 폰 전용 저장 라우트를 새로 파면 여기서 잡힌다.
    assert "askServer('/orders/invoice/send'" in src, \
        '송장 저장이 기존 /orders/invoice/send 배선이 아니다(새 쓰기 경로 발명 금지)'
    # payload 는 PC invSend 와 같은 키 — 서버가 '이미 발송된 주문' 덮어쓰기를 막는 근거(status)와
    # ESM 전송 식별자(send_ids)가 빠지면 조용히 다른 동작이 된다.
    m = re.search(r"askServer\('/orders/invoice/send'.*?body:JSON\.stringify\((\{.*?\})\)\}\)", src, re.S)
    assert m, '전송 payload 를 못 찾았다'
    for key in ('live:', 'market:', 'order_no:', 'courier:', 'invoice_no:', 'alias:', 'send_ids:', 'status:'):
        assert key in m.group(1), f'전송 payload 에 {key} 가 없다(PC invSend 와 동일해야 한다)'
    assert "r['_send_ids']||null" in m.group(1), 'send_ids 가 행의 _send_ids 배선이 아니다'


def test_폰이_부르는_모든_주소는_orders_라우트에_실존한다():
    """askServer 주소 전수 → orders.py 의 @bp.route/@bp.post 와 대조(drift 시험).

    서버 쪽 주소가 바뀌면(라우트 개명·삭제) 폰만 조용히 죽는 사고를 여기서 막는다.
    """
    src = _tpl_src()
    routes = _ROUTES.read_text(encoding='utf-8')
    urls = set(re.findall(r"askServer\('(/orders/[^']+)'", src))
    assert urls, 'askServer 주소가 하나도 없다 — 추출 정규식이 죽었다'
    for u in urls:
        path = u.split('?')[0][len('/orders'):]
        assert re.search(r"@bp\.(?:route|post)\('" + re.escape(path) + r"'", routes), \
            f'폰이 부르는 {u} 가 orders.py 라우트에 없다(주소 drift)'


# ────────────── ② CS — 같은 숫자 두 정의 금지(단일 원천) ──────────────

def test_CS_수는_알약_전체칩_목록이_한_목록에서_나온다():
    src = _tpl_src()
    # 위 알약 = csTotal() / 전체 칩 = 같은 total 변수 / total = csItems().length.
    assert re.search(r"setCnt\('mo-cnt-cs',\s*csTotal\(\)\)", src)
    assert re.search(r"var\s+total=csTotal\(\),\s*items=csItems\(\)", src)
    assert re.search(r"setCnt\('mo-cs-n-all',\s*total\)", src)
    assert re.search(r"return csItems\(\)\.length", src), \
        'csTotal 이 csItems()(목록 그 자체)의 길이가 아니다'
    # 1차의 rows 정규식 수(csN)는 제거됐어야 한다 — 남아 있으면 두 정의가 공존한다.
    assert not re.search(r"var\s+csN\s*=", src), \
        '1차의 rows 기반 CS 수(csN)가 남아 있다 — 판(claims+문의)과 다른 답을 낸다'


def test_CS_부분_실패는_전체를_대시로_남긴다():
    """클레임·문의 중 한쪽이 죽었을 때 남은 쪽만 합쳐 「전체 N」이라 말하면
    부분합을 전체인 척하는 것이다 — null('-') 갈래를 못 박는다."""
    src = _tpl_src()
    assert re.search(
        r"if\(cs\.cFail\|\|cs\.iFail\|\|cs\.claims===null\|\|cs\.inqs===null\)return null", src), \
        'CS 총계의 부분 실패 갈래(null → -)가 없다'
    # 실패한 원천의 유형 칩도 '-' — 클레임 실패면 취소·반품·교환을 0 으로 그리지 않는다.
    assert re.search(r"setCnt\('mo-cs-n-cancel',\s*cOk\?cnt\['취소'\]:null\)", src)
    assert re.search(r"setCnt\('mo-cs-n-inq',\s*iOk\?cnt\['문의'\]:null\)", src)


def test_CS_는_기존_claims_inquiries_엔드포인트_배선이다():
    src = _tpl_src()
    assert "askServer('/orders/cs/claims.json?markets='" in src
    assert "askServer('/orders/cs/inquiries.json?markets='" in src
    # 처음 열 때 1회만 — 화면 열 때마다 마켓 문의 API 를 치지 않는다.
    assert re.search(r"if\(ch\.dataset\.pane==='cs'&&!cs\.req\)\{csLoad\(loadSeq\);\}", src)


# ────────────── ③ 송장 — 칩·KPI 가 같은 함수 ──────────────

def test_발송대기는_칩과_송장판_KPI_가_같은_함수다():
    src = _tpl_src()
    # 칩: var shipN=shipRowsOf().length (test_orders_screen 이 못 박음)
    # KPI: 같은 shipRowsOf() 결과(sr)를 그대로 센다 — 정규식·복사식 재정의 금지.
    assert re.search(r"var\s+sr=shipRowsOf\(\);", src)
    assert re.search(r"setKpi\('mo-ship-wait',\s*okAny\?String\(sr\.length\):'-'\)", src), \
        '송장 판 발송대기가 shipRowsOf() 배선이 아니다(칩과 갈라질 수 있는 구조)'


def test_송장없음은_서버가_준_SHIPPED_상태와_hasInvoice_로_판정한다():
    src = _tpl_src()
    # 서버 주입(사본 금지) — 손으로 적은 상태 목록이면 flow_daily 와 갈라진다.
    assert '{{ shipped_states|tojson }}' in src
    assert '{{ sendable|tojson }}' in src
    assert re.search(r"SHIPPED\[String\(r\['주문상태'\]\|\|''\)\.trim\(\)\]\s*&&\s*!hasInvoice\(r\)", src), \
        '「송장 없음」 판정이 SHIPPED(서버 원천)+hasInvoice 배선이 아니다'


def test_서버가_주는_SENDABLE_SHIPPED_는_파이썬_원천과_같다(client):
    """렌더된 화면의 JSON 이 invoice_send.SUPPORTED_SEND·order_export._SHIPPED_STATES
    그대로인지 — 라우트가 다른 걸 주입하면(오타·부분집합) 여기서 잡힌다."""
    from lemouton.markets.invoice_send import SUPPORTED_SEND
    from lemouton.markets.order_export import _SHIPPED_STATES
    html = _orders_html(client)
    assert json.dumps(sorted(SUPPORTED_SEND), ensure_ascii=False) in html.replace('", "', '", "'), \
        'SENDABLE 이 SUPPORTED_SEND 원문이 아니다'
    blob = json.dumps(sorted(_SHIPPED_STATES), ensure_ascii=False)
    # tojson 은 유니코드 이스케이프를 쓸 수 있어 정규화 비교(파싱해서 대조).
    m = re.search(r"var SHIPPED = \{\};\s*\((\[.*?\])\)\.forEach", html, re.S)
    assert m, 'SHIPPED 주입 블록이 없다'
    assert sorted(json.loads(m.group(1))) == sorted(_SHIPPED_STATES), \
        f'SHIPPED 주입값이 _SHIPPED_STATES 와 다르다: {m.group(1)}'
    m2 = re.search(r"var SENDABLE = \{\};\s*\((\[.*?\])\)\.forEach", html, re.S)
    assert m2, 'SENDABLE 주입 블록이 없다'
    assert sorted(json.loads(m2.group(1))) == sorted(SUPPORTED_SEND)
    assert blob  # (참조 유지)


def test_오늘발송은_flow_daily_원천이고_실패면_대시다():
    src = _tpl_src()
    assert "askServer('/orders/flow-daily.json?days=1')" in src, \
        '오늘 발송이 flow-daily(적재분·마켓 호출 0) 원천이 아니다'
    # 실패·미도착 → '-' (0 으로 지어내지 않는다) + 설명줄도 비운다
    assert re.search(
        r"if\(!shipSentLoaded\|\|shipSent==null\)\{\s*setKpi\('mo-ship-sent','-'\);\s*setShipNote\(''\);\s*\}", src)


def test_오늘발송_한계는_tooltip_이_아니라_인라인_문구로_말한다():
    """[검토 반영] 폰엔 hover 가 없다 — title 툴팁의 +? 는 뜻을 알 수 없는 기호였다.

    ① 못 세는 건수는 설명줄에 **변수 배선**으로 넣는다(숫자 하드코딩이면 실패).
       unknown 은 「발송일 정보가 없는 건」이라 오늘 것인지도 모른다 — 「오늘 N건」 단정 금지.
    ② 적재분 기준(방금 보낸 송장은 빠질 수 있음)도 같은 줄에 밝힌다.
    """
    src = _tpl_src()
    assert '+?' not in src, '+? 툴팁 표기가 남아 있다(폰에서 뜻을 알 수 없다)'
    # 못 세는 건수 — shipSentUnknown 변수가 문구에 배선돼 있다.
    assert re.search(
        r"shipSentUnknown>0\?' · 발송일 정보가 없는 '\+shipSentUnknown\+'건[^']*은 못 셉니다':''", src), \
        '못 세는 건수의 인라인 설명(변수 배선)이 없다'
    # 문구가 「오늘」을 단정하지 않는다.
    m = re.search(r"' · 발송일 정보가 없는 '[^\n]*", src)
    assert m and '오늘' not in m.group(0), \
        'unknown 건수 문구가 「오늘」을 단정한다 — 날짜가 없어 오늘 것인지 알 수 없다'
    # 적재분 기준(신선도) 안내 — setShipNote 로 실제 그린다.
    assert re.search(r"setShipNote\('「오늘 발송」은 저장해 둔 주문\(적재분\) 기준", src), \
        '적재분 기준(방금 보낸 송장은 빠질 수 있음) 안내가 없다'
    assert re.search(r"function setShipNote\(t\)\{", src)
    assert 'id="mo-ship-note"' in src, '설명줄을 그릴 자리(mo-ship-note)가 없다'


def test_사본_동일성_COURIERS_와_hasInvoice_는_PC_와_같다():
    pc, mo = _pc_src(), _tpl_src()

    def couriers_of(src, name):
        m = re.search(r"var COURIERS=\[([^\]]+)\];", src)
        assert m, f'{name} 에서 COURIERS 를 못 찾았다'
        return m.group(1).replace(' ', '')

    assert couriers_of(pc, 'PC') == couriers_of(mo, '폰'), \
        '택배사 목록이 PC 와 갈라졌다 — 같은 택배사를 다른 이름으로 보내게 된다'

    def has_inv_of(src, name):
        m = re.search(r"function hasInvoice\(r\)\{(.*?)\}", src, re.S)
        assert m, f'{name} 에서 hasInvoice 를 못 찾았다'
        return re.sub(r"\s+|//[^\n]*", '', m.group(1))

    assert has_inv_of(pc, 'PC') == has_inv_of(mo, '폰'), \
        '「이미 송장 있음」 판정이 PC 와 갈라졌다(센티넬 취급 차이 = 이중송장 위험)'


def test_전송중_버튼은_잠기고_스위치꺼짐은_저장안됨을_말한다():
    src = _tpl_src()
    # 전송 중 — 버튼 disabled + 라벨 변경(눌린 척·이중 전송 금지). 잠금은 CSS 로도 보인다.
    assert re.search(r"sendBusy\?' disabled':''", src)
    assert re.search(r"\.mo-savebtn\[disabled\]\{[^}]*opacity", src), \
        '전송 중 잠금이 눈에 안 보인다(disabled 스타일 없음)'
    # 서버 실전송 스위치 OFF(dry_run) — 보낸 척 금지.
    assert '마켓에는 저장되지 않았습니다' in src
    # 마켓이 실제 등록한 번호가 입력값과 다르면 숨기지 않는다(PC 빨간 경고와 같은 원칙).
    assert re.search(r"mismatch:!!\(got&&got!==inv\)", src)


# ────────────── ⑤ 마진(C-4) ──────────────

def test_마진판_기간칩과_6칸이_있고_초기값은_대시다(client):
    html = _orders_html(client)
    ids = _IdText()
    ids.feed(html)
    for k in ('mo-mg-sales', 'mo-mg-margin', 'mo-mg-rate',
              'mo-mg-orders', 'mo-mg-cancel', 'mo-mg-loss',
              'mo-ship-wait', 'mo-ship-sent', 'mo-ship-noinv',
              'mo-cs-n-all', 'mo-cs-n-cancel', 'mo-cs-n-return',
              'mo-cs-n-exchange', 'mo-cs-n-inq'):
        assert k in ids.texts, f'칸이 없다: {k}'
        assert ids.texts[k] == '-', f'{k} 초기값이 - 가 아니다: {ids.texts[k]!r}'
    for p in ('today', 'week', 'month'):
        assert f'data-mg="{p}"' in html, f'기간 칩이 없다: {p}'


def test_마진_기간칩은_배선이고_이번달은_숫자_대신_이유를_말한다():
    src = _tpl_src()
    assert re.search(r"mgPeriod=ch\.dataset\.mg", src), '기간 칩이 dataset 배선이 아니다'
    # month 갈래 — 격자 숨김+안내 판을 그리고 **계산 전에 return**(합계 지어내기 금지).
    assert re.search(r"var month=\(mgPeriod==='month'\);", src)
    assert re.search(r"if\(month\)return;", src), \
        '이번 달 갈래가 계산으로 흘러든다 — 월 합계를 지어낼 수 있는 구조'
    assert '/orders/?tab=margin' in src, '이번 달 안내에 PC 마진 계산기 링크가 없다'


def test_마진판_매출은_오늘매출_KPI_와_같은_함수다():
    src = _tpl_src()
    # 3-C 매출 KPI 와 C-4 매출이 같은 salesOf() — 한 화면에 두 산식 금지.
    # [2026-08-06 사장님 확정] KPI 매출은 기간 칩을 따라간다 — rows(서버가 실주문일
    # from/to 로 거른 그 기간 전체)를 합하고, 라벨(mo-kpi-sales-l)도 같이 바뀐다.
    # [2026-08-06 4차] 모수가 rows → visRows() 로 넓어졌다(기간 칩 + 마켓·계정 칩).
    #   visRows() 는 rows 에서 파생하므로 「기간을 따라간다」는 이 시험의 뜻은 그대로고,
    #   todayRows 로 되돌아가는 퇴행도 여전히 여기서 잡힌다(대안 목록에 없다).
    assert re.search(r"var sub=visRows\(\);", src), \
        '매출 KPI 모수가 visRows()(기간+마켓·계정) 배선이 아니다'
    assert re.search(r"setKpi\('mo-kpi-sales',\s*won\(salesOf\(sub\)\)", src), \
        '매출 KPI 가 기간을 안 따른다 — todayRows 로 돌아가면 기간 칩과 모순 화면'
    assert re.search(r"getElementById\('mo-kpi-sales-l'\)\.textContent=pdShort\(\)\+' 매출'", src), \
        '매출 라벨이 기간을 안 따른다 — 「7일 매출」이라 쓰고 30일 합을 보여주는 거짓 화면'
    assert re.search(r"id=\"mo-kpi-sales-l\"", src), 'KPI 매출 라벨 요소가 없다'
    assert re.search(r"put\('mo-mg-sales',\s*won\(salesOf\(sub\)\)", src)
    assert re.search(r"function salesOf\(sub\)\{", src)
    # 취소 제외 규칙도 한 정의(CANCEL_RE)를 매출·취소칸이 같이 쓴다.
    assert re.search(r"var CANCEL_RE=/취소완료\|취소요청/;", src)
    assert re.search(r"CANCEL_RE\.test\(r\['주문상태'\]", src)


def test_마진_모름은_대시고_부분값은_N분의M_로_밝힌다():
    src = _tpl_src()
    # price-diff 실패·원가 아는 행 0 → 마진·마진율·적자 전부 '-'.
    assert re.search(
        r"if\(!pdxOk\|\|!kn\)\{\s*put\('mo-mg-margin',null\);\s*put\('mo-mg-rate',null\);\s*put\('mo-mg-loss',null\);", src), \
        '마진 모름 갈래(- 처리)가 없다'
    # 일부만 알면 「원가를 아는 N/M건 기준」을 밝힌다(조용한 부분합 금지).
    assert re.search(r"if\(kn<act\.length\)note='[^']*'\+kn\+'/'\+act\.length\+'건 기준", src), \
        '부분값(N/M건 기준) 안내가 없다'
    # 적자 = 원가를 아는 행 중 margin<0 만 — 모르는 행을 적자 0 으로 섞지 않는다.
    assert re.search(r"if\(d\.margin<0\)lossN\+\+;", src)


# ────────────── ⑧ 렌더된 JS 실파싱 ──────────────

def test_렌더된_화면_JS_가_node_에서_파싱된다(client, tmp_path):
    node = shutil.which('node')
    if not node:
        pytest.skip('node 없음')
    html = _orders_html(client)
    scripts = re.findall(r'<script>(.*?)</script>', html, re.S)
    assert scripts, '스크립트 블록이 없다'
    js = max(scripts, key=len)
    p = tmp_path / 'mo_orders.js'
    p.write_text(js, encoding='utf-8')
    r = subprocess.run([node, '--check', str(p)], capture_output=True, text=True)
    assert r.returncode == 0, f'JS 문법 오류: {r.stderr[:500]}'
