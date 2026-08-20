# -*- coding: utf-8 -*-
"""검색필터 — 「리스팅 URL 한 줄 = 수집 행위 하나」를 영구 개체로.

━━ 왜 만드나 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
대량등록은 모음전과 근본이 다르다. 모음전은 옵션별 URL 을 사람이 하나씩 넣고 소싱처를
**비교**하지만, 대량등록은 **검색형 URL 한 줄**(무신사에 "나이키" 검색)로 수십~수천
상품을 자동 수집한다. 그 「한 줄」을 개체로 만들어야 정책·재수집·성적표가 그 위에 선다.
우리에게 이 개체가 **통째로 없었다**(설계서 §3-1).

━━ 🔴 더망고를 그대로 베끼면 안 되는 곳 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
더망고는 **검색필터를 지우면 그 필터로 수집한 상품이 전부 삭제**된다(§08-4 위험설계).
수집은 다시 하면 되지만 **이미 마켓에 올라간 상품과의 연결**은 되살릴 수 없다.
그래서 우리는 필터를 지워도 상품을 건드리지 않는다 — 이 파일이 그걸 못박는다.
"""
import pytest

_MADE_F, _MADE_D = [], []


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
    from lemouton.registration.models import ProductDraft, SearchFilter
    s = SessionLocal()
    try:
        for did in _MADE_D:
            r = s.query(ProductDraft).filter_by(id=did).first()
            if r is not None:
                s.delete(r)
        s.commit()
        for fid in _MADE_F:
            r = s.query(SearchFilter).filter_by(id=fid).first()
            if r is not None:
                s.delete(r)
        s.commit()
    except Exception:       # noqa: BLE001
        s.rollback()
    finally:
        s.close()
        _MADE_F.clear()
        _MADE_D.clear()


LISTING = 'https://www.musinsa.com/search/goods?keyword=나이키&keywordType=keyword&gf=A'


def _filter(s, **over):
    from lemouton.registration.models import SearchFilter
    kw = dict(name='무신사_나이키_001', source_key='musinsa', listing_url=LISTING)
    kw.update(over)
    f = SearchFilter(**kw)
    s.add(f)
    s.commit()
    _MADE_F.append(f.id)
    return f


def _draft(s, **over):
    from lemouton.registration.models import ProductDraft
    kw = dict(name='나이키 에어포스1', sale_price=139000)
    kw.update(over)
    d = ProductDraft(**kw)
    s.add(d)
    s.commit()
    _MADE_D.append(d.id)
    return d


def test_검색필터를_만들고_상품을_붙일_수_있다(client):
    from shared.db import SessionLocal
    s = SessionLocal()
    try:
        f = _filter(s)
        d = _draft(s, search_filter_id=f.id)

        assert f.source_key == 'musinsa'
        assert f.listing_url == LISTING
        assert d.search_filter_id == f.id
    finally:
        s.close()


def test_수집_시점_조건을_필터가_들고_있다(client):
    """저장 상품수 상한·페이지 범위 — 쓰레기가 들어오면 뒤에서 다 비용이다."""
    from shared.db import SessionLocal
    s = SessionLocal()
    try:
        f = _filter(s, max_items=50, page_from=1, page_to=3)

        assert f.max_items == 50
        assert (f.page_from, f.page_to) == (1, 3)
    finally:
        s.close()


def test_필터를_지워도_상품은_안_지워진다(client):
    """🔴 더망고 함정 회피 — 마켓에 올라간 상품과의 연결은 되살릴 수 없다."""
    from shared.db import SessionLocal
    from lemouton.registration.models import ProductDraft
    import datetime
    s = SessionLocal()
    try:
        f = _filter(s)
        d = _draft(s, search_filter_id=f.id)
        did = d.id

        f.deleted_at = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
        s.commit()
        s.expire_all()

        kept = s.query(ProductDraft).filter_by(id=did).first()
        assert kept is not None, '필터를 지웠더니 상품이 사라졌다'
        assert kept.deleted_at is None, '필터를 지웠더니 상품이 휴지통으로 갔다'
        assert kept.search_filter_id == f.id, '어느 필터에서 왔는지 기록이 지워졌다'
    finally:
        s.close()


def test_필터_없이도_상품이_만들어진다(client):
    """수기 등록 초안은 필터가 없다 — 비어 있어도 정상이다."""
    from shared.db import SessionLocal
    s = SessionLocal()
    try:
        d = _draft(s)
        assert d.search_filter_id is None
    finally:
        s.close()
