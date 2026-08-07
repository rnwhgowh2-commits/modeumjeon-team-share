# -*- coding: utf-8 -*-
"""검색필터를 **고칠 수 있어야** 한다 — 특히 가격 정책을 나중에 붙이는 것.

━━ 왜 필요한가 (라이브에서 드러남) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
2026-08-07 라이브 확인 중 발견 — 만들기·실행·상품만들기·지우기는 있는데
**고치기가 없었다.** 그래서 이미 만든 필터에 가격 정책을 나중에 붙일 방법이
지우고 다시 만드는 것뿐이었다.

    🔴 그런데 지우고 다시 만들면 **찾아 둔 주소를 다시 훑어야 한다.**
      라이브 필터는 이미 30개를 찾아 뒀는데 그게 통째로 헛일이 된다
      (소싱처를 또 두들기는 것이기도 하다).

정책은 「처음에 정하고 끝」이 아니라 **해 보고 바꾸는 값**이다 — 마진율을 올렸다
내렸다 하는 게 이 기능의 본체다. 고치는 길이 없으면 안 쓰게 된다.
"""
import pytest

_MADE_F, _MADE_P = [], []


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
    from lemouton.policy.models import MarketPolicy
    s = SessionLocal()
    try:
        for fid in _MADE_F:
            for r in s.query(SearchFilterItem).filter_by(filter_id=fid).all():
                s.delete(r)
            r = s.query(SearchFilter).filter_by(id=fid).first()
            if r is not None:
                s.delete(r)
        for pid in _MADE_P:
            r = s.query(MarketPolicy).filter_by(id=pid).first()
            if r is not None:
                s.delete(r)
        s.commit()
    except Exception:       # noqa: BLE001
        s.rollback()
    finally:
        s.close()
        _MADE_F.clear(); _MADE_P.clear()


def _make(client):
    r = client.post('/bulk/api/search-filters', json={
        'source_key': 'musinsa',
        'listing_url': 'https://www.musinsa.com/search/goods?keyword=시험'})
    fid = r.get_json()['filter']['id']
    _MADE_F.append(fid)
    # 이미 주소를 찾아 둔 상태 — 이게 있어서 「지우고 다시」가 비싸다.
    client.post(f'/bulk/api/search-filters/{fid}/run')
    client.post('/api/crawl/listing-result',
                json={'filter_id': fid, 'ids': ['920001', '920002']})
    return fid


def _policy(session, name='나중에 붙인 정책'):
    from lemouton.policy.models import MarketPolicy
    p = MarketPolicy(name=name, enabled_markets='smartstore')
    session.add(p)
    session.commit()
    _MADE_P.append(p.id)
    return p.id


def test_나중에_가격_정책을_붙일_수_있다(client):
    from shared.db import SessionLocal
    fid = _make(client)
    s = SessionLocal()
    try:
        pid = _policy(s)
    finally:
        s.close()

    r = client.patch(f'/bulk/api/search-filters/{fid}',
                     json={'apply_policy_id': pid})

    assert r.status_code == 200, r.get_data(as_text=True)
    got = [f for f in client.get('/bulk/api/search-filters').get_json()['filters']
           if f['id'] == fid][0]
    assert got['apply_policy_id'] == pid, got
    assert got['apply_policy_name'] == '나중에 붙인 정책', got


def test_고쳐도_찾아_둔_주소는_그대로다(client):
    """🔴 이게 「지우고 다시 만들기」와 다른 점이다 — 다시 훑을 필요가 없다."""
    from shared.db import SessionLocal
    fid = _make(client)
    s = SessionLocal()
    try:
        pid = _policy(s)
    finally:
        s.close()

    client.patch(f'/bulk/api/search-filters/{fid}', json={'apply_policy_id': pid})

    got = [f for f in client.get('/bulk/api/search-filters').get_json()['filters']
           if f['id'] == fid][0]
    assert got['found_total'] == 2, got


def test_정책을_뗄_수도_있다(client):
    """붙이기만 되고 못 떼면 「잘못 붙였을 때」 되돌릴 길이 없다."""
    from shared.db import SessionLocal
    fid = _make(client)
    s = SessionLocal()
    try:
        pid = _policy(s)
    finally:
        s.close()
    client.patch(f'/bulk/api/search-filters/{fid}', json={'apply_policy_id': pid})

    client.patch(f'/bulk/api/search-filters/{fid}', json={'apply_policy_id': None})

    got = [f for f in client.get('/bulk/api/search-filters').get_json()['filters']
           if f['id'] == fid][0]
    assert got['apply_policy_id'] is None, got


def test_수집_조건도_고칠_수_있다(client):
    """몇 개까지·몇 쪽까지도 해 보고 바꾸는 값이다."""
    fid = _make(client)

    r = client.patch(f'/bulk/api/search-filters/{fid}',
                     json={'max_items': 50, 'page_from': 1, 'page_to': 3,
                           'name': '이름도 바꿈'})

    assert r.status_code == 200, r.get_data(as_text=True)
    got = [f for f in client.get('/bulk/api/search-filters').get_json()['filters']
           if f['id'] == fid][0]
    assert (got['max_items'], got['page_from'], got['page_to']) == (50, 1, 3), got
    assert got['name'] == '이름도 바꿈', got


def test_안_보낸_칸은_안_건드린다(client):
    """🔴 일부만 고치려다 나머지가 비워지면 조용한 데이터 손실이다."""
    fid = _make(client)
    client.patch(f'/bulk/api/search-filters/{fid}',
                 json={'max_items': 50, 'page_to': 3})

    client.patch(f'/bulk/api/search-filters/{fid}', json={'page_to': 5})

    got = [f for f in client.get('/bulk/api/search-filters').get_json()['filters']
           if f['id'] == fid][0]
    assert got['page_to'] == 5, got
    assert got['max_items'] == 50, f'안 보낸 칸이 지워졌다: {got}'
