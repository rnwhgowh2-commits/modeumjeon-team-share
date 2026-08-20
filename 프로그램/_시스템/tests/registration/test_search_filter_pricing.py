# -*- coding: utf-8 -*-
"""검색필터에 가격 정책을 붙이면 만든 상품에 **판매가가 채워진다**.

━━ 산식은 한 줄도 새로 쓰지 않는다 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
「매입가 → 판매가」는 `pricing/unified.compute_sale_price_unified` 가 **단일 진실
원천**이고(마진율·마진금액·지정가 3종 + 수수료·배송비·라운딩·가드레일),
정책을 그 엔진이 읽는 모양으로 바꿔 주는 `policy/as_template.policy_as_template`
도 이미 있다. 구성→초안 경로(`send/as_draft`)가 이미 이 둘을 쓴다.

    🔴 같은 숫자를 두 곳에서 만들면 반드시 갈린다 — 여기서는 **잇기만** 한다.

━━ 🔴 모르면 지어내지 않는다 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
정책이 없거나 최종매입가를 모르면 **판매가를 0으로 둔다.** 0 은 「못 정했다」는
뜻이고, 사전 점검이 「판매가가 0 이하입니다」로 막는다. 아무 값이나 채우면 그
가격이 그대로 마켓에 나간다(돈이 걸린 자리라 폴백 금지).
"""
import pytest

_MADE_F, _MADE_D, _MADE_P = [], [], []

URL_A = 'https://www.musinsa.com/products/910001'


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
    from lemouton.policy.models import MarketPolicy, MarketPolicyValue
    s = SessionLocal()
    try:
        for d in s.query(ProductDraft).filter_by(source_url=URL_A).all():
            s.delete(d)
        for fid in _MADE_F:
            for r in s.query(SearchFilterItem).filter_by(filter_id=fid).all():
                s.delete(r)
            r = s.query(SearchFilter).filter_by(id=fid).first()
            if r is not None:
                s.delete(r)
        for sp in s.query(SourceProduct).filter_by(url=URL_A).all():
            for o in s.query(SourceOption).filter_by(source_product_id=sp.id).all():
                s.delete(o)
            s.delete(sp)
        for pid in _MADE_P:
            for v in s.query(MarketPolicyValue).filter_by(policy_id=pid).all():
                s.delete(v)
            r = s.query(MarketPolicy).filter_by(id=pid).first()
            if r is not None:
                s.delete(r)
        s.commit()
    except Exception:       # noqa: BLE001
        s.rollback()
    finally:
        s.close()
        _MADE_F.clear(); _MADE_D.clear(); _MADE_P.clear()


def _policy(session, *, rate=20):
    """판매가를 「마진율 rate%」로 정하는 정책 1건 (스마트스토어 기준)."""
    import json
    from lemouton.policy.models import MarketPolicy, MarketPolicyValue
    p = MarketPolicy(name='시험_마진20', enabled_markets='smartstore')
    session.add(p)
    session.commit()
    _MADE_P.append(p.id)
    session.add(MarketPolicyValue(
        policy_id=p.id, market='smartstore', field_key='price',
        value=json.dumps({'sourcing_mode': 'margin_rate', 'sourcing_rate': rate,
                          'fee_rate': 6, 'rounding_unit': 100},
                         ensure_ascii=False)))
    session.commit()
    return p.id


def _crawled(session, *, surface=100000):
    """크롤이 끝난 소싱처 상품 — 표면가만 있고 혜택은 없는 가장 단순한 경우."""
    from lemouton.sources import service as SS
    sp = SS.upsert_source_product(session, site='musinsa', url=URL_A,
                                  product_name='시험 상품')
    sp.last_price = surface
    sp.last_status = 'ok'
    SS.upsert_source_option(session, source_product_id=sp.id, color_text='블랙',
                            size_text='270', current_price=surface, current_stock=3)
    session.commit()
    return sp


def _filter(client, *, policy_id=None):
    r = client.post('/bulk/api/search-filters', json={
        'source_key': 'musinsa',
        'listing_url': 'https://www.musinsa.com/search/goods?keyword=시험',
        'apply_policy_id': policy_id})
    fid = r.get_json()['filter']['id']
    _MADE_F.append(fid)
    client.post(f'/bulk/api/search-filters/{fid}/run')
    client.post('/api/crawl/listing-result',
                json={'filter_id': fid, 'ids': ['910001']})
    return fid


# ── 정책 붙이기 ────────────────────────────────────────────────────────

