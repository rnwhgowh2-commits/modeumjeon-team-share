# -*- coding: utf-8 -*-
"""[2026-07-23 코드리뷰 C1·C2·I2·I1] 등록 경로의 「같은 상품 두 번 올리기」 차단 4종.

이 파일이 고정하는 것 (전부 돈이 걸린 경로다):

  C1 이미 등록된 마켓은 **다시 부르지 않는다.**
     정상 워크플로가 그대로 사고였다 — 6마켓 중 3개 성공·3개 값부족 → 사장님이 빠진
     값을 채우고 「다시 점검」 → 6개가 전부 `ready` 로 나오고 화면이 **미리 체크**까지
     해 준다 → 한 번 누르면 이미 팔리고 있는 3개가 또 올라간다. 장부(ProductDraftMarket)
     에 `status='ok'` + 상품번호가 있으면 그게 「이미 올라가 있다」의 증거다.

  C2 회수된 좀비 스레드는 **다음 마켓을 부르지 않는다.**
     스테일 회수(새 POST)로 job_id 가 바뀌면 옛 스레드의 상태 쓰기는 거부된다. 그런데
     그 거부를 무시하고 계속 돌면 '쓰기만' 막히고 '마켓 호출'은 계속돼, 두 스레드가
     같은 드래프트를 같은 마켓에 동시에 올린다. 쓰기 거부 = 중단 신호다.

  I2 전송 중 끊긴 것을 **「실패」라고 단정하지 않는다.**
     요청이 소켓을 떠난 뒤 끊기면 마켓에는 상품이 만들어져 있을 수 있다(유령 상품).
     죽은 스레드 경로와 **같은 문구·같은 확인 수단**으로 「확인 필요」라고 말한다.

  I1 「마켓에서 확인」이 **있는 유령을 「없다」고 답하지 않는다.**
     롯데온 목록은 1페이지 100행인데 카탈로그는 13,883건이다 — 조회기간 없이 1페이지만
     보고 「0건」이라 답하면 그게 거짓 답이고, 그 답을 믿고 다시 누르면 곧 중복 등록이다.

★ 실등록은 절대 하지 않는다 — LIVE_REGISTER_ARMED 는 꺼둔 채, 마켓 호출 계층
  (register_draft·_send)은 전부 monkeypatch 로만 다룬다.
"""
import datetime
import threading
import time

import pytest


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('DISABLE_AUTH', '1')
    monkeypatch.delenv('LIVE_REGISTER_ARMED', raising=False)
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config['TESTING'] = True
    return flask_app.test_client()


ALL_CODES = {
    'smartstore': '50000167', 'coupang': '63955',
    'auction': '00120005002000000000/37500700',
    'gmarket': '00120005002100000000/300006243',
    'eleven11': '1011634', 'lotteon': 'LO2727500650',
}

_MADE = []      # 이 파일이 만든 draft_id — 실행상태·장부 행을 정확히 이것만 지운다.


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    from shared.db import SessionLocal
    from lemouton.registration.models import (
        ProductDraftRegisterRun, ProductDraftMarket)
    s = SessionLocal()
    try:
        for did in _MADE:
            for row in s.query(ProductDraftRegisterRun).filter_by(draft_id=did).all():
                s.delete(row)
            for row in s.query(ProductDraftMarket).filter_by(draft_id=did).all():
                s.delete(row)
        s.commit()
    except Exception:       # noqa: BLE001
        s.rollback()
    finally:
        s.close()
        _MADE.clear()


