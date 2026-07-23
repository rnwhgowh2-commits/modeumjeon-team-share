# -*- coding: utf-8 -*-
"""M4-7 복수 등록 백그라운드 실행 — 202/409·폴링·「죽어도 진실을 잃지 않기」.

왜 백그라운드인가 (이 파일이 지키는 것):
  이 저장소의 Dockerfile 은 gunicorn 을 `--timeout 60`(sync worker)로 띄운다. 6마켓
  순차 등록을 한 HTTP 요청 안에서 돌리면 60초를 넘겨 **워커가 죽고 요청도 응답도
  증발**한다 — 그때 이미 마켓에 만들어진 상품은 회수(판매중지)가 못 돌아 그대로 남는다.
  과거이력의 「502 로 워커가 죽어 롤백이 안 돌아 유령 상품이 남은 사고」가 정확히 그
  조건이다. 그래서 POST 는 202 만 주고 결과는 폴링으로 읽는다.

이 파일이 고정하는 4가지:
  ① POST 는 202 + job_id 즉시. 이미 진행 중이면 409(중복 등록 = 유령 상품 방지).
  ② 폴링은 **그때까지 확정된 분량**을 준다(마켓 하나가 끝날 때마다 그 줄이 확정).
  ③ 스레드가 죽으면 실행 행은 `running=True` + 마지막으로 **시작한** 마켓으로 남고,
     폴링은 그 마켓을 성공도 실패도 아닌 **불확실**로 말한다.
  ④ **자동 재시도가 없다** — 스테일 행을 회수하는 것은 오직 새 POST(사장님이 마켓에서
     확인하고 다시 누르는 것)뿐이다. 서버가 알아서 다시 부르면 그게 중복 등록이다.

★ 실등록은 절대 하지 않는다 — LIVE_REGISTER_ARMED 는 꺼둔 채, 마켓 호출 계층은
  monkeypatch 로만 다룬다.
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

_MADE = []      # 이 파일이 만든 draft_id — 끝나면 실행 상태 행을 정확히 이것만 지운다.


@pytest.fixture(autouse=True)
def _cleanup_runs():
    """`draft_register_runs` 는 draft_id 가 PK(드래프트당 1행)다 — 남기면 다음 테스트가
    이전 테스트의 running=True 를 물려받아 엉뚱한 409 를 본다."""
    yield
    from shared.db import SessionLocal
    from lemouton.registration.models import ProductDraftRegisterRun
    s = SessionLocal()
    try:
        for did in _MADE:
            row = s.query(ProductDraftRegisterRun).filter_by(draft_id=did).first()
            if row is not None:
                s.delete(row)
        s.commit()
    except Exception:       # noqa: BLE001
        s.rollback()
    finally:
        s.close()
        _MADE.clear()


def _complete(client, **over):
    """4마켓 컴파일을 통과하는 완결 드래프트 1건 (test_register_many_route 와 같은 재료)."""
    body = {
        'name': '테스트 자켓(백그라운드)', 'brand': '테스트브랜드', 'sale_price': 39000,
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


def _spy_register(monkeypatch, gate=None, fail_for=()):
    """register_draft 를 기록기로 갈아끼운다. gate 를 주면 그 마켓에서 멈춰 세운다."""
    calls = []

    def fake(session, draft_id, market, *, category_code, vendor=None,
             account_key='default', **kw):
        calls.append(market)
        if gate and market == gate['market']:
            gate['entered'].set()
            gate['release'].wait(timeout=8)
        if market in fail_for:
            return {'ok': False, 'market_product_id': None, 'error': f'{market} 실패'}
        return {'ok': True, 'market_product_id': f'{market}-PID',
                'error': None, 'excluded': []}

    import webapp.routes.bulk.drafts as D
    monkeypatch.setattr(D, 'register_draft', fake)
    return calls


# ── ① 202 / 409 ────────────────────────────────────────────────────────────

def test_POST는_202와_job_id만_주고_결과는_안_싣는다(client, monkeypatch):
    """★ 응답에 결과가 실려 있으면 그건 동기 처리라는 뜻 — gunicorn 60초에 워커가 죽는다."""
    gate = {'market': 'smartstore', 'entered': threading.Event(),
            'release': threading.Event()}
    _spy_register(monkeypatch, gate=gate)
    did = _complete(client)
    try:
        r = client.post(f'/bulk/api/drafts/{did}/register',
                        json={'markets': ['smartstore', 'lotteon'],
                              'category_codes': ALL_CODES})
        # 아직 첫 마켓이 gate 에 걸려 있는데도 응답이 이미 돌아왔다 = 동기 대기가 아니다.
        assert r.status_code == 202, r.get_data(as_text=True)
        body = r.get_json()
        assert body['ok'] is True and body['started'] is True
        assert body['job_id']
        assert 'rows' not in body and 'summary' not in body, body
        assert gate['entered'].wait(timeout=8)
    finally:
        gate['release'].set()
        assert _wait_until(lambda: not _status(client, did)['running'])


def test_이미_진행중이면_두번째_POST는_409(client, monkeypatch):
    """중복 실행 = 같은 상품을 두 번 올림 = 유령 상품. 두 번째는 시작조차 안 한다."""
    gate = {'market': 'smartstore', 'entered': threading.Event(),
            'release': threading.Event()}
    calls = _spy_register(monkeypatch, gate=gate)
    did = _complete(client)
    try:
        r1 = client.post(f'/bulk/api/drafts/{did}/register',
                         json={'markets': ['smartstore'], 'category_codes': ALL_CODES})
        assert r1.status_code == 202
        assert gate['entered'].wait(timeout=8)

        r2 = client.post(f'/bulk/api/drafts/{did}/register',
                         json={'markets': ['smartstore'], 'category_codes': ALL_CODES})
        assert r2.status_code == 409, r2.get_data(as_text=True)
        assert r2.get_json()['ok'] is False
        assert '이미 등록이 진행 중' in r2.get_json()['error']
    finally:
        gate['release'].set()
        assert _wait_until(lambda: not _status(client, did)['running'])
    # 두 번째 요청이 마켓을 한 번도 더 부르지 않았다는 증명.
    assert calls == ['smartstore'], calls


# ── ② 폴링이 부분 결과를 준다 ──────────────────────────────────────────────

def test_폴링은_그때까지_끝난_마켓만_준다(client, monkeypatch):
    """마켓 하나가 끝날 때마다 그 줄이 확정된다 — 다 끝나야 보이는 게 아니다."""
    gate = {'market': 'lotteon', 'entered': threading.Event(),
            'release': threading.Event()}
    _spy_register(monkeypatch, gate=gate)
    did = _complete(client)
    try:
        r = client.post(f'/bulk/api/drafts/{did}/register',
                        json={'markets': ['smartstore', 'lotteon', 'eleven11'],
                              'category_codes': ALL_CODES})
        assert r.status_code == 202
        assert gate['entered'].wait(timeout=8)       # 두 번째 마켓에서 멈춰 있다
        assert _wait_until(lambda: _status(client, did)['done'] >= 1)

        mid = _status(client, did)
        assert mid['running'] is True
        assert mid['current_market'] == 'lotteon'          # 지금 처리 중인 마켓
        got = [x['market'] for x in mid['rows']]
        assert got == ['smartstore'], got                  # 끝난 것만 실린다
        assert mid['rows'][0]['status'] == 'ok'
        # 아직 부르지 않은 마켓은 pending — 「안 올라갔다」가 확실한 유일한 칸.
        assert mid['pending'] == ['lotteon', 'eleven11'], mid['pending']
        assert mid['total'] == 3
    finally:
        gate['release'].set()
    assert _wait_until(lambda: not _status(client, did)['running'])
    end = _status(client, did)
    assert [x['market'] for x in end['rows']] == ['smartstore', 'lotteon', 'eleven11']
    assert end['pending'] == []
    assert end['summary']['ok'] == 3


def test_시작한_적_없으면_없음이지_실패가_아니다(client):
    did = _complete(client)
    body = _status(client, did)
    assert body['ok'] is True
    assert body['running'] is False
    assert body['rows'] == []
    assert body['error'] is None
    assert body['uncertain'] is None


def test_status는_draft_id_쿼리스트링으로도_읽힌다(client):
    did = _complete(client)
    q = client.get(f'/bulk/api/drafts/register/status?draft_id={did}').get_json()
    assert q['ok'] is True and q['rows'] == []
    assert client.get('/bulk/api/drafts/register/status').status_code == 400


# ── ③ 죽어도 진실을 잃지 않는다 ────────────────────────────────────────────

def _seed_dead_run(did, *, market, done_rows=(), minutes_ago=30):
    """스레드가 마켓 처리 도중 죽은 상태를 그대로 재현한다.

    실제 사고 모양: 워커가 재시작·OOM 으로 죽으면 데몬 스레드는 자기 상태를 정리할
    새 없이 함께 죽는다 → 행은 `running=True` 인 채, `current_market` 은 마지막으로
    **시작한** 마켓으로, 진행률(progress_at)은 그 시점에서 멈춘 채 남는다.
    """
    import json
    from shared.db import SessionLocal
    from lemouton.registration.models import ProductDraftRegisterRun
    old = datetime.datetime.utcnow() - datetime.timedelta(minutes=minutes_ago)
    s = SessionLocal()
    try:
        row = s.query(ProductDraftRegisterRun).filter_by(draft_id=did).first()
        if row is None:
            row = ProductDraftRegisterRun(draft_id=did)
            s.add(row)
        row.job_id = 'deadjob'
        row.running = True
        row.started_at = old
        row.progress_at = old
        row.finished_at = None
        row.error = None
        row.current_market = market
        row.markets_json = json.dumps(['smartstore', market, 'eleven11'])
        row.done_count = len(done_rows)
        row.total_count = 3
        row.result_json = json.dumps(list(done_rows))
        s.commit()
    finally:
        s.close()


def test_스레드가_죽으면_running인_채_남고_폴링이_불확실을_말한다(client):
    """★ 이 파일에서 가장 중요한 고정.

    성공/실패를 단정하지 않는다 — 마켓 호출이 나간 뒤 죽었을 수도 있고, 그러면 상품은
    실제로 올라가 있다(유령 상품). 「실패」로 칠하면 그걸 영영 못 찾는다.
    """
    did = _complete(client)
    _seed_dead_run(did, market='lotteon', done_rows=[
        {'market': 'smartstore', 'status': 'ok', 'market_product_id': 'smartstore-PID',
         'error_code': None, 'error': None, 'reason': '', 'raw': None,
         'excluded': [], 'notes': []}])

    body = _status(client, did)
    assert body['running'] is True, '죽은 실행은 running 인 채 남아야 한다'
    assert body['stale'] is True
    assert body['current_market'] == 'lotteon'

    unc = body['uncertain']
    assert unc is not None and unc['market'] == 'lotteon'
    # 문구는 성공/실패를 단정하지 않고, 확인할 곳을 알려준다.
    assert '롯데온 처리 중 연결이 끊겼습니다' in unc['message'], unc
    assert '올라갔는지 모릅니다' in unc['message'], unc
    assert '마켓에서 상품이 생겼는지 직접 확인해 주세요' in unc['message'], unc
    for banned in ('실패했습니다', '성공했습니다', '등록되었습니다'):
        assert banned not in unc['message'], unc

    rows = {r['market']: r for r in body['rows']}
    assert rows['smartstore']['status'] == 'ok'          # 앞 마켓 결과는 그대로 남는다
    assert rows['lotteon']['status'] == 'unknown'
    assert rows['lotteon']['error_code'] == 'UNKNOWN'
    assert '마켓에서 상품 존재 확인 필요' in rows['lotteon']['notes']
    assert body['summary']['unknown'] == 1
    # 아직 손도 안 댄 마켓만 pending — 불확실 마켓은 pending 이 아니다(불렀을 수 있다).
    assert body['pending'] == ['eleven11'], body['pending']


def test_불확실_마켓에_조회API가_있으면_확인_수단을_알려준다(client):
    """유령 상품 스캔 힌트 — 이름으로 찾는 조회 API 가 있는 마켓만 True."""
    did = _complete(client)
    _seed_dead_run(did, market='lotteon')
    assert _status(client, did)['uncertain']['lookup_supported'] is True
    assert _status(client, did)['rows'][-1]['lookup_supported'] is True


def test_조회API가_없는_마켓은_확인_버튼을_주지_않는다(client):
    """쿠팡·ESM 은 상품번호가 있어야 조회된다 — 불확실하다는 건 그 번호가 없다는 뜻이라
    누를 수 없는 버튼이 된다. 스마트스토어는 products.py 자체가 없다."""
    did = _complete(client)
    _seed_dead_run(did, market='coupang')
    body = _status(client, did)
    assert body['uncertain']['market'] == 'coupang'
    assert body['uncertain']['lookup_supported'] is False
    # 라우트도 같은 판정을 한다(화면만 숨기고 서버는 열려 있으면 안 된다).
    r = client.get(f'/bulk/api/drafts/{did}/market-lookup?market=coupang')
    assert r.status_code == 400
    assert '조회 API 가 없어' in r.get_json()['error']


def test_불확실은_저장되지_않고_읽을_때_판정된다(client):
    """장부(ProductDraftMarket)에 없는 '불확실' 행을 실행 상태에 굳혀 두면, 나중에 사실이
    밝혀져도 그 거짓이 남는다 — result_json 은 확정된 것만 담는다."""
    import json
    did = _complete(client)
    _seed_dead_run(did, market='lotteon')
    saved = json.loads(_run_row(did).result_json or '[]')
    assert saved == [], saved
    assert _status(client, did)['uncertain'] is not None


def test_확인_버튼은_그_마켓_상품조회를_상품명으로_부른다(client, monkeypatch):
    """유령 상품 스캔 — 조회 API 를 상품명으로 부르고, **어디까지 봤는지**를 같이 말한다.

    (조회 전용이라 쓰기가 없다. 등록 실패를 되돌리거나 재시도하지 않는다.)

    [2026-07-23 I1] note 는 결과에 따라 달라진다 — 찾았으면 「찾았습니다」, 0건이면
    「확인한 범위 안에는 없습니다」다(0건을 「없다」로 단정하지 않는다). 0건 쪽 고정은
    tests/registration/test_register_guards.py 의 I1 절에 있다.
    """
    import webapp.routes.bulk.drafts as D
    import lemouton.uploader.market_fetch as MF
    import shared.platforms.eleven11.products as P11

    did = _complete(client, name='유령확인 자켓')
    monkeypatch.setattr(D, '_first_upload_env_prefix', lambda s, m: 'ELEVEN11')
    monkeypatch.setattr(MF, '_eleven11_client', lambda envp: object())
    seen = {}

    def fake_search(*, client=None, name=None, limit=None, **kw):
        seen['name'] = name
        return [{'prdNo': '777', 'prdNm': '유령확인 자켓'}]

    monkeypatch.setattr(P11, 'search_products', fake_search)

    body = client.get(f'/bulk/api/drafts/{did}/market-lookup?market=eleven11').get_json()
    assert body['ok'] is True
    assert seen['name'] == '유령확인 자켓'          # 드래프트 이름 그대로 검색
    assert body['count'] == 1
    assert body['rows'][0]['code'] == '777'
    assert '찾았습니다' in body['note'], body['note']
    assert body['scanned'] == 1 and '상품명' in body['scope'], body


def test_조회_실패는_없다가_아니라_원문_사유로_502(client, monkeypatch):
    """조회가 터진 것을 「상품 없음」으로 칠하면 유령 상품을 못 찾는다."""
    import webapp.routes.bulk.drafts as D
    import lemouton.uploader.market_fetch as MF
    import shared.platforms.eleven11.products as P11

    did = _complete(client)
    monkeypatch.setattr(D, '_first_upload_env_prefix', lambda s, m: 'ELEVEN11')
    monkeypatch.setattr(MF, '_eleven11_client', lambda envp: object())

    def boom(**kw):
        raise RuntimeError('11번가 HTTP 500: <error>서버 오류</error>')

    monkeypatch.setattr(P11, 'search_products', boom)
    r = client.get(f'/bulk/api/drafts/{did}/market-lookup?market=eleven11')
    assert r.status_code == 502
    assert r.get_json()['ok'] is False
    assert '서버 오류' in r.get_json()['error']     # 원문을 버리지 않는다


# ── ④ 자동 재시도 금지 ─────────────────────────────────────────────────────

def test_스테일이어도_스스로_다시_등록하지_않는다(client, monkeypatch):
    """죽은 실행을 서버가 알아서 재시도하면 그게 곧 중복 등록이다.

    폴링을 아무리 해도 마켓 호출은 0 이어야 한다 — 회수는 사장님의 새 POST 때만.
    """
    calls = _spy_register(monkeypatch)
    did = _complete(client)
    _seed_dead_run(did, market='lotteon')
    for _ in range(5):
        body = _status(client, did)
        assert body['running'] is True and body['stale'] is True
    assert calls == [], '폴링이 등록을 자동으로 다시 불렀다 — 중복 등록 위험'


def test_스테일_행은_새_POST가_회수해_다시_시작한다(client, monkeypatch):
    """사장님이 마켓에서 확인한 뒤 다시 누르는 흐름 — 이때만 409 가 아니라 새 실행.

    ★★ [2026-07-23 재리뷰 I-E] 단, **죽은 실행이 처리 중이던 마켓은 다시 부르지 않는다.**
      옛 스레드가 아직 그 마켓 호출 안에 있을 수 있어서(스테일 5분은 「죽었다」의 증명이
      아니라 의심이다), 그걸 새 스레드가 또 부르면 같은 마켓에 동시 등록이 된다.
      그 마켓은 「확인 필요」로 넘기고 **나머지 마켓만** 새로 돈다.
      (예전 이 테스트는 그 마켓을 다시 부르는 것을 정상으로 고정하고 있었다.)
    """
    calls = _spy_register(monkeypatch)
    did = _complete(client)
    _seed_dead_run(did, market='lotteon')

    r = client.post(f'/bulk/api/drafts/{did}/register',
                    json={'markets': ['lotteon', 'eleven11'], 'category_codes': ALL_CODES})
    assert r.status_code == 202, r.get_data(as_text=True)
    assert r.get_json()['job_id'] != 'deadjob', '회수 시 job_id 가 바뀌어야 한다'
    assert _wait_until(lambda: not _status(client, did)['running'])

    assert calls == ['eleven11'], f'처리 중이던 마켓을 또 불렀다 — {calls}'
    end = _status(client, did)
    assert end['uncertain'] is None                 # 새 실행이 정상 종료됐다
    rows = {x['market']: x for x in end['rows']}
    assert rows['lotteon']['status'] == 'unknown'   # 확인 필요로 넘겼다
    assert rows['eleven11']['status'] == 'ok'


def test_옛_좀비_스레드는_새_실행의_상태를_덮지_못한다(client):
    """스테일 회수 뒤 옛 스레드가 뒤늦게 깨어나 상태를 덮으면 진행 상황이 되감긴다
    (사장님은 그걸 보고 또 누른다 = 중복 등록). job_id 대조가 그 경로를 막는다."""
    import webapp.routes.bulk.drafts as D
    did = _complete(client)
    _seed_dead_run(did, market='lotteon')
    assert D._register_run_write(did, 'deadjob', done_count=99) is True   # 아직 같은 job

    from shared.db import SessionLocal
    from lemouton.registration.models import ProductDraftRegisterRun
    s = SessionLocal()
    try:
        row = s.query(ProductDraftRegisterRun).filter_by(draft_id=did).first()
        row.job_id = 'newjob'
        row.done_count = 0
        s.commit()
    finally:
        s.close()

    assert D._register_run_write(did, 'deadjob', done_count=99) is False
    assert (_run_row(did).done_count or 0) == 0, '옛 스레드가 새 실행 상태를 덮었다'


# ── 기존 증명 유지: ready 마켓에만 호출이 나간다 (백그라운드로 바뀌어도 동일) ──

def test_백그라운드로_바뀌어도_ready가_아닌_마켓엔_호출이_없다(client, monkeypatch):
    calls = _spy_register(monkeypatch)
    did = _complete(client)
    r = client.post(f'/bulk/api/drafts/{did}/register', json={
        'markets': ['smartstore', 'coupang', 'eleven11'],
        'category_codes': {'smartstore': ALL_CODES['smartstore'],
                           'coupang': ALL_CODES['coupang']},   # 11번가는 코드 없음
    })
    assert r.status_code == 202
    assert _wait_until(lambda: not _status(client, did)['running'])
    assert calls == ['smartstore'], calls
    rows = {x['market']: x for x in _status(client, did)['rows']}
    assert rows['coupang']['status'] == 'skipped'
    assert rows['eleven11']['status'] == 'skipped'
