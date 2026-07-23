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


_MADE = []      # 이 파일이 만든 draft_id — 실행상태 행을 정확히 이것만 지운다.


@pytest.fixture(autouse=True)
def _cleanup():
    """`draft_register_runs` 는 draft_id 가 PK(드래프트당 1행)다 — 남기면 다음 테스트가
    이전 테스트의 running=True 를 물려받아 엉뚱한 409 를 본다."""
    yield
    from shared.db import SessionLocal
    from lemouton.registration.models import ProductDraftRegisterRun
    s = SessionLocal()
    try:
        for did in _MADE:
            for row in s.query(ProductDraftRegisterRun).filter_by(draft_id=did).all():
                s.delete(row)
        s.commit()
    except Exception:       # noqa: BLE001
        s.rollback()
    finally:
        s.close()
        _MADE.clear()


def _complete(client, **over):
    """등록 실행상태만 다루는 테스트라 드래프트는 저장만 되면 된다."""
    body = {'name': '테스트 자켓(잠금)', 'brand': '테스트브랜드', 'sale_price': 39000,
            'stock_quantity': 7}
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