def _complete(client, **over):
    """6마켓 예비 컴파일을 통과하는 완결 드래프트 1건."""
    body = {
        'name': '테스트 자켓(중복차단)', 'brand': '테스트브랜드', 'sale_price': 39000,
        'stock_quantity': 7,
        'notice_type': 'WEAR',
        'notice': {
            'material': '면 100%', 'color': '블랙', 'size': 'M / L',
            'manufacturer': '테스트제조', 'caution': '단독세탁',
            'warranty_policy': '구매일로부터 1년',
            'after_service_director': '홍길동 010-1234-5678',
        },
        'images': ['https://example.com/main.jpg'],
        'detail_html': '<p>상세</p>',
        'delivery_fee': '3000', 'return_fee': '5000',
        'after_service_phone': '010-1234-5678',
        'after_service_guide': '평일 09-18시',
    }
    body.update(over)
    did = client.post('/bulk/api/drafts', json=body).get_json()['draft_id']
    _MADE.append(did)
    return did


def _seed_ledger(did, market, *, status='ok', pid='SS-1234', account_key='default'):
    """장부(ProductDraftMarket)에 등록 결과 1행을 심는다 = 「이미 올라가 있다」의 증거."""
    from shared.db import SessionLocal
    from lemouton.registration.models import ProductDraftMarket
    s = SessionLocal()
    try:
        row = (s.query(ProductDraftMarket)
               .filter_by(draft_id=did, market=market, account_key=account_key).first())
        if row is None:
            row = ProductDraftMarket(draft_id=did, market=market,
                                     account_key=account_key)
            s.add(row)
        row.status = status
        row.market_product_id = pid
        s.commit()
    finally:
        s.close()


def _status(client, did):
    return client.get(f'/bulk/api/drafts/{did}/register/status').get_json()


def _wait_until(cond, timeout=8.0, step=0.05):
    waited = 0.0
    while not cond() and waited < timeout:
        time.sleep(step)
        waited += step
    return cond()


def _run_row(did):
    from shared.db import SessionLocal
    from lemouton.registration.models import ProductDraftRegisterRun
    s = SessionLocal()
    try:
        return s.query(ProductDraftRegisterRun).filter_by(draft_id=did).first()
    finally:
        s.close()


def _spy_register(monkeypatch, gate=None, ledger=None):
    """register_draft 를 기록기로 갈아끼운다 → 어느 마켓에 호출이 나갔는지 증명용.

    ledger: {market: (status, error_code, error_message)} 를 주면 진짜 register_draft
        처럼 장부 행까지 남긴다(결과행의 error_code 는 장부에서 읽어 온다).
    """
    calls = []

    def fake(session, draft_id, market, *, category_code, vendor=None,
             account_key='default', **kw):
        calls.append(market)
        if gate and market == gate['market']:
            gate['entered'].set()
            gate['release'].wait(timeout=8)
        led = (ledger or {}).get(market)
        if led is not None:
            from lemouton.registration.models import ProductDraftMarket
            row = (session.query(ProductDraftMarket)
                   .filter_by(draft_id=draft_id, market=market,
                              account_key=account_key).first())
            if row is None:
                row = ProductDraftMarket(draft_id=draft_id, market=market,
                                         account_key=account_key)
                session.add(row)
            row.status, row.error_code, row.error_message = led
            session.commit()
            return {'ok': False, 'market_product_id': None, 'error': led[2]}
        return {'ok': True, 'market_product_id': f'{market}-PID',
                'error': None, 'excluded': []}

    import webapp.routes.bulk.drafts as D
    monkeypatch.setattr(D, 'register_draft', fake)
    return calls


# ══════════════════════════════════════════════════════════════════════════
#  C1 — 이미 등록된 마켓을 또 부르지 않는다
# ══════════════════════════════════════════════════════════════════════════

