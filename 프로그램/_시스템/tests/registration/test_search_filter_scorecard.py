# -*- coding: utf-8 -*-
"""필터별 성적표 — 「수집 → 상품 → 등록 → 매출」.

━━ 왜 필요한가 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
더망고에서 본 것 — 검색필터 12개 중 **돈이 된 건 3개**였다. 나머지 9개는 수천 개를
긁어 마켓에 올리고 관리비만 먹었다. 어느 필터가 그 3개인지 모르면 계속 다 돌린다.

━━ 이 성적표가 지키는 것 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔴 **매출 기준은 `정산예정금(배송비포함)`** — `orders/fulfillment.py::SETTLE_FIELD` 를
  그대로 쓴다. 수수료율로 되계산하면 「에러 없이 틀린 숫자」가 된다.
🔴 **금액을 못 읽은 주문을 0 원으로 세지 않는다.** 0 으로 뭉개면 「안 팔렸다」와
  「팔렸는데 금액을 모른다」가 같아져, 잘 되는 필터를 꺼 버릴 수 있다.
"""
import json

import pytest

_MADE = {'f': [], 'd': [], 'l': []}

URL_A = 'https://www.musinsa.com/products/950001'
PID = 'SS-950001'


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
        ProductDraft, ProductDraftMarket, SearchFilter, SearchFilterItem)
    from lemouton.markets.models_orders import MarketOrderLine
    s = SessionLocal()
    try:
        for uid in _MADE['l']:
            r = s.query(MarketOrderLine).filter_by(line_uid=uid).first()
            if r is not None:
                s.delete(r)
        for did in _MADE['d']:
            for r in s.query(ProductDraftMarket).filter_by(draft_id=did).all():
                s.delete(r)
            r = s.query(ProductDraft).filter_by(id=did).first()
            if r is not None:
                s.delete(r)
        for fid in _MADE['f']:
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
        for v in _MADE.values():
            v.clear()


def _seed(client, *, register=True, lines=()):
    """필터 1 + 찾은 주소 1 + 초안 1(+마켓 등록) + 주문라인들."""
    from datetime import datetime, timedelta
    from shared.db import SessionLocal
    from lemouton.registration.models import (
        ProductDraft, ProductDraftMarket, SearchFilterItem)
    from lemouton.markets.models_orders import MarketOrderLine
    from lemouton.orders.fulfillment import SETTLE_FIELD

    r = client.post('/bulk/api/search-filters', json={
        'source_key': 'musinsa',
        'listing_url': 'https://www.musinsa.com/search/goods?keyword=시험'})
    fid = r.get_json()['filter']['id']
    _MADE['f'].append(fid)

    s = SessionLocal()
    try:
        s.add(SearchFilterItem(filter_id=fid, product_url=URL_A))
        d = ProductDraft(origin='bulk', source='crawl', source_site='musinsa',
                         source_url=URL_A, name='시험상품', sale_price=0,
                         search_filter_id=fid)
        s.add(d)
        s.flush()
        _MADE['d'].append(d.id)
        if register:
            s.add(ProductDraftMarket(draft_id=d.id, market='ss', account_key='a',
                                     status='ok', market_product_id=PID))
        day = (datetime.utcnow() - timedelta(days=3)).strftime('%Y-%m-%d %H:%M:%S')
        for i, (pid, amount) in enumerate(lines):
            uid = f'시험라인{i}_{fid}'
            _MADE['l'].append(uid)
            row = {'_pd_market_product_id': pid}
            if amount is not None:
                row[SETTLE_FIELD] = amount
            s.add(MarketOrderLine(line_uid=uid, market='ss', order_no=uid,
                                  order_date=day, status='배송완료', account='a',
                                  row=row))
        s.commit()
    finally:
        s.close()
    return fid


def _card(client, fid):
    r = client.get(f'/bulk/api/search-filters/{fid}/scorecard')
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()


def test_수집_상품_등록_수를_센다(client):
    fid = _seed(client)

    got = _card(client, fid)

    assert got['found'] == 1, got
    assert got['drafted'] == 1, got
    assert got['registered'] == 1, got


def test_안_올린_것은_등록으로_안_센다(client):
    """「만들었다」와 「마켓에 올라갔다」는 다른 사실이다."""
    fid = _seed(client, register=False)

    got = _card(client, fid)

    assert got['drafted'] == 1 and got['registered'] == 0, got


def test_이_필터에서_나온_상품의_매출만_센다(client):
    """남의 상품 주문까지 세면 성적표가 통째로 거짓말이 된다."""
    fid = _seed(client, lines=[(PID, 30000), ('남의상품', 999000)])

    got = _card(client, fid)

    assert got['order_lines'] == 1, got
    assert got['sales'] == 30000, got


def test_금액을_못_읽은_주문은_0원으로_세지_않는다(client):
    """🔴 0 으로 뭉개면 「안 팔렸다」와 「팔렸는데 금액을 모른다」가 같아진다."""
    fid = _seed(client, lines=[(PID, 30000), (PID, None)])

    got = _card(client, fid)

    assert got['order_lines'] == 2, got
    assert got['sales'] == 30000, got
    assert got['sales_unknown_lines'] == 1, got


def test_한_건도_안_팔렸으면_0_이지_모름이_아니다(client):
    fid = _seed(client, lines=[])

    got = _card(client, fid)

    assert got['order_lines'] == 0 and got['sales'] == 0, got
    assert got['sales_unknown_lines'] == 0, got


def test_없는_필터는_404(client):
    r = client.get('/bulk/api/search-filters/99999999/scorecard')

    assert r.status_code == 404, r.status_code
