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


def test_훑기_규칙에_더있음_표시가_실려_온다(client):
    """🔴 [2026-08-08 실측 정정] 처음엔 「무한 스크롤이라 내리면 더 나온다」고 보고
    스크롤 횟수를 실어 보냈는데 **틀렸다.** 롯데온·롯데아이몰·현대H몰 모두 화면을
    끝까지 내려도 개수가 그대로였다(48→48 · 24→24 · 40→40, 안쪽 스크롤 상자까지 확인).
    셋 다 **단추로 넘기는** 방식이다.

    그래서 지금 할 수 있는 정직한 일은 하나다 — **「더 있다」를 알아보고 말하는 것.**
    페이지의 「다음」 단추가 살아 있으면 우리가 첫 장만 가져온 것이다."""
    fid = _make(client)
    client.post(f'/bulk/api/search-filters/{fid}/run')

    due = client.get('/api/crawl/due-listings').get_json()
    job = [j for j in due['listings'] if j['filter_id'] == fid][0]

    assert 'more_sel' in job, job          # 없으면 None 이라도 와야 한다


def test_단추로_넘기는_소싱처는_더있음_선택자가_있다():
    """실측한 곳만 넣는다 — 롯데온 `a.srchPaginationNext`(눌러서 상품이 바뀌는 것 확인)."""
    from lemouton.sources.listing_discover import dom_rule_for

    assert dom_rule_for('lotteon')['more_sel'], '롯데온 「다음」 선택자가 없다'


def test_결과없음_글귀가_규칙에_실려_온다():
    """🔴🔴 소싱처 대부분이 **결과가 0건이어도 추천 상품을 화면에 깐다.**
    실측(2026-08-08) — 「없습니다」 화면인데 우리 규칙에 잡힌 수:
      롯데온 25 · 롯데아이몰 25 · 현대H몰 12.
    막지 않으면 **오타 한 번에 엉뚱한 상품 수십 건이 크롤 대기에 들어가 초안까지 된다.**
    """
    from lemouton.sources.listing_discover import dom_rule_for

    for key in ('musinsa', 'lotteon', 'lotteimall', 'hmall', 'lemouton'):
        assert dom_rule_for(key)['empty_text'], f'{key} 「결과 없음」 글귀가 없다'


def test_결과없음_글귀를_모르는_곳은_비워_둔다():
    """★ 글귀가 없다고 0건으로 만들지는 않는다 — 있을 때만 「없다」고 확정한다.
    SSF 는 결과 0건이면 **정말 0건**이 나오는 것을 실측했다(추천이 안 깔린다)."""
    from lemouton.sources.listing_discover import dom_rule_for

    assert dom_rule_for('ssf')['empty_text'] is None


def test_모르는_곳은_지어내지_않는다():
    """선택자를 추측해 넣으면 「더 있음」이 늘 켜지거나 늘 꺼져 둘 다 거짓말이 된다."""
    from lemouton.sources.listing_discover import dom_rule_for

    assert dom_rule_for('musinsa')['more_sel'] is None