def test_이미_등록된_마켓은_점검이_registered로_잠근다(client):
    """★ 화면이 미리 체크해 주는 그 자리를 막는 고정.

    `ready` 로 돌려주면 화면은 체크박스를 켠 채 준다 — 한 번 누르면 이미 팔리는
    상품이 또 올라간다. 상태 자체가 달라야(=registered) 잠기고 체크가 꺼진다.
    """
    did = _complete(client)
    _seed_ledger(did, 'smartstore', pid='SS-777')

    body = client.post(f'/bulk/api/drafts/{did}/preflight',
                       json={'markets': ['smartstore', 'eleven11'],
                             'category_codes': ALL_CODES}).get_json()
    rows = {r['market']: r for r in body['rows']}
    assert rows['smartstore']['status'] == 'registered', rows['smartstore']
    assert rows['smartstore']['market_product_id'] == 'SS-777'
    assert '이미 등록' in rows['smartstore']['reason']
    assert 'SS-777' in rows['smartstore']['reason']       # 상품번호를 그대로 보여준다
    assert rows['eleven11']['status'] == 'ready'          # 나머지 마켓은 그대로


def test_이미_등록된_마켓에는_등록_호출이_0회다(client, monkeypatch):
    """★ 서버 가드 — 누가 markets 를 직접 POST 해도 버텨야 한다(화면은 그 다음)."""
    calls = _spy_register(monkeypatch)
    did = _complete(client)
    _seed_ledger(did, 'smartstore', pid='SS-777')

    r = client.post(f'/bulk/api/drafts/{did}/register',
                    json={'markets': ['smartstore', 'eleven11'],
                          'category_codes': ALL_CODES})
    assert r.status_code == 202
    assert _wait_until(lambda: not _status(client, did)['running'])

    assert calls == ['eleven11'], calls        # 스스는 부르지 않았다
    rows = {x['market']: x for x in _status(client, did)['rows']}
    assert rows['smartstore']['status'] == 'already'
    assert rows['smartstore']['market_product_id'] == 'SS-777'
    assert rows['smartstore']['error_code'] == 'ALREADY_REGISTERED'
    assert rows['eleven11']['status'] == 'ok'
    assert _status(client, did)['summary']['already'] == 1


def test_다시_올리기를_켜야만_다시_부른다(client, monkeypatch):
    """다시 올려야 하는 경우의 **명시적 opt-in** — 기본은 꺼져 있다."""
    calls = _spy_register(monkeypatch)
    did = _complete(client)
    _seed_ledger(did, 'smartstore', pid='SS-777')

    # 점검부터 ready 로 풀린다(화면이 체크할 수 있게).
    pre = client.post(f'/bulk/api/drafts/{did}/preflight',
                      json={'markets': ['smartstore'], 'category_codes': ALL_CODES,
                            'reregister': ['smartstore']}).get_json()
    assert pre['rows'][0]['status'] == 'ready', pre['rows'][0]

    r = client.post(f'/bulk/api/drafts/{did}/register',
                    json={'markets': ['smartstore'], 'category_codes': ALL_CODES,
                          'reregister': ['smartstore']})
    assert r.status_code == 202
    assert _wait_until(lambda: not _status(client, did)['running'])
    assert calls == ['smartstore'], calls


def test_다시_올리기는_켠_마켓에만_적용된다(client, monkeypatch):
    """opt-in 은 마켓 단위다 — 하나 켰다고 나머지까지 풀리면 그게 사고다."""
    calls = _spy_register(monkeypatch)
    did = _complete(client)
    _seed_ledger(did, 'smartstore', pid='SS-777')
    _seed_ledger(did, 'eleven11', pid='11-888')

    r = client.post(f'/bulk/api/drafts/{did}/register',
                    json={'markets': ['smartstore', 'eleven11'],
                          'category_codes': ALL_CODES,
                          'reregister': ['eleven11']})
    assert r.status_code == 202
    assert _wait_until(lambda: not _status(client, did)['running'])
    assert calls == ['eleven11'], calls
    rows = {x['market']: x for x in _status(client, did)['rows']}
    assert rows['smartstore']['status'] == 'already'


