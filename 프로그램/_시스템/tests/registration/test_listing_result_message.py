# -*- coding: utf-8 -*-
"""훑기가 실패했거나 중간에 멈췄으면 **화면이 그걸 말해야** 한다.

━━ 왜 이 시험이 필요한가 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
확장은 한 장이 실패하면 사유를 `error` 로 실어 보낸다 — 코드 주석이
「조용히 넘기지 않는다. 한 장이 실패한 걸 0건과 구분해야 한다」고 못박아 뒀다.
**그런데 서버가 그 값을 받기만 하고 버렸다**(2026-08-08 확인: 저장도 표시도 없음).
보내는 쪽이 아무리 정직해도 받는 쪽이 버리면 화면엔 그냥 「0건」이다.

━━ 두 사실을 갈라 둔다 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
`last_error`  — **못 봤다**(페이지가 안 열림 등). 0건과 다른 뜻이다.
`last_capped` — **더 있는데 여기서 멈췄다**(무한 스크롤을 정해진 횟수만 내림).
  뭉치면 「끝까지 다 봤다」로 읽혀, 사장님이 없는 상품을 없다고 믿게 된다.
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
    r = client.post('/bulk/api/search-filters', json={
        'source_key': 'musinsa',
        'listing_url': 'https://www.musinsa.com/search/goods?keyword=시험'})
    fid = r.get_json()['filter']['id']
    _MADE_F.append(fid)
    return fid


def _row(client, fid):
    rows = client.get('/bulk/api/search-filters').get_json()['filters']
    return [f for f in rows if f['id'] == fid][0]


def test_실패_사유가_화면까지_온다(client):
    """🔴 이게 없어서 「페이지가 안 열렸다」가 「0건」과 구분이 안 됐다."""
    fid = _make(client)

    client.post('/api/crawl/listing-result',
                json={'filter_id': fid, 'ids': [], 'error': '페이지 로드 시간 초과'})

    got = _row(client, fid)
    assert '시간 초과' in (got.get('last_error') or ''), got


def test_다음_훑기가_성공하면_옛_사유는_지워진다(client):
    """낡은 실패 문구가 남아 있으면 「지금도 고장」으로 읽힌다."""
    fid = _make(client)
    client.post('/api/crawl/listing-result',
                json={'filter_id': fid, 'ids': [], 'error': '페이지 로드 시간 초과'})

    client.post('/api/crawl/listing-result',
                json={'filter_id': fid, 'ids': ['111']})

    got = _row(client, fid)
    assert not got.get('last_error'), got


def test_중간에_멈춘_것은_실패와_다르게_말한다(client):
    """무한 스크롤을 정해진 횟수만 내렸다 = 못 본 상품이 더 있다."""
    fid = _make(client)

    client.post('/api/crawl/listing-result',
                json={'filter_id': fid, 'ids': ['111', '222'], 'capped': True})

    got = _row(client, fid)
    assert got.get('last_capped') is True, got
    assert not got.get('last_error'), '멈춘 것은 실패가 아니다'


def test_끝까지_봤으면_멈춤_표시가_없다(client):
    fid = _make(client)
    client.post('/api/crawl/listing-result',
                json={'filter_id': fid, 'ids': ['111'], 'capped': True})

    client.post('/api/crawl/listing-result',
                json={'filter_id': fid, 'ids': ['111', '222']})

    got = _row(client, fid)
    assert got.get('last_capped') is False, got


def test_훑기_규칙에_스크롤_횟수가_실려_온다(client):
    """무한 스크롤 소싱처는 내려야 더 나온다 — 몇 번 내릴지는 서버가 정한다."""
    fid = _make(client)
    client.post(f'/bulk/api/search-filters/{fid}/run')

    due = client.get('/api/crawl/due-listings').get_json()
    job = [j for j in due['listings'] if j['filter_id'] == fid][0]

    assert isinstance(job.get('scroll_rounds'), int), job
    assert job['scroll_rounds'] >= 1, job


def test_무한스크롤_소싱처가_더_많이_내린다():
    """페이지 넘김이 되는 곳은 조금만, 안 되는 곳은 많이 — 안 그러면 첫 화면만 걷힌다."""
    from lemouton.sources.listing_discover import dom_rule_for

    assert (dom_rule_for('lotteon')['scroll_rounds']
            > dom_rule_for('musinsa')['scroll_rounds'])
