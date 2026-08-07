# -*- coding: utf-8 -*-
"""찾은 주소 → 크롤 대기 → 초안. 「상품 만들기」 한 단추가 갈 수 있는 데까지 간다.

━━ 왜 이 모양인가 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
검색필터는 **주소만** 찾아 둔다. 그 주소가 상품이 되려면 두 걸음이 더 필요하다.

    찾은 주소(SearchFilterItem)
        │  ① 크롤 대상으로 등록  ← 이 파일이 만드는 것
        ▼
    SourceProduct  ──(확장이 크롤·이미 있음)──▶  가격·재고·옵션·이미지
        │  ② 초안 만들기 (draft_from_crawl·이미 있음)
        ▼
    ProductDraft

★ **재구현 금지.** ①은 `sources.service.upsert_source_product`, ②는
  `registration.draft_from_crawl.build_draft_from_source` 를 그대로 쓴다.
  크롤 자체는 여전히 로컬 PC 가 한다 — 서버는 대기열에 넣기만 한다.

━━ 🔴 자동으로 넣지 않는다 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
검색 한 번에 수백~수천 주소가 들어온다. 찾자마자 크롤 대기에 자동으로 넣으면
사장님 모르는 사이 크롤 부하가 몇 배가 된다(「거를 말」 같은 수집 시점 필터가
아직 안 먹는 상태라 더 그렇다). **사람이 눌러야** 들어간다.
"""
import pytest

_MADE_F, _MADE_SP, _MADE_D = [], [], []

URL_A = 'https://www.musinsa.com/products/900001'
URL_B = 'https://www.musinsa.com/products/900002'


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
    from lemouton.registration.models import (
        SearchFilter, SearchFilterItem, ProductDraft)
    from lemouton.sources.models import SourceProduct, SourceOption
    s = SessionLocal()
    try:
        for did in _MADE_D:
            r = s.query(ProductDraft).filter_by(id=did).first()
            if r is not None:
                s.delete(r)
        for fid in _MADE_F:
            for r in s.query(SearchFilterItem).filter_by(filter_id=fid).all():
                s.delete(r)
            r = s.query(SearchFilter).filter_by(id=fid).first()
            if r is not None:
                s.delete(r)
        for u in (URL_A, URL_B):
            for sp in s.query(SourceProduct).filter_by(url=u).all():
                for o in s.query(SourceOption).filter_by(source_product_id=sp.id).all():
                    s.delete(o)
                for d in s.query(ProductDraft).filter_by(source_url=u).all():
                    s.delete(d)
                s.delete(sp)
        s.commit()
    except Exception:       # noqa: BLE001
        s.rollback()
    finally:
        s.close()
        _MADE_F.clear(); _MADE_SP.clear(); _MADE_D.clear()


def _filter_with(client, urls):
    """검색필터 1개 + 그 필터가 찾은 주소들."""
    r = client.post('/bulk/api/search-filters', json={
        'source_key': 'musinsa',
        'listing_url': 'https://www.musinsa.com/search/goods?keyword=시험'})
    fid = r.get_json()['filter']['id']
    _MADE_F.append(fid)
    client.post(f'/bulk/api/search-filters/{fid}/run')
    ids = [u.rsplit('/', 1)[-1] for u in urls]
    client.post('/api/crawl/listing-result', json={'filter_id': fid, 'ids': ids})
    return fid


# ── ① 크롤 대기에 넣기 ────────────────────────────────────────────────

def test_상품_만들기를_누르면_찾은_주소가_크롤_대기에_들어간다(client):
    from shared.db import SessionLocal
    from lemouton.sources.models import SourceProduct
    fid = _filter_with(client, [URL_A, URL_B])

    r = client.post(f'/bulk/api/search-filters/{fid}/build')

    assert r.status_code == 200, r.get_data(as_text=True)
    body = r.get_json()
    assert body['queued'] == 2, body          # 크롤 대기에 새로 넣은 수
    assert body['drafted'] == 0, body         # 아직 크롤 전이라 초안은 0

    s = SessionLocal()
    try:
        got = {sp.url for sp in s.query(SourceProduct)
               .filter(SourceProduct.url.in_([URL_A, URL_B])).all()}
        assert got == {URL_A, URL_B}, got
        sp = s.query(SourceProduct).filter_by(url=URL_A).first()
        assert sp.site == 'musinsa', sp.site   # 소싱처가 필터에서 와야 한다
    finally:
        s.close()


def test_누르지_않으면_크롤_대기에_안_들어간다(client):
    """🔴 찾자마자 자동으로 들어가면 크롤 부하가 사장님 모르게 몇 배가 된다."""
    from shared.db import SessionLocal
    from lemouton.sources.models import SourceProduct
    _filter_with(client, [URL_A, URL_B])

    s = SessionLocal()
    try:
        n = s.query(SourceProduct).filter(SourceProduct.url.in_([URL_A, URL_B])).count()
        assert n == 0, f'누르지도 않았는데 {n}건이 대기에 들어갔다'
    finally:
        s.close()