def test_실패한_장부행은_잠그지_않는다(client, monkeypatch):
    """실패 뒤 재시도는 막지 않는다 — 막는 근거는 「성공 + 상품번호」뿐이다."""
    calls = _spy_register(monkeypatch)
    did = _complete(client)
    _seed_ledger(did, 'smartstore', status='failed', pid=None)

    r = client.post(f'/bulk/api/drafts/{did}/register',
                    json={'markets': ['smartstore'], 'category_codes': ALL_CODES})
    assert r.status_code == 202
    assert _wait_until(lambda: not _status(client, did)['running'])
    assert calls == ['smartstore'], calls


def test_계정이_다르면_다른_상품이다(client, monkeypatch):
    """장부 키는 (드래프트, 마켓, 계정) 이다 — A계정 등록이 B계정 등록을 막으면 안 된다."""
    calls = _spy_register(monkeypatch)
    did = _complete(client)
    _seed_ledger(did, 'lotteon', pid='LO-111', account_key='default')

    r = client.post(f'/bulk/api/drafts/{did}/register',
                    json={'markets': ['lotteon'], 'category_codes': ALL_CODES,
                          'account_keys': {'lotteon': 'acctB'}})
    assert r.status_code == 202
    assert _wait_until(lambda: not _status(client, did)['running'])
    assert calls == ['lotteon'], calls


def test_단수_라우트도_이미_등록된_마켓을_다시_부르지_않는다(client, monkeypatch):
    """가드는 판정기(_register_one)에 있다 — 단수·복수 라우트가 같은 답을 낸다."""
    calls = _spy_register(monkeypatch)
    did = _complete(client)
    _seed_ledger(did, 'smartstore', pid='SS-777')

    body = client.post(f'/bulk/api/drafts/{did}/register/smartstore',
                       json={'category_code': ALL_CODES['smartstore']}).get_json()
    assert calls == [], calls
    assert body['ok'] is False
    assert body['already'] is True
    assert body['market_product_id'] == 'SS-777'

    # opt-in 하면 그때만 부른다.
    client.post(f'/bulk/api/drafts/{did}/register/smartstore',
                json={'category_code': ALL_CODES['smartstore'], 'reregister': True})
    assert calls == ['smartstore'], calls


# ══════════════════════════════════════════════════════════════════════════
#  C2 — 회수된 좀비 스레드는 다음 마켓을 부르지 않는다
# ══════════════════════════════════════════════════════════════════════════

def _steal_run(did, new_job='newjob'):
    """스테일 회수를 흉내낸다 — 새 POST 가 이 드래프트의 실행을 가져간 상태."""
    from shared.db import SessionLocal
    from lemouton.registration.models import ProductDraftRegisterRun
    s = SessionLocal()
    try:
        row = s.query(ProductDraftRegisterRun).filter_by(draft_id=did).first()
        row.job_id = new_job
        row.done_count = 0
        row.result_json = None
        s.commit()
    finally:
        s.close()


def test_회수된_옛_스레드는_다음_마켓을_부르지_않는다(client, monkeypatch):
    """★ C2 의 핵심 — 쓰기만 막고 호출은 계속하면 두 스레드가 같은 마켓에 동시 등록한다.

    상태 쓰기 거부(job_id 불일치)는 「너는 더 이상 이 실행의 주인이 아니다」는 뜻이다.
    다음 마켓을 부르기 전에 멈춰야 한다.
    """
    gate = {'market': 'smartstore', 'entered': threading.Event(),
            'release': threading.Event()}
    calls = _spy_register(monkeypatch, gate=gate)
    did = _complete(client)

    r = client.post(f'/bulk/api/drafts/{did}/register',
                    json={'markets': ['smartstore', 'eleven11', 'lotteon'],
                          'category_codes': ALL_CODES})
    assert r.status_code == 202
    assert gate['entered'].wait(timeout=8)

    _steal_run(did)                 # 그 사이 새 POST 가 실행을 회수했다
    gate['release'].set()

    # 옛 스레드가 살아 있었다면 수십 ms 안에 두 번째 마켓을 부른다.
    grew = _wait_until(lambda: len(calls) >= 2, timeout=1.5)
    assert grew is False, f'회수된 옛 스레드가 마켓을 더 불렀다 — {calls}'
    assert calls == ['smartstore'], calls

    # 새 실행의 상태를 덮어쓰지도 않았다.
    row = _run_row(did)
    assert row.job_id == 'newjob'
    assert (row.done_count or 0) == 0
    assert row.result_json is None
    assert row.finished_at is None, '남의 실행을 끝났다고 표시했다'


