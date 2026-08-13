# -*- coding: utf-8 -*-
"""**못 걸은 쪽을 기억했다가 다시 건다** — 조용히 빠지지 않는다.

🔴🔴 왜 (2026-08-13 현대H몰 라이브 실측)
   크롬이 바쁠 때 탭이 열리다 죽는다(「페이지 로드 시간 초과」·「No tab with id」).
   그 쪽 상품이 통째로 빠지는데 **어느 쪽이었는지 아무도 기억하지 않아** 다시 걸
   방법이 없었다.

   결과 — H몰 463쪽(16,668개) 중 **13,920개만** 걷혔다. **16%(2,748개)가 빈 것이다.**
   그런데 화면엔 「끝남」으로 보였다.

   ★ 표본 30쪽을 손으로 훑어 **겹침 0**을 확인했다 — H몰은 중복이 없다.
     즉 13,920 은 「그것뿐」이 아니라 **못 걷은 것**이다.

★ 처방 둘 —
  ① 실패하면 **한 번 더 열어 본다**(일시적인 실패가 대부분이다)
  ② 두 번 다 실패하면 **그 쪽 주소를 기억**했다가 **다음 회차 맨 앞**에 세운다
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


URL = 'https://www.hmall.com/md/pde/search?searchTerm=못걸은쪽시험'


def _make(client):
    r = client.post('/bulk/api/search-filters', json=dict(
        source_key='hmall', listing_url=URL, page_from=1, page_to=3))
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


def _report(client, fid, ids, capped, missed=None):
    body = dict(filter_id=fid, ids=ids, capped=capped, ext_version='test')
    if missed:
        body['missed'] = missed
    r = client.post('/api/crawl/listing-result', json=body)
    assert r.status_code == 200, r.get_data(as_text=True)


def test_못_걸은_쪽을_다음_회차_맨앞에_세운다(client):
    """🔴 이 파일의 핵심 — 「나중에」로 미루면 영영 안 걷힌다."""
    fid = _make(client)
    job1 = _job(client, fid)
    miss = job1['page_urls'][1]                      # 2쪽을 못 걸었다 치자
    _report(client, fid, ['700001'], capped=True, missed=[miss])

    job2 = _job(client, fid)
    assert job2['page_urls'][0] == miss, (
        f'못 걸은 쪽이 맨 앞에 없습니다: {job2["page_urls"][:3]}'
    )


def test_성공하면_목록에서_빠진다(client):
    """성공했는데 계속 다시 걸면 헛돈다."""
    fid = _make(client)
    job1 = _job(client, fid)
    miss = job1['page_urls'][1]
    _report(client, fid, ['700002'], capped=True, missed=[miss])
    _report(client, fid, ['700003'], capped=True, missed=[])   # 이번엔 성공

    from shared.db import SessionLocal
    from lemouton.registration.models import SearchFilter
    s = SessionLocal()
    try:
        f = s.query(SearchFilter).filter_by(id=fid).first()
        assert not (getattr(f, 'missed_urls', None) or '').strip(), (
            '성공했는데 못 걸은 쪽 목록에 남아 있습니다 — 계속 헛돕니다.'
        )
    finally:
        s.close()


def test_같은_쪽이_계속_실패하면_멈춘다(client):
    """🔴 안 줄어드는데 계속 돌면 소싱처를 영원히 두들긴다."""
    fid = _make(client)
    job1 = _job(client, fid)
    miss = job1['page_urls'][1]
    _report(client, fid, ['700004'], capped=True, missed=[miss])    # 1회 — 새것 1
    _report(client, fid, [], capped=True, missed=[miss])            # 2회 — 그대로

    j = client.get('/bulk/api/search-filters').get_json()
    row = [x for x in j['filters'] if x['id'] == fid][0]
    assert not row['run_requested_at'], (
        '못 걸은 쪽이 안 줄었는데 계속 예약합니다 — 영원히 두들깁니다.'
    )


def test_줄어들고_있으면_이어간다(client):
    """못 걸은 쪽이 3 → 1 로 줄면 나아가는 중이다 — 계속 간다."""
    fid = _make(client)
    job1 = _job(client, fid)
    a, b, c = job1['page_urls'][:3]
    _report(client, fid, ['700005'], capped=True, missed=[a, b, c])
    _report(client, fid, [], capped=True, missed=[a])       # 셋 → 하나

    j = client.get('/bulk/api/search-filters').get_json()
    row = [x for x in j['filters'] if x['id'] == fid][0]
    assert row['run_requested_at'], (
        '못 걸은 쪽이 줄고 있는데 멈췄습니다 — 나아가는 중인데 포기합니다.'
    )