def test_검색필터에_가격_정책을_붙일_수_있다(client):
    from shared.db import SessionLocal
    s = SessionLocal()
    try:
        pid = _policy(s)
    finally:
        s.close()

    fid = _filter(client, policy_id=pid)
    got = [f for f in client.get('/bulk/api/search-filters').get_json()['filters']
           if f['id'] == fid][0]

    assert got['apply_policy_id'] == pid, got
    assert got['apply_policy_name'] == '시험_마진20', got   # 화면에 이름이 보여야 한다


# ── 판매가 계산 ────────────────────────────────────────────────────────

def test_정책이_붙어_있으면_판매가가_채워진다(client):
    """🔴 산식은 엔진이 정한다 — 여기서는 「0이 아니고 매입가보다 크다」만 본다.
    숫자를 여기 적어 두면 엔진이 바뀔 때 시험이 거짓으로 통과한다."""
    from shared.db import SessionLocal
    from lemouton.registration.models import ProductDraft
    s = SessionLocal()
    try:
        pid = _policy(s, rate=20)
        _crawled(s, surface=100000)
    finally:
        s.close()
    fid = _filter(client, policy_id=pid)

    body = client.post(f'/bulk/api/search-filters/{fid}/build').get_json()

    assert body['drafted'] == 1, body
    s = SessionLocal()
    try:
        d = s.query(ProductDraft).filter_by(source_url=URL_A).first()
        assert d is not None
        assert d.sale_price > 0, '판매가가 안 채워졌다'
        assert d.sale_price > 100000, f'매입가보다 싸다: {d.sale_price}'
    finally:
        s.close()


def test_정책이_없으면_판매가를_지어내지_않는다(client):
    """🔴 아무 값이나 채우면 그 가격이 그대로 마켓에 나간다. 0 = 「못 정했다」."""
    from shared.db import SessionLocal
    from lemouton.registration.models import ProductDraft
    s = SessionLocal()
    try:
        _crawled(s, surface=100000)
    finally:
        s.close()
    fid = _filter(client, policy_id=None)

    body = client.post(f'/bulk/api/search-filters/{fid}/build').get_json()

    assert body['drafted'] == 1, body
    assert body['priced'] == 0, body        # 판매가를 정한 것
    assert body['unpriced'] == 1, body      # 못 정한 것 — 화면이 이 숫자를 보여준다
    s = SessionLocal()
    try:
        d = s.query(ProductDraft).filter_by(source_url=URL_A).first()
        assert (d.sale_price or 0) == 0, d.sale_price
    finally:
        s.close()


def test_매입가를_모르면_판매가를_안_만든다(client):
    """표면가가 없으면 마진을 붙일 바탕이 없다 — 그때도 지어내지 않는다."""
    from shared.db import SessionLocal
    from lemouton.registration.models import ProductDraft
    from lemouton.sources import service as SS
    s = SessionLocal()
    try:
        pid = _policy(s)
        sp = SS.upsert_source_product(s, site='musinsa', url=URL_A,
                                      product_name='표면가 없는 상품')
        sp.last_status = 'ok'          # 크롤은 됐지만 가격을 못 읽음
        SS.upsert_source_option(s, source_product_id=sp.id, color_text='블랙',
                                size_text='270', current_stock=3)
        s.commit()
    finally:
        s.close()
    fid = _filter(client, policy_id=pid)

    body = client.post(f'/bulk/api/search-filters/{fid}/build').get_json()

    assert body['unpriced'] == 1, body
    # 🔴 왜 못 정했는지 말해야 한다. 조용히 0 으로 두면 사장님은 원인을 못 찾는다.
    assert body['unpriced_reasons'], body
    assert '표면가' in ' '.join(body['unpriced_reasons']), body['unpriced_reasons']
    s = SessionLocal()
    try:
        d = s.query(ProductDraft).filter_by(source_url=URL_A).first()
        assert (d.sale_price or 0) == 0, d.sale_price
    finally:
        s.close()


def test_계산이_터져도_조용히_넘기지_않는다(client):
    """🔴 실제로 겪음 — 없는 함수를 부르는 버그를 `except` 가 삼켜 판매가가 조용히
    0 이 됐다. 시험이 「0이 아니다」를 안 봤으면 그대로 나갔을 것이다.
    터진 사실은 사유로 남아야 한다."""
    from shared.db import SessionLocal
    s = SessionLocal()
    try:
        pid = _policy(s)
        _crawled(s, surface=100000)
    finally:
        s.close()
    fid = _filter(client, policy_id=pid)

    import webapp.routes.bulk.search_filters as SF
    real = SF.compute_price_for
    SF.compute_price_for = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('일부러 터뜨림'))
    try:
        body = client.post(f'/bulk/api/search-filters/{fid}/build').get_json()
    finally:
        SF.compute_price_for = real

    assert body['unpriced'] == 1, body
    assert body['unpriced_reasons'], body