def test_두_번_눌러도_대기가_두_배로_늘지_않는다(client):
    """멱등 — 같은 주소를 또 넣으면 크롤이 같은 상품을 두 번 돈다."""
    fid = _filter_with(client, [URL_A, URL_B])
    client.post(f'/bulk/api/search-filters/{fid}/build')

    body = client.post(f'/bulk/api/search-filters/{fid}/build').get_json()

    assert body['queued'] == 0, body          # 새로 넣은 것 없음
    assert body['waiting'] == 2, body         # 크롤을 기다리는 중


# ── ② 크롤된 것은 초안이 된다 ─────────────────────────────────────────

def test_크롤이_끝난_주소는_초안이_된다(client):
    from shared.db import SessionLocal
    from lemouton.registration.models import ProductDraft
    from lemouton.sources import service as SS
    fid = _filter_with(client, [URL_A])
    client.post(f'/bulk/api/search-filters/{fid}/build')

    # 확장이 크롤을 끝낸 상황을 재현 — 값이 채워진다.
    s = SessionLocal()
    try:
        sp = SS.upsert_source_product(s, site='musinsa', url=URL_A,
                                      product_name='시험 나이키 운동화')
        sp.last_price = 89000
        sp.last_status = 'ok'
        SS.upsert_source_option(s, source_product_id=sp.id, color_text='블랙',
                                size_text='270', current_price=89000, current_stock=3)
        s.commit()
    finally:
        s.close()

    body = client.post(f'/bulk/api/search-filters/{fid}/build').get_json()

    assert body['drafted'] == 1, body
    s = SessionLocal()
    try:
        d = s.query(ProductDraft).filter_by(source_url=URL_A).first()
        assert d is not None, '초안이 안 생겼다'
        _MADE_D.append(d.id)
        # 🔴 어느 검색필터에서 왔는지 새겨져야 성적표(수집→생존→매출)가 성립한다.
        assert d.search_filter_id == fid, d.search_filter_id
    finally:
        s.close()


def test_이미_초안이_된_것은_다시_안_만든다(client):
    """두 번 만들면 같은 상품이 초안 두 벌 = 마켓 중복 등록의 씨앗이다."""
    from shared.db import SessionLocal
    from lemouton.sources import service as SS
    fid = _filter_with(client, [URL_A])
    client.post(f'/bulk/api/search-filters/{fid}/build')
    s = SessionLocal()
    try:
        sp = SS.upsert_source_product(s, site='musinsa', url=URL_A,
                                      product_name='시험 나이키 운동화')
        sp.last_price = 89000
        sp.last_status = 'ok'
        SS.upsert_source_option(s, source_product_id=sp.id, color_text='블랙',
                                size_text='270', current_price=89000, current_stock=3)
        s.commit()
    finally:
        s.close()
    client.post(f'/bulk/api/search-filters/{fid}/build')

    body = client.post(f'/bulk/api/search-filters/{fid}/build').get_json()

    assert body['drafted'] == 0, body
    assert body['done'] == 1, body            # 이미 상품이 된 것


# ── 🔴 크롤이 꺼져 있으면 「기다리면 된다」고 말하면 안 된다 ──────────────

def test_크롤이_꺼져_있으면_그_사실을_알려준다(client):
    """🔴 라이브에서 실제로 겪음 — 30개를 대기에 넣었는데 크롤 자동 실행이 꺼져 있었다.

    그 상태로 「조금 뒤 한 번 더 누르면 늘어납니다」라고 안내하면 **거짓말**이다.
    기다려도 영영 안 늘어난다. 「대기에 넣었다」와 「그게 언젠가 처리된다」는 다른 사실이다.
    """
    from lemouton.pricing.settings import get_or_init
    from shared.db import SessionLocal
    fid = _filter_with(client, [URL_A])

    # ★ 전역 설정이라 반드시 되돌린다 — 안 되돌리면 뒤따르는 시험이
    #   「크롤 꺼짐」 상태를 물려받아 엉뚱한 곳에서 실패한다(시험 오염).
    s = SessionLocal()
    try:
        was = bool(get_or_init(s).crawl_auto_enabled)
        get_or_init(s).crawl_auto_enabled = False
        s.commit()
    finally:
        s.close()
    try:
        body = client.post(f'/bulk/api/search-filters/{fid}/build').get_json()
        assert body['queued'] == 1, body
        assert body['crawl_enabled'] is False, body
    finally:
        s = SessionLocal()
        try:
            get_or_init(s).crawl_auto_enabled = was
            s.commit()
        finally:
            s.close()
