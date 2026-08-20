# -*- coding: utf-8 -*-
"""검색필터 실행 — 「지금 수집」 → 확장이 훑음 → 찾은 상품 URL 접수.

━━ 왜 이 모양인가 (죽은 큐를 피한 자리) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
`CrawlJob` 표가 있지만 **그 큐를 소비하는 워커가 저장소에 없다** — 그래서 예전
「검증」 버튼은 영원히 '대기'였다(`sourcing_guide.py:975~977` 원문). 거기 얹으면
또 안 도는 걸 만든다.

**살아 있는 경로는 하나다** — 확장이 `/api/crawl/due-bundles` 를 폴링하고
`/api/sources/crawl-result` 로 밀어 넣는다(background.js:2363). 검색필터도 같은
모양으로 붙인다: 서버는 「훑을 것」을 알려주고, 페이지를 여는 일은 로컬 PC 가 한다.

━━ 이 단계가 하는 일 / 안 하는 일 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
**한다**   — 검색 결과에서 **상품 주소를 찾아 모아 둔다**. 몇 개 나왔는지, 그 중
             몇 개가 새 것인지 안다.
**안 한다** — 그 상품을 크롤하거나 초안으로 만들지 않는다. 그건 이미 있는 경로다
             (`draft_from_url`). 여기서 다시 만들지 않는다.
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


LISTING = 'https://www.musinsa.com/search/goods?keyword=나이키'


def _make(client, **over):
    body = dict(source_key='musinsa', listing_url=LISTING)
    body.update(over)
    r = client.post('/bulk/api/search-filters', json=body)
    assert r.status_code == 200, r.get_data(as_text=True)
    fid = r.get_json()['filter']['id']
    _MADE_F.append(fid)
    return fid


# ── 만들기 ────────────────────────────────────────────────────────────

def test_검색필터를_만들면_이름이_자동으로_붙는다(client):
    """사장님이 이름을 안 지어도 목록에서 구분돼야 한다."""
    fid = _make(client)
    row = client.get('/bulk/api/search-filters').get_json()['filters']
    got = [f for f in row if f['id'] == fid][0]

    assert got['name'], '이름이 비어 있다'
    assert '무신사' in got['name'] or 'musinsa' in got['name'], got['name']


def test_규칙을_모르는_소싱처는_거절한다(client):
    """🔴 만들게 두면 「지금 수집」이 영원히 0건이 된다 — 만들 때 막는다."""
    r = client.post('/bulk/api/search-filters',
                    json={'source_key': '29cm', 'listing_url': 'https://29cm.co.kr/search?q=x'})
    assert r.status_code == 400, r.get_data(as_text=True)
    assert '29cm' in r.get_json().get('message', '')


# ── 「지금 수집」 → 확장이 가져갈 목록 ──────────────────────────────────

def test_지금_수집을_누르면_훑을_주소가_확장에게_나간다(client):
    fid = _make(client, page_from=1, page_to=2)
    client.post(f'/bulk/api/search-filters/{fid}/run')

    due = client.get('/api/crawl/due-listings').get_json()
    mine = [d for d in due['listings'] if d['filter_id'] == fid]

    assert len(mine) == 1, due
    assert mine[0]['source_key'] == 'musinsa'
    # 🔴 [2026-08-08 정정] 예전엔 `&page=1`·`&page=2` 두 주소를 기대했다.
    #   그런데 무신사는 `page=` 를 **서버가 아예 무시한다**(1쪽·2쪽 응답의 상품번호가
    #   완전히 동일, 둘 다 totalCount 2412). 그대로 뒀으면 같은 1쪽을 두 번 긁고
    #   「2장 봤다」고 거짓말했다. → **주소는 한 장**, 나머지는 응답이 주는
    #   `nextPageUrl` 을 따라간다(그래서 `click_pages` 가 2 로 온다).
    assert mine[0]['page_urls'] == [LISTING], mine[0]
    assert mine[0]['click_pages'] == 2, mine[0]
    assert mine[0]['next_url_re'], mine[0]


def test_안_누른_필터는_안_나간다(client):
    """🔴 만들어 두기만 한 필터가 저절로 돌면 소싱처를 두들긴다."""
    fid = _make(client)
    due = client.get('/api/crawl/due-listings').get_json()
    assert [d for d in due['listings'] if d['filter_id'] == fid] == []


# ── 결과 접수 ──────────────────────────────────────────────────────────

def test_확장은_번호만_보내고_주소는_서버가_조립한다(client):
    """🔴 주소 모양을 아는 곳은 서버 하나뿐이어야 한다 — 확장에서 조립하면 소싱처를
    하나 붙일 때마다 확장까지 고쳐야 하고, 그때마다 「다시 불러오기」를 부탁하게 된다."""
    from shared.db import SessionLocal
    from lemouton.registration.models import SearchFilterItem
    fid = _make(client)
    client.post(f'/bulk/api/search-filters/{fid}/run')

    r = client.post('/api/crawl/listing-result',
                    json={'filter_id': fid, 'ids': ['111', '222']})

    assert r.status_code == 200, r.get_data(as_text=True)
    body = r.get_json()
    assert body['found'] == 2 and body['new'] == 2, body

    s = SessionLocal()
    try:
        got = sorted(x.product_url for x in
                     s.query(SearchFilterItem).filter_by(filter_id=fid).all())
        assert got == ['https://www.musinsa.com/products/111',
                       'https://www.musinsa.com/products/222'], got
    finally:
        s.close()


def test_두_번째_수집에서는_새_것만_센다(client):
    """「신규상품수집」의 근거 — 몇 개가 **새로 늘었나**가 이 기능의 성적이다."""
    fid = _make(client)
    client.post(f'/bulk/api/search-filters/{fid}/run')
    client.post('/api/crawl/listing-result', json={'filter_id': fid, 'ids': ['111']})

    client.post(f'/bulk/api/search-filters/{fid}/run')
    r = client.post('/api/crawl/listing-result', json={
        'filter_id': fid, 'ids': ['111', '333']})   # 111=이미 있던 것 / 333=새 것

    body = r.get_json()
    assert body['found'] == 2, body
    assert body['new'] == 1, body


def test_결과를_받으면_그_필터는_목록에서_빠진다(client):
    """안 빠지면 확장이 같은 필터를 무한히 다시 훑는다."""
    fid = _make(client)
    client.post(f'/bulk/api/search-filters/{fid}/run')
    client.post('/api/crawl/listing-result',
                json={'filter_id': fid, 'ids': []})

    due = client.get('/api/crawl/due-listings').get_json()
    assert [d for d in due['listings'] if d['filter_id'] == fid] == []


def test_한_건도_못_찾아도_오류가_아니다(client):
    """검색 결과가 없을 수 있다 — 0 건은 정직한 답이다."""
    fid = _make(client)
    client.post(f'/bulk/api/search-filters/{fid}/run')
    r = client.post('/api/crawl/listing-result',
                    json={'filter_id': fid, 'ids': []})
    assert r.status_code == 200
    assert r.get_json()['found'] == 0
