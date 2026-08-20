# -*- coding: utf-8 -*-
"""[2026-07-23 코드리뷰 I4] 등록 실행상태 잠금 — 엔진에 기대지 않는 원자적 클레임.

`draft_register_runs` 1행이 「이 드래프트는 지금 등록 중」의 유일한 표식이다. 그 행을
누가 차지하느냐가 갈리면 같은 상품에 등록 스레드가 두 개 뜬다(= 같은 상품 2개).

예전 구현의 두 가지 구멍:
  ① 클레임이 `with_for_update()` 에 기댔다 — SQLite 는 그 구문을 **조용히 무시**한다.
     이 저장소는 SQLite 폴백 이력이 실제로 있어서, 폴백으로 떨어지면 가드가 사라진다.
  ② 상태 쓰기가 읽고-비교하고-쓰기(TOCTOU)였다 — WHERE 에 job_id 가 없어, 그 사이에
     회수된 행을 좀비 스레드가 덮어쓸 창이 남았다.

둘 다 **단일 조건부 UPDATE + rowcount** 로 바꾼 것을 이 파일이 고정한다
(Postgres·SQLite 양쪽에서 한 문장 안에 조건 검사와 쓰기가 끝난다).

★ 실등록은 절대 하지 않는다 — 마켓 호출 계층을 아예 건드리지 않는 테스트다.
"""
import datetime
import json
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


_MADE = []      # 이 파일이 만든 draft_id — 실행상태·장부 행을 정확히 이것만 지운다.


