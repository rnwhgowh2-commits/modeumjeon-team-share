# -*- coding: utf-8 -*-
"""「뺄 옵션」이 **상품 만들기에서 실제로 먹어야** 한다.

순수 함수(`drop_excluded_options`)가 있는 것과 그게 라우트에 물려 있는 것은
다른 사실이다 — 이 저장소에서 이미 두 번 갈렸다(대기열·SetChannel).
"""
import pytest

_MADE_F, _MADE_D = [], []

URL_A = 'https://www.musinsa.com/products/940001'


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
        for fid in _MADE_F:
            for r in s.query(SearchFilterItem).filter_by(filter_id=fid).all():
                s.delete(r)
            r = s.query(SearchFilter).filter_by(id=fid).first()
            if r is not None:
                s.delete(r)
        for d in s.query(ProductDraft).filter_by(source_url=URL_A).all():
            s.delete(d)
        for sp in s.query(SourceProduct).filter_by(url=URL_A).all():
            for o in s.query(SourceOption).filter_by(source_product_id=sp.id).all():
                s.delete(o)
            s.delete(sp)
        s.commit()
    except Exception:       # noqa: BLE001
        s.rollback()
    finally:
        s.close()
        _MADE_F.clear(); _MADE_D.clear()


def _setup(client, words, options):
    """검색필터(뺄 말 지정) + 이미 크롤이 끝난 상품 1건."""
    from shared.db import SessionLocal
    from lemouton.sources import service as SS

    r = client.post('/bulk/api/search-filters', json={
        'source_key': 'musinsa',
        'listing_url': 'https://www.musinsa.com/search/goods?keyword=시험',
        'option_exclude_words': words})
    fid = r.get_json()['filter']['id']
    _MADE_F.append(fid)
    client.post(f'/bulk/api/search-filters/{fid}/run')
    client.post('/api/crawl/listing-result',
                json={'filter_id': fid, 'ids': [URL_A.rsplit('/', 1)[-1]]})

    s = SessionLocal()
    try:
        sp = SS.upsert_source_product(s, site='musinsa', url=URL_A,
                                      product_name='시험 나이키 운동화')
        sp.last_price = 89000
        sp.last_status = 'ok'
        for color, size in options:
            SS.upsert_source_option(s, source_product_id=sp.id, color_text=color,
                                    size_text=size, current_price=89000,
                                    current_stock=3)
        s.commit()
    finally:
        s.close()
    return fid


def _draft_options(url=URL_A):
    import json
    from shared.db import SessionLocal
    from lemouton.registration.models import ProductDraft
    s = SessionLocal()
    try:
        d = s.query(ProductDraft).filter_by(source_url=url).first()
        if d is None:
            return None
        return json.loads(d.options_json or '[]')
    finally:
        s.close()


def test_적어_둔_말이_든_옵션은_초안에_안_담긴다(client):
    fid = _setup(client, '샘플', [('블랙', '270'), ('블랙', '샘플용'), ('화이트', '280')])

    r = client.post(f'/bulk/api/search-filters/{fid}/build')

    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()['drafted'] == 1, r.get_json()
    # ★ 저장하면서 사이즈가 다듬어진다('270' → '270mm') — 글자 그대로 비교하지 않는다.
    got = _draft_options()
    assert len(got) == 2, got
    assert not [o for o in got if '샘플' in o['size']], got


def test_뺀_개수를_말해_준다(client):
    """조용히 빼면 「왜 옵션이 줄었지」를 사장님이 영영 못 푼다."""
    fid = _setup(client, '샘플', [('블랙', '270'), ('블랙', '샘플용')])

    body = client.post(f'/bulk/api/search-filters/{fid}/build').get_json()

    assert body.get('excluded_options') == 1, body


def test_말을_안_적었으면_하나도_안_빠진다(client):
    fid = _setup(client, '', [('블랙', '270'), ('블랙', '샘플용')])

    client.post(f'/bulk/api/search-filters/{fid}/build')

    got = _draft_options()
    assert len(got) == 2, got


def test_전부_걸리면_초안을_안_만들고_사유를_말한다(client):
    """🔴 옵션 0개짜리 초안이 생기면 「옵션 없는 단품」으로 굳어 재고·가격이
    통째로 틀린 상품이 조용히 마켓까지 간다."""
    # ★ 사이즈에 숫자가 섞이면 저장 때 '2mm' 로 다듬어져 글자가 사라진다
    #   (`_norm_size`: 숫자만 뽑아 mm 를 붙인다). 숫자 없는 말로 시험한다.
    fid = _setup(client, '샘플', [('블랙', '샘플용'), ('화이트', '샘플백')])

    body = client.post(f'/bulk/api/search-filters/{fid}/build').get_json()

    assert body['drafted'] == 0, body
    assert _draft_options() is None, '옵션 없는 초안이 생겼다'
    assert body.get('failed'), body
    assert '샘플' in body['failed'][0]['error'], body['failed']
