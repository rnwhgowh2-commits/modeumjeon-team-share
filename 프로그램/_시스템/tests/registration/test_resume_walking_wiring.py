# -*- coding: utf-8 -*-
"""이어서 걷기가 **실제로 배선돼 있나** — 대기 목록과 결과 접수까지.

🔴 계산이 맞아도 배선이 없으면 소용없다. 예전에 「규칙을 넣었는데 확장이 안 쓰는」
   일이 있었다 — **「넣었다」와 「그게 쓰인다」는 다른 사실이다.**

★ 이 시험은 회차를 두 번 돌려 **2회차가 진짜로 다음 창을 걷는지** 본다.
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


def _make(client, source_key, listing_url, page_from=1, page_to=3):
    r = client.post('/bulk/api/search-filters',
                    json=dict(source_key=source_key, listing_url=listing_url,
                              page_from=page_from, page_to=page_to))
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


def _report(client, fid, ids, capped):
    r = client.post('/api/crawl/listing-result',
                    json=dict(filter_id=fid, ids=ids, capped=capped,
                              ext_version='test'))
    assert r.status_code == 200, r.get_data(as_text=True)


def test_더_있으면_2회차가_다음_창을_걷는다(client):
    """🔴 이 파일의 핵심 — 이게 없으면 60쪽에서 영영 멈춘다."""
    fid = _make(client, 'hmall', 'https://www.hmall.com/md/pde/search?searchTerm=나이키',
                page_from=1, page_to=3)

    job1 = _job(client, fid)
    assert [u.rsplit('page=', 1)[-1] for u in job1['page_urls']] == ['1', '2', '3'], job1

    _report(client, fid, ['1000001', '1000002'], capped=True)

    job2 = _job(client, fid)
    assert [u.rsplit('page=', 1)[-1] for u in job2['page_urls']] == ['4', '5', '6'], (
        f'2회차가 다음 창을 안 걷습니다: {job2["page_urls"]}'
    )


def test_끝까지_걸었으면_처음부터_다시(client):
    """🔴 커서를 그대로 두면 앞쪽에 들어온 새 상품을 영영 못 본다."""
    fid = _make(client, 'hmall', 'https://www.hmall.com/md/pde/search?searchTerm=나이키',
                page_from=1, page_to=2)

    _job(client, fid)
    _report(client, fid, ['1000001'], capped=True)      # 1~2 → 다음은 3~4
    _job(client, fid)
    _report(client, fid, ['1000002'], capped=False)     # 끝까지 걸었다

    job3 = _job(client, fid)
    assert [u.rsplit('page=', 1)[-1] for u in job3['page_urls']] == ['1', '2'], (
        f'처음으로 안 돌아갑니다: {job3["page_urls"]}'
    )


def test_단추로_넘기는_곳은_커서를_안_쓴다(client):
    """롯데온은 늘 1쪽에서 눌러 가야 한다 — 이어걷는 척하면 거짓말이 된다."""
    fid = _make(client, 'lotteon',
                'https://www.lotteon.com/search/search/search.ecn?q=나이키',
                page_from=1, page_to=5)

    _job(client, fid)
    _report(client, fid, ['LO1', 'LO2'], capped=True)

    job2 = _job(client, fid)
    # 주소는 한 장 그대로, 「몇 번 누를지」로 답한다.
    assert len(job2['page_urls']) == 1, job2['page_urls']
    assert job2['click_pages'] == 5, job2

    from shared.db import SessionLocal
    from lemouton.registration.models import SearchFilter
    s = SessionLocal()
    try:
        f = s.query(SearchFilter).filter_by(id=fid).first()
        assert getattr(f, 'next_page_from', None) is None, (
            '단추로 넘기는 곳에 이어걷기 커서가 남았습니다 — '
            '2회차가 엉뚱한 쪽부터 걷는 것처럼 보입니다.'
        )
    finally:
        s.close()