# ══════════════════════════════════════════════════════════════════════════
#  I2 — 전송이 끊긴 것을 「실패」라고 단정하지 않는다
# ══════════════════════════════════════════════════════════════════════════

def test_service는_전송예외를_CALL로_남긴다(client, monkeypatch):
    """이 아래 매핑이 기대는 계약 — 전송 중 예외는 장부에 error_code='CALL' 로 남는다."""
    from shared.db import SessionLocal
    from lemouton.registration.service import register_draft
    from lemouton.registration.models import ProductDraftMarket

    did = _complete(client)

    def boom(market, spec):
        raise RuntimeError('ReadTimeout — 응답을 받지 못했습니다')

    s = SessionLocal()
    try:
        r = register_draft(s, did, 'eleven11',
                           category_code=ALL_CODES['eleven11'], _send=boom)
        assert r['ok'] is False
        row = (s.query(ProductDraftMarket)
               .filter_by(draft_id=did, market='eleven11',
                          account_key='default').first())
        assert row.error_code == 'CALL', row.error_code
    finally:
        s.close()


def test_전송이_끊긴_결과는_실패가_아니라_확인필요다(client, monkeypatch):
    """★ 요청이 소켓을 떠난 뒤 끊기면 상품은 올라가 있을 수 있다(유령 상품).

    죽은 스레드 경로와 **같은 문구**로 말하고, 확인 수단(lookup)까지 같이 준다.
    """
    calls = _spy_register(monkeypatch, ledger={
        'lotteon': ('failed', 'CALL', 'ReadTimeout — 응답을 받지 못했습니다')})
    did = _complete(client)

    r = client.post(f'/bulk/api/drafts/{did}/register',
                    json={'markets': ['lotteon'], 'category_codes': ALL_CODES})
    assert r.status_code == 202
    assert _wait_until(lambda: not _status(client, did)['running'])
    assert calls == ['lotteon']

    body = _status(client, did)
    row = body['rows'][0]
    assert row['status'] == 'unknown', row
    assert row['error_code'] == 'CALL'
    assert row['lookup_supported'] is True            # 롯데온은 이름으로 찾을 수 있다
    assert '올라갔는지 모릅니다' in (row['error'] or ''), row
    assert 'ReadTimeout' in (row['error'] or ''), '전송 오류 원문을 버렸다'
    for banned in ('실패했습니다', '성공했습니다', '등록되었습니다'):
        assert banned not in (row['error'] or ''), row
    assert '마켓에서 상품 존재 확인 필요' in row['notes']
    assert body['summary']['unknown'] == 1
    assert body['summary']['failed'] == 0, '거짓 실패가 요약에 잡혔다'


def test_전송끊김이_아닌_실패는_그대로_실패다(client, monkeypatch):
    """마켓이 4xx 로 거절한 것은 **부르고 거절당한** 사실이다 — 불확실이 아니다."""
    calls = _spy_register(monkeypatch, ledger={
        'eleven11': ('failed', 'NO_PRODUCT_ID', '마켓이 상품ID 를 주지 않았습니다')})
    did = _complete(client)

    r = client.post(f'/bulk/api/drafts/{did}/register',
                    json={'markets': ['eleven11'], 'category_codes': ALL_CODES})
    assert r.status_code == 202
    assert _wait_until(lambda: not _status(client, did)['running'])
    assert calls == ['eleven11']
    row = _status(client, did)['rows'][0]
    assert row['status'] == 'failed', row
    assert row['error_code'] == 'NO_PRODUCT_ID'


