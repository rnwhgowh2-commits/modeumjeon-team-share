# -*- coding: utf-8 -*-
"""훑기 규칙은 **서버가 확장에 내려보낸다.**

━━ 왜 이걸 고정하는가 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
확장 `background.js::_listingCollectIds` 는 **무신사 전용으로 박혀 있었다**
(`a[href*="/products/"]` + `/products/(\\d+)`). 그래서 서버에 SSF·롯데온 규칙을
넣어도 확장은 무신사 링크만 찾는다 → 새 소싱처는 **에러 없이 0건**이다.
「규칙을 넣었다」와 「그 규칙이 쓰인다」는 다른 사실이다.

★ 규칙을 서버가 주면 소싱처를 하나 더 붙일 때 **확장을 안 고쳐도 된다** —
  사장님께 「확장 다시 불러오기」를 부탁하는 횟수가 줄어든다.
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


def _make(client, source_key, listing_url):
    r = client.post('/bulk/api/search-filters',
                    json=dict(source_key=source_key, listing_url=listing_url))
    assert r.status_code == 200, r.get_data(as_text=True)
    fid = r.get_json()['filter']['id']
    _MADE_F.append(fid)
    return fid


def _job(client, fid):
    client.post(f'/bulk/api/search-filters/{fid}/run')
    due = client.get('/api/crawl/due-listings').get_json()
    got = [j for j in due['listings'] if j['filter_id'] == fid]
    assert got, due
    return got[0]


def test_훑을_목록에_규칙이_같이_실려_온다(client):
    fid = _make(client, 'ssf', 'https://www.ssfshop.com/search/result?keyword=나이키')

    job = _job(client, fid)

    assert job.get('sel'), job
    assert job.get('attr') == 'href', job
    assert 'good' in (job.get('id_re') or ''), job


def test_소싱처마다_다른_규칙이_온다(client):
    """한 벌짜리 규칙이면 새 소싱처가 조용히 0건이 된다."""
    a = _job(client, _make(client, 'musinsa',
                           'https://www.musinsa.com/search/goods?keyword=나이키'))
    b = _job(client, _make(client, 'hmall',
                           'https://www.hmall.com/md/pde/search?searchTerm=나이키'))

    assert a['id_re'] != b['id_re'], (a, b)
    assert b['attr'] == 'data-slitm-cd', b   # H몰은 링크가 아니라 속성


def test_규칙을_모르는_소싱처는_사유를_실어_보낸다(client):
    """조용히 빼면 「눌렀는데 아무 일도 안 남」이 된다."""
    from shared.db import SessionLocal
    from lemouton.registration.models import SearchFilter
    from datetime import datetime

    fid = _make(client, 'musinsa',
                'https://www.musinsa.com/search/goods?keyword=나이키')
    s = SessionLocal()
    try:                                  # 옛 데이터 흉내 — 만들 때는 막히는 값
        f = s.query(SearchFilter).filter_by(id=fid).first()
        f.source_key = 'gsshop'
        f.run_requested_at = datetime.utcnow()
        s.commit()
    finally:
        s.close()

    due = client.get('/api/crawl/due-listings').get_json()
    job = [j for j in due['listings'] if j['filter_id'] == fid][0]

    assert job.get('error'), job
    assert not job.get('page_urls'), job
