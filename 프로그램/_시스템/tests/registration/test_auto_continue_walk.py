# -*- coding: utf-8 -*-
"""**끝까지 걷는다** — 「더 있음」이면 서버가 다음 회차를 스스로 예약한다.

🔴 왜 (2026-08-13, 사장님: 「완벽히 맞춰놓아」)
   현대H몰 「나이키 신발」은 456쪽이다. 한 회차 60쪽이니 **8번**을 눌러야 끝난다.
   롯데아이몰은 767쪽 — 13번이다. 사람이 그걸 손으로 누르고 앉아 있을 수 없다.

★ 그래서 결과를 받을 때 「더 있음」이면 **곧바로 다음 회차를 예약**한다.

🔴🔴 **스스로 멈추는 조건이 셋이다** — 이게 없으면 소싱처를 영원히 두들겨 차단당한다.
   ① 「더 있음」이 꺼지면 멈춘다(다 걸었다)
   ② **새로 걷은 것이 0이면 멈춘다** — 더 있다는데 안 늘면 헛도는 것이다
   ③ 필터를 꺼 두면 예약하지 않는다
   ④ 실패 사유가 있으면 예약하지 않는다(고장 난 채로 계속 두들기지 않는다)
"""
import pytest

_MADE_F = []


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('DISABLE_AUTH', '1')
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config['TESTING'] = True
    return flask_app.test_client()


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    from shared.db import SessionLocal
    from lemouton.registration.models import SearchFilter, SearchFilterItem
    s = SessionLocal()
    try:
        for fid in _MADE_F:
            for r in s.query(SearchFilterItem).filter_by(filter_id=fid).all():
                s.delete(r)
            r = s.query(SearchFilter).filter_by(id=fid).first()
            if r is not None:
                s.delete(r)
        s.commit()
    except Exception:       # noqa: BLE001
        s.rollback()
    finally:
        s.close()
        _MADE_F.clear()


def _make(client):
    r = client.post('/bulk/api/search-filters', json=dict(
        source_key='hmall',
        listing_url='https://www.hmall.com/md/pde/search?searchTerm=자동이어걷기시험',
        page_from=1, page_to=3))
    assert r.status_code == 200, r.get_data(as_text=True)
    fid = r.get_json()['filter']['id']
    _MADE_F.append(fid)
    return fid


def _report(client, fid, ids, capped, error=None):
    body = dict(filter_id=fid, ids=ids, capped=capped, ext_version='test')
    if error:
        body['error'] = error
    r = client.post('/api/crawl/listing-result', json=body)
    assert r.status_code == 200, r.get_data(as_text=True)


def _pending(client, fid) -> bool:
    j = client.get('/bulk/api/search-filters').get_json()
    row = [x for x in j['filters'] if x['id'] == fid]
    assert row, '방금 만든 필터가 목록에 없습니다.'
    return bool(row[0]['run_requested_at'])


def test_더_있고_새로_걷었으면_스스로_이어간다(client):
    """🔴 이 파일의 핵심 — 이게 없으면 사람이 456쪽을 손으로 눌러야 한다."""
    fid = _make(client)
    client.post(f'/bulk/api/search-filters/{fid}/run')
    _report(client, fid, ['900001', '900002'], capped=True)
    assert _pending(client, fid) is True, (
        '「더 있음」인데 다음 회차를 예약하지 않았습니다 — 사람이 계속 눌러야 합니다.'
    )


def test_다_걸었으면_멈춘다(client):
    """「더 있음」이 꺼지면 끝난 것이다 — 더 두들기지 않는다."""
    fid = _make(client)
    client.post(f'/bulk/api/search-filters/{fid}/run')
    _report(client, fid, ['900003'], capped=False)
    assert _pending(client, fid) is False


def test_새로_걷은_것이_0이면_멈춘다(client):
    """🔴🔴 가장 중요한 안전장치.

    소싱처가 늘 「더 있다」고 답하는데 상품은 안 늘 수 있다(헛돌기·이미 다 가짐).
    이때 멈추지 않으면 **영원히 두들겨 차단당한다.**
    """
    fid = _make(client)
    client.post(f'/bulk/api/search-filters/{fid}/run')
    _report(client, fid, ['900004'], capped=True)       # 1회차 — 새것 1
    assert _pending(client, fid) is True
    _report(client, fid, ['900004'], capped=True)       # 2회차 — 같은 것뿐
    assert _pending(client, fid) is False, (
        '새로 걷은 것이 없는데 계속 예약합니다 — 소싱처를 영원히 두들깁니다.'
    )


def test_실패_사유가_있으면_멈춘다(client):
    """고장 난 채로 계속 두들기지 않는다.

    ★ [2026-08-13] **예외 하나가 생겼다** — 못 걸은 쪽이 **줄고 있으면** 이어간다.
      그건 고장이 아니라 **줍는 중**이기 때문이다(H몰이 빠진 쪽을 되찾는 경우).
      자세한 것은 `test_missed_pages_retried.py`.
      여기서는 못 걸은 쪽이 **없는** 경우를 본다 — 그때는 그냥 고장이다.
    """
    fid = _make(client)
    client.post(f'/bulk/api/search-filters/{fid}/run')
    _report(client, fid, ['900005'], capped=True, error='훑는 중 시간 초과')
    assert _pending(client, fid) is False


def test_꺼_둔_필터는_안_이어간다(client):
    """사장님이 꺼 둔 것을 서버가 멋대로 돌리면 안 된다.

    ★ `enabled` 는 화면에서 고치는 칸이 아니라(PATCH 대상 아님) 저장소에서 직접 끈다.
    """
    from shared.db import SessionLocal
    from lemouton.registration.models import SearchFilter
    fid = _make(client)
    s = SessionLocal()
    try:
        row = s.query(SearchFilter).filter_by(id=fid).first()
        row.enabled = False
        s.commit()
    finally:
        s.close()
    client.post(f'/bulk/api/search-filters/{fid}/run')
    _report(client, fid, ['900006'], capped=True)
    assert _pending(client, fid) is False