# ══════════════════════════════════════════════════════════════════════════
#  I1 — 「마켓에서 확인」이 있는 유령을 「없다」고 답하지 않는다
#
#  롯데온 상품 목록 조회는 **1페이지 100행**이 상한이고, 이 계정 카탈로그는
#  dataCount 13,883 이다(지도 실측). 조회기간 없이 1페이지만 훑고 「0건」이라 답하면
#  실제로 올라간 유령을 「없다」고 말하는 것이다 — 사장님이 그걸 믿고 다시 누르면
#  그게 곧 중복 등록(C1 이 막으려는 바로 그 사고)이다.
#
#  지도 근거(marketplace_api_map.json · lotteon.product.list):
#    POST /v1/openapi/product/v1/product/list
#    필수 regStrtDttm·regEndDttm(YYYYMMDDHHMMSS 14자리) · pageNo(1부터) · rowsPerPage(MAX 100)
#
#  ★ 라이브 롯데온을 부르지 않는다 — list_products 를 monkeypatch 로 고정한다.
# ══════════════════════════════════════════════════════════════════════════

def _fake_lotteon(monkeypatch, pages):
    """롯데온 상품목록을 페이지별로 되돌려주는 가짜 — 호출 인자를 그대로 기록한다."""
    import lemouton.uploader.market_fetch as MF
    import shared.platforms.lotteon.products as LP
    import webapp.routes.bulk.drafts as D

    seen = []
    monkeypatch.setattr(D, '_first_upload_env_prefix', lambda s, m: 'LOTTEON_MAIN')
    monkeypatch.setattr(MF, '_lotteon_client', lambda envp: object())

    def fake_list(*, client=None, page_no=1, rows_per_page=100,
                  reg_start=None, reg_end=None, **kw):
        seen.append({'page_no': page_no, 'rows_per_page': rows_per_page,
                     'reg_start': reg_start, 'reg_end': reg_end})
        if callable(pages):
            return pages(page_no)
        return pages[page_no - 1] if page_no <= len(pages) else []

    monkeypatch.setattr(LP, 'list_products', fake_list)
    return seen


def _filler(n, page):
    return [{'spdNo': f'LO{page}{i:03d}', 'spdNm': f'다른 상품 {page}-{i}'} for i in range(n)]


def test_롯데온_유령확인은_뒤_페이지에_있어도_찾는다(client, monkeypatch):
    """★ 1페이지(100행)만 보고 「0건」이라 답하던 거짓말을 막는 고정.

    카탈로그가 13,883건인데 100행만 훑으면, 방금 올라간 유령은 거의 언제나 못 본다.
    """
    seen = _fake_lotteon(monkeypatch, [
        _filler(100, 1),
        _filler(99, 2) + [{'spdNo': 'LO2729045338', 'spdNm': '유령확인 자켓 블랙'}],
        [],
    ])
    did = _complete(client, name='유령확인 자켓')

    body = client.get(f'/bulk/api/drafts/{did}/market-lookup?market=lotteon').get_json()
    assert body['ok'] is True
    assert [c['page_no'] for c in seen][:2] == [1, 2], seen   # 페이지를 넘겼다
    assert body['count'] == 1, body
    assert body['rows'][0]['code'] == 'LO2729045338'
    assert body['complete'] is True                            # 찾았으면 답이 확정이다


