# -*- coding: utf-8 -*-
"""0건일 때 **무엇을 봤는지**와 **확장이 몇 판인지**를 화면이 말해야 한다.

━━ 왜 필요한가 (오늘 이걸로 헤맸다) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
2026-08-08 라이브 검증에서 두 가지를 한참 못 짚었다.

① **「화면 새로고침」은 확장 본체를 안 바꾼다.**
   사장님이 F5 를 누르시면 화면 쪽 파일만 새로 붙어 `data-moum-ext` 는 새 판을
   보여 주는데, 정작 일하는 본체(서비스워커)는 **옛 판 그대로**다.
   그래서 「확장 0.7.92 맞음」인데 동작은 0.7.88 이었다.
   → 확장이 결과를 보낼 때 **자기 판 번호를 같이** 보낸다. 그러면 서버가 안다.

② **0건이 두 가지 뜻인데 구분이 안 됐다.**
   「그 검색엔 상품이 없다」와 「우리 규칙이 그 화면과 안 맞는다」가 똑같이 0으로 보였다.
   SSG 가 0건으로 나왔을 때 어느 쪽인지 알 방법이 없었다.
   → 0건이면 **그 화면에 링크가 몇 개였고 우리 선택자에 몇 개 걸렸는지**를 같이 보낸다.
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


def test_0건이면_무엇을_봤는지_남는다(client):
    """🔴 그냥 0이라고만 하면 「상품이 없다」와 「규칙이 안 맞는다」가 같아진다."""
    fid = _make(client)

    client.post('/api/crawl/listing-result', json={
        'filter_id': fid, 'ids': [],
        'diag': '0건(나이키 신발 : SSG · 링크 312 · 선택자 0)'})

    got = _row(client, fid)
    assert '선택자 0' in (got.get('last_error') or ''), got


def test_확장_판_번호가_남는다(client):
    """🔴 「화면만 새로고침」하면 본체는 옛 판이다 — 서버가 알아볼 수 있어야 한다."""
    fid = _make(client)

    client.post('/api/crawl/listing-result', json={
        'filter_id': fid, 'ids': ['111'], 'ext_version': '0.7.93'})

    got = _row(client, fid)
    assert got.get('last_ext_version') == '0.7.93', got


def test_상품이_나오면_사유는_비운다(client):
    """낡은 문구가 남으면 「지금도 고장」으로 읽힌다."""
    fid = _make(client)
    client.post('/api/crawl/listing-result', json={
        'filter_id': fid, 'ids': [], 'diag': '0건(어쩌고)'})

    client.post('/api/crawl/listing-result', json={'filter_id': fid, 'ids': ['222']})

    got = _row(client, fid)
    assert not got.get('last_error'), got