@pytest.fixture(autouse=True)
def _cleanup():
    """`draft_register_runs` 는 draft_id 가 PK(드래프트당 1행)다 — 남기면 다음 테스트가
    이전 테스트의 running=True 를 물려받아 엉뚱한 409 를 본다."""
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
    """6마켓 예비 컴파일을 통과하는 완결 드래프트 — 사전점검이 ready 여야 마켓 호출까지 간다."""
    body = {
        'name': '테스트 자켓(잠금)', 'brand': '테스트브랜드', 'sale_price': 39000,
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


def _run_row(did):
    from shared.db import SessionLocal
    from lemouton.registration.models import ProductDraftRegisterRun
    s = SessionLocal()
    try:
        return s.query(ProductDraftRegisterRun).filter_by(draft_id=did).first()
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


def _steal_run(did, new_job='otherjob'):
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



def test_클레임은_행잠금에_기대지_않는다():
    """`with_for_update()` 는 SQLite 가 조용히 무시한다 — 이 저장소는 SQLite 폴백 이력이
    실제로 있다. 잠금을 엔진에 맡기면 폴백에서 가드가 통째로 사라진다."""
    import ast
    import inspect
    import textwrap
    import webapp.routes.bulk.drafts as D

    def _code_only(fn):
        """설명(docstring)·주석을 뺀 **실행되는 코드**만 — 설명에는 「예전엔 이걸 썼다」가
        남아 있어도 되지만, 코드에 남아 있으면 안 된다."""
        node = ast.parse(textwrap.dedent(inspect.getsource(fn))).body[0]
        if ast.get_docstring(node) is not None:
            node.body = node.body[1:]
        return ast.unparse(node)

    for fn in (D._claim_register_run, D._register_run_write):
        assert 'with_for_update' not in _code_only(fn), \
            f'{fn.__name__} 가 아직 행 잠금에 기댄다'


def test_동시_클레임은_정확히_하나만_성공한다(client):
    """★ 두 요청이 동시에 스테일 행을 회수하면 **한쪽만** 이겨야 한다.

    둘 다 이기면 같은 드래프트에 등록 스레드가 두 개 뜬다 = 같은 상품 두 번 등록.
    """
    import webapp.routes.bulk.drafts as D
    from shared.db import SessionLocal
    from lemouton.registration.models import ProductDraftRegisterRun

    did = _complete(client)
    old = datetime.datetime.utcnow() - datetime.timedelta(hours=1)
    s = SessionLocal()
    try:
        row = ProductDraftRegisterRun(draft_id=did, job_id='deadjob', running=True,
                                      started_at=old, progress_at=old,
                                      markets_json=json.dumps(['lotteon']),
                                      total_count=1)
        s.add(row)
        s.commit()
    finally:
        s.close()

    got = []
    start = threading.Barrier(4)

    def claim():
        start.wait(timeout=5)
        for _ in range(6):          # SQLite 쓰기 잠금은 재시도로 흡수한다
            sess = SessionLocal()
            try:
                got.append(D._claim_register_run(sess, did, ['lotteon']))
                return
            except Exception:       # noqa: BLE001 — 잠금 충돌은 실패가 아니라 재시도
                sess.rollback()
                time.sleep(0.05)
            finally:
                sess.close()
        got.append(None)

    threads = [threading.Thread(target=claim) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    winners = [j for j in got if j]
    assert len(winners) == 1, f'동시 클레임이 {len(winners)}개 성공했다 — 중복 등록 위험'
    assert _run_row(did).job_id == winners[0]


def test_진행중인_실행은_클레임되지_않는다(client):
    """진짜로 도는 실행을 회수하면 두 스레드가 같은 마켓을 동시에 부른다."""
    import webapp.routes.bulk.drafts as D
    from shared.db import SessionLocal
    from lemouton.registration.models import ProductDraftRegisterRun

    did = _complete(client)
    now = datetime.datetime.utcnow()
    s = SessionLocal()
    try:
        s.add(ProductDraftRegisterRun(draft_id=did, job_id='livejob', running=True,
                                      started_at=now, progress_at=now,
                                      markets_json=json.dumps(['lotteon']),
                                      total_count=1))
        s.commit()
    finally:
        s.close()

    s2 = SessionLocal()
    try:
        assert D._claim_register_run(s2, did, ['lotteon']) is None
    finally:
        s2.close()
    assert _run_row(did).job_id == 'livejob'


def test_상태쓰기는_job_id를_WHERE에_넣는다(client):
    """읽고-비교하고-쓰기(TOCTOU)면 그 사이에 회수된 행을 좀비가 덮어쓴다.

    조건부 UPDATE 라야 「내 것일 때만 쓴다」가 원자적으로 지켜진다.
    """
    import webapp.routes.bulk.drafts as D
    from shared.db import SessionLocal
    from lemouton.registration.models import ProductDraftRegisterRun

    did = _complete(client)
    s = SessionLocal()
    try:
        s.add(ProductDraftRegisterRun(draft_id=did, job_id='myjob', running=True,
                                      started_at=datetime.datetime.utcnow(),
                                      progress_at=datetime.datetime.utcnow(),
                                      done_count=0, total_count=1))
        s.commit()
    finally:
        s.close()

    assert D._register_run_write(did, 'myjob', done_count=7) is True
    assert _run_row(did).done_count == 7
    # 회수된 뒤 — 옛 job 은 **행을 건드리지 못한다**(False = 중단 신호).
    _steal_run(did, new_job='otherjob')
    assert D._register_run_write(did, 'myjob', done_count=99) is False
    assert (_run_row(did).done_count or 0) == 0
    # 아예 없는 드래프트도 False (예외 아님).
    assert D._register_run_write(9999999, 'myjob', done_count=1) is False


# ══════════════════════════════════════════════════════════════════════════
#  I-C [재리뷰] 단수 등록 라우트도 같은 잠금에 참여한다
#
#  단수 라우트가 _claim_register_run 을 안 부르면, 복수 잡이 도는 중에 같은 드래프트·
#  마켓으로 단수 POST 가 들어와 **409 없이 동시에** 마켓을 부른다(라이브는 DISABLE_AUTH=1).
# ══════════════════════════════════════════════════════════════════════════

def test_복수_잡이_도는_중_단수_POST는_409(client, monkeypatch):
    import webapp.routes.bulk.drafts as D
    from shared.db import SessionLocal
    from lemouton.registration.models import ProductDraftRegisterRun

    did = _complete(client)
    calls = []
    monkeypatch.setattr(D, 'register_draft',
                        lambda *a, **k: calls.append(k.get('market')) or {})

    now = datetime.datetime.utcnow()
    s = SessionLocal()
    try:
        s.add(ProductDraftRegisterRun(draft_id=did, job_id='livejob', running=True,
                                      started_at=now, progress_at=now,
                                      markets_json=json.dumps(['lotteon']),
                                      total_count=1))
        s.commit()
    finally:
        s.close()

    r = client.post(f'/bulk/api/drafts/{did}/register/lotteon',
                    json={'category_code': 'LO2727500650'})
    assert r.status_code == 409, r.get_data(as_text=True)
    assert calls == [], f'진행 중인데 단수 등록이 마켓을 불렀다 — {calls}'
    assert _run_row(did).job_id == 'livejob', '단수 라우트가 남의 실행을 가로챘다'


def test_단수_등록은_끝나면_잠금을_돌려준다(client, monkeypatch):
    """안 풀면 그 드래프트는 스테일 5분이 지나기 전엔 아무것도 못 올린다."""
    import webapp.routes.bulk.drafts as D
    from shared.db import SessionLocal
    from lemouton.registration.models import ProductDraftMarket
    did = _complete(client)

    def fake(session, draft_id, market, *, account_key='default', **k):
        # 진짜 register_draft 처럼 장부에 성공을 남긴다(두 번째 호출이 already 로 막히는 근거).
        row = ProductDraftMarket(draft_id=draft_id, market=market,
                                 account_key=account_key, status='ok',
                                 market_product_id='LO-1')
        session.add(row)
        session.commit()
        return {'ok': True, 'market_product_id': 'LO-1', 'error': None, 'excluded': []}

    monkeypatch.setattr(D, 'register_draft', fake)

    r1 = client.post(f'/bulk/api/drafts/{did}/register/lotteon',
                     json={'category_code': 'LO2727500650'})
    assert r1.status_code == 200, r1.get_data(as_text=True)
    row = _run_row(did)
    assert row.running is False and row.finished_at is not None

    # 연달아 또 부를 수 있다(잠금이 풀렸다는 증명). 이미 등록됐으니 already 로 막힌다.
    r2 = client.post(f'/bulk/api/drafts/{did}/register/lotteon',
                     json={'category_code': 'LO2727500650'})
    assert r2.status_code == 200, r2.get_data(as_text=True)
    assert r2.get_json().get('already') is True


# ══════════════════════════════════════════════════════════════════════════
#  I-D [재리뷰] 기록 실패(None)로 계속 갈 때 유령 단서가 사라진다
#
#  「부르기 전에 current_market 을 기록한다」가 이 설계의 전제다. 그 쓰기가 실패했는데
#  그대로 마켓을 부르면, 거기서 죽었을 때 payload 의 current_market 은 **이전 마켓**을
#  가리키고 진짜 유령이 생긴 마켓은 pending(=「부른 적 없다」가 확실한 칸)으로 보고된다.
#  계속 진행하는 선택 자체는 옳다(멀쩡한 등록을 죽이는 게 더 비싸다) — 다만 재시도하고,
#  연속으로 계속 실패하면 멈춘다.
# ══════════════════════════════════════════════════════════════════════════

def test_current_market_기록_실패는_한_번_더_시도한다(client, monkeypatch):
    import webapp.routes.bulk.drafts as D

    did = _complete(client)
    tries = []
    real = D._register_run_write

    def flaky(draft_id, job_id, **fields):
        if 'current_market' in fields:
            tries.append(fields['current_market'])
            if len(tries) == 1:
                return None                     # 첫 시도는 기록 실패(모름)
        return real(draft_id, job_id, **fields)

    monkeypatch.setattr(D, '_register_run_write', flaky)
    monkeypatch.setattr(D, 'register_draft',
                        lambda *a, **k: {'ok': True, 'market_product_id': 'X',
                                         'error': None, 'excluded': []})
    r = client.post(f'/bulk/api/drafts/{did}/register',
                    json={'markets': ['lotteon'], 'category_codes': {'lotteon': 'LO1'}})
    assert r.status_code == 202
    assert _wait_until(lambda: not _status(client, did)['running'])
    # 마지막 None 은 실행이 끝나며 current_market 을 지우는 쓰기다(마켓 이름만 센다).
    assert [t for t in tries if t] == ['lotteon', 'lotteon'], f'재시도가 없었다 — {tries}'
    assert _status(client, did)['current_market'] is None


def test_기록이_계속_실패하면_멈춘다(client, monkeypatch):
    """단서를 못 남기는 채로 계속 마켓을 부르면 유령을 찾을 방법이 사라진다."""
    import webapp.routes.bulk.drafts as D

    did = _complete(client)
    called = []
    monkeypatch.setattr(D, '_register_run_write', lambda *a, **k: None)   # 늘 기록 실패
    monkeypatch.setattr(D, 'register_draft',
                        lambda *a, **k: called.append(1) or
                        {'ok': True, 'market_product_id': 'X', 'error': None,
                         'excluded': []})

    r = client.post(f'/bulk/api/drafts/{did}/register',
                    json={'markets': ['lotteon', 'eleven11', 'auction', 'gmarket'],
                          'category_codes': {'lotteon': 'LO1', 'eleven11': '1',
                                             'auction': '1/1', 'gmarket': '1/1'}})
    assert r.status_code == 202
    time.sleep(1.0)
    assert len(called) <= D.REGISTER_WRITE_BLIND_LIMIT, (
        f'기록이 계속 실패하는데 {len(called)}개 마켓을 불렀다 — 유령 단서가 없다')


# ══════════════════════════════════════════════════════════════════════════
#  I-E [재리뷰] 스테일 회수 직후 「처리 중이던 마켓」을 새 실행이 그대로 다시 부른다
#
#  C2 는 옛 스레드의 **다음** 마켓만 막는다. 옛 스레드가 아직 그 마켓 호출 안에 있으면
#  장부에 ok 가 없어 C1 도 못 막고, 새 스레드가 **같은 마켓을 동시에** 부른다.
# ══════════════════════════════════════════════════════════════════════════

def _seed_dead_run(did, *, market, markets, minutes_ago=30):
    from shared.db import SessionLocal
    from lemouton.registration.models import ProductDraftRegisterRun
    old = datetime.datetime.utcnow() - datetime.timedelta(minutes=minutes_ago)
    s = SessionLocal()
    try:
        s.add(ProductDraftRegisterRun(
            draft_id=did, job_id='deadjob', running=True, started_at=old,
            progress_at=old, current_market=market,
            markets_json=json.dumps(markets), total_count=len(markets),
            done_count=0))
        s.commit()
    finally:
        s.close()


def test_회수한_실행이_처리중이던_마켓은_새_실행이_안_부른다(client, monkeypatch):
    import webapp.routes.bulk.drafts as D

    did = _complete(client)
    _seed_dead_run(did, market='lotteon', markets=['lotteon', 'eleven11'])
    calls = []
    monkeypatch.setattr(D, 'register_draft',
                        lambda s, d, market, **k: calls.append(market) or
                        {'ok': True, 'market_product_id': f'{market}-PID',
                         'error': None, 'excluded': []})

    r = client.post(f'/bulk/api/drafts/{did}/register',
                    json={'markets': ['lotteon', 'eleven11'],
                          'category_codes': {'lotteon': 'LO1', 'eleven11': '1'}})
    assert r.status_code == 202
    assert _wait_until(lambda: not _status(client, did)['running'])

    assert calls == ['eleven11'], f'회수된 실행이 처리중이던 마켓을 또 불렀다 — {calls}'
    rows = {x['market']: x for x in _status(client, did)['rows']}
    assert rows['lotteon']['status'] == 'uncertain', rows['lotteon']
    assert '마켓에서 상품 존재 확인 필요' in rows['lotteon']['notes']
    assert rows['eleven11']['status'] == 'ok'


def test_회수한_마켓은_장부에도_불확실로_남는다(client, monkeypatch):
    """다음 「점검」에서도 잠기게 — 결과표를 닫으면 잊히면 안 된다."""
    import webapp.routes.bulk.drafts as D
    from shared.db import SessionLocal
    from lemouton.registration.models import ProductDraftMarket

    did = _complete(client)
    _seed_dead_run(did, market='lotteon', markets=['lotteon'])
    monkeypatch.setattr(D, 'register_draft', lambda *a, **k: {})

    client.post(f'/bulk/api/drafts/{did}/register',
                json={'markets': ['lotteon'], 'category_codes': {'lotteon': 'LO1'}})
    assert _wait_until(lambda: not _status(client, did)['running'])

    s = SessionLocal()
    try:
        row = (s.query(ProductDraftMarket)
               .filter_by(draft_id=did, market='lotteon').first())
        assert row is not None and row.status == 'uncertain', row
    finally:
        s.close()


# ── 행이 없는 상태의 동시 INSERT(더블클릭) ────────────────────────────────

def test_행이_없을_때_동시_시작도_하나만_이긴다(client):
    """더블클릭 = 실행 상태 행이 아직 없는 상태에서 두 요청이 동시에 들어온다."""
    import webapp.routes.bulk.drafts as D
    from shared.db import SessionLocal

    did = _complete(client)
    got = []
    start = threading.Barrier(4)

    def claim():
        start.wait(timeout=5)
        for _ in range(6):
            sess = SessionLocal()
            try:
                got.append(D._claim_register_run(sess, did, ['lotteon']))
                return
            except Exception:       # noqa: BLE001 — SQLite 쓰기 잠금은 재시도로 흡수
                sess.rollback()
                time.sleep(0.05)
            finally:
                sess.close()
        got.append(None)

    threads = [threading.Thread(target=claim) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    winners = [j for j in got if j]
    assert len(winners) == 1, f'행이 없는 상태에서 {len(winners)}개가 동시에 시작했다'


def test_단수_등록도_부른_사실을_상태에_남긴다(client, monkeypatch):
    """안 남기면 폴링이 그 마켓을 pending(=「부른 적 없다」가 확실한 칸)으로 보고한다 —
    방금 불러 놓고 안 불렀다고 말하는 셈이다(거짓 안심 = 유령을 못 찾는다)."""
    import webapp.routes.bulk.drafts as D
    did = _complete(client)
    monkeypatch.setattr(D, 'register_draft',
                        lambda *a, **k: {'ok': True, 'market_product_id': 'LO-9',
                                         'error': None, 'excluded': []})

    client.post(f'/bulk/api/drafts/{did}/register/lotteon',
                json={'category_code': 'LO2727500650'})
    body = _status(client, did)
    assert body['pending'] == [], body
    assert [r['market'] for r in body['rows']] == ['lotteon'], body
    assert body['rows'][0]['status'] == 'ok'