def test_롯데온_조회는_등록직후_구간을_14자리로_준다(client, monkeypatch):
    """지도 실측: regStrtDttm/regEndDttm 은 **14자리**(8자리면 INVALID_INPUT).
    등록은 방금 일어난 일이라 최근 구간만 본다 — 1년치를 훑으면 상한에 먼저 걸린다."""
    seen = _fake_lotteon(monkeypatch, [[]])
    did = _complete(client, name='유령확인 자켓')
    client.get(f'/bulk/api/drafts/{did}/market-lookup?market=lotteon')

    call = seen[0]
    assert len(call['reg_start']) == 14 and call['reg_start'].isdigit(), call
    assert len(call['reg_end']) == 14 and call['reg_end'].isdigit(), call
    start = datetime.datetime.strptime(call['reg_start'], '%Y%m%d%H%M%S')
    assert datetime.datetime.now() - start <= datetime.timedelta(days=2), call
    assert call['rows_per_page'] == 100                        # 롯데온 상한


def test_상한에_걸리면_없다가_아니라_못_다_봤다로_답한다(client, monkeypatch):
    """무한 루프를 막는 상한은 필요하다 — 다만 상한에 걸린 사실을 숨기면 그게 거짓말이다."""
    import webapp.routes.bulk.drafts as D
    seen = _fake_lotteon(monkeypatch, lambda page: _filler(100, page))
    did = _complete(client, name='유령확인 자켓')

    body = client.get(f'/bulk/api/drafts/{did}/market-lookup?market=lotteon').get_json()
    assert body['ok'] is True
    assert body['count'] == 0
    assert len(seen) == D.LOOKUP_MAX_PAGES, seen               # 상한에서 멈춘다
    assert body['complete'] is False, '못 다 본 것을 다 봤다고 답했다'
    assert body['scanned'] == D.LOOKUP_MAX_PAGES * 100
    assert '확인한 범위' in body['note'], body['note']
    for banned in ('올라가지 않았습니다', '등록되지 않았습니다'):
        assert banned not in body['note'], body['note']


def test_끝까지_봤어도_확인한_범위_안에는_없다고만_말한다(client, monkeypatch):
    """0건은 「안 올라갔다」의 증명이 아니다 — 마켓 색인이 늦을 수 있다."""
    _fake_lotteon(monkeypatch, [_filler(7, 1)])
    did = _complete(client, name='유령확인 자켓')

    body = client.get(f'/bulk/api/drafts/{did}/market-lookup?market=lotteon').get_json()
    assert body['count'] == 0
    assert body['complete'] is True
    assert body['scanned'] == 7
    assert '확인한 범위' in body['note'], body['note']
    assert '판매자센터' in body['note'], body['note']           # 사람이 확인할 곳을 알려준다


def test_훑은_범위를_응답에_싣는다(client, monkeypatch):
    """「0건」이 「없다」인지 「거기까진 못 봤다」인지 구분할 근거를 화면에 준다."""
    _fake_lotteon(monkeypatch, [_filler(100, 1), _filler(5, 2)])
    did = _complete(client, name='유령확인 자켓')

    body = client.get(f'/bulk/api/drafts/{did}/market-lookup?market=lotteon').get_json()
    assert body['scanned'] == 105
    assert body['pages'] == 2
    assert '105' in body['scope'] and '2' in body['scope'], body['scope']


def test_11번가는_이름검색이라_훑은_범위가_검색결과다(client, monkeypatch):
    """마켓마다 확인 수단이 다르다 — 무엇으로 확인했는지를 그대로 말한다."""
    import lemouton.uploader.market_fetch as MF
    import shared.platforms.eleven11.products as P11
    import webapp.routes.bulk.drafts as D

    did = _complete(client, name='유령확인 자켓')
    monkeypatch.setattr(D, '_first_upload_env_prefix', lambda s, m: 'ELEVEN11')
    monkeypatch.setattr(MF, '_eleven11_client', lambda envp: object())
    monkeypatch.setattr(P11, 'search_products',
                        lambda **kw: [{'prdNo': '777', 'prdNm': '유령확인 자켓'}])

    body = client.get(f'/bulk/api/drafts/{did}/market-lookup?market=eleven11').get_json()
    assert body['ok'] is True and body['count'] == 1
    assert body['scanned'] == 1
    assert '상품명' in body['scope'], body['scope']
