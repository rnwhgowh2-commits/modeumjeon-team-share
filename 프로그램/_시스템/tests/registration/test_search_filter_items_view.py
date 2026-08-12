# -*- coding: utf-8 -*-
"""「찾은 주소」를 볼 수 있어야 한다.

━━ 왜 필요한가 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
화면은 「찾음 31」이라고만 말한다. **무엇을 31개 찾았는지 볼 방법이 없다.**
그래서 검색어가 엉뚱해도(예: 「나이키」로 검색했는데 잡화가 딸려 옴) 상품을
만들어 보기 전엔 모른다. 수백~수천 건이면 그때 되돌리는 값이 크다.

★ 「상품 만들기」 전에 눈으로 확인할 수 있어야 한다 — 그게 이 화면의 값이다.
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


def _seed(client, ids):
    r = client.post('/bulk/api/search-filters', json={
        'source_key': 'musinsa',
        'listing_url': 'https://www.musinsa.com/search/goods?keyword=시험'})
    fid = r.get_json()['filter']['id']
    _MADE_F.append(fid)
    client.post('/api/crawl/listing-result', json={'filter_id': fid, 'ids': ids})
    return fid


def _items(client, fid, qs=''):
    r = client.get(f'/bulk/api/search-filters/{fid}/items{qs}')
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()


def test_찾은_주소를_돌려준다(client):
    fid = _seed(client, ['901', '902'])

    got = _items(client, fid)

    urls = [x['product_url'] for x in got['items']]
    assert 'https://www.musinsa.com/products/901' in urls, got
    assert got['total'] == 2, got


def test_아직_크롤_전인지_상품이_됐는지_같이_말한다(client):
    """🔴 주소만 보여주면 「왜 상품이 안 생기지」를 여전히 못 푼다."""
    from shared.db import SessionLocal
    from lemouton.sources import service as SS
    fid = _seed(client, ['903'])
    s = SessionLocal()
    try:                                   # 크롤이 끝난 상태를 심는다
        sp = SS.upsert_source_product(s, site='musinsa',
                                      url='https://www.musinsa.com/products/903')
        sp.last_status = 'ok'
        s.commit()
        spid = sp.id
    finally:
        s.close()

    got = _items(client, fid)
    row = got['items'][0]

    assert row['crawled'] is True, row
    assert row['drafted'] is False, row

    s = SessionLocal()                     # 뒷정리
    try:
        from lemouton.sources.models import SourceProduct
        r = s.query(SourceProduct).filter_by(id=spid).first()
        if r is not None:
            s.delete(r)
        s.commit()
    finally:
        s.close()


def test_아직_안_긁은_주소는_크롤됨이_아니다(client):
    """행이 있다고 크롤된 게 아니다 — 증거는 last_status=='ok' 하나뿐."""
    fid = _seed(client, ['904'])

    row = _items(client, fid)['items'][0]

    assert row['crawled'] is False, row


def test_많으면_잘라서_준다(client):
    """수천 건을 한 번에 내리면 화면이 멎는다. 자른 사실은 total 로 말한다."""
    fid = _seed(client, [str(900000 + i) for i in range(30)])

    got = _items(client, fid, '?limit=10')

    assert len(got['items']) == 10, len(got['items'])
    assert got['total'] == 30, got          # 🔴 자른 것을 숨기지 않는다


def test_없는_필터는_404(client):
    r = client.get('/bulk/api/search-filters/99999999/items')

    assert r.status_code == 404, r.status_code
