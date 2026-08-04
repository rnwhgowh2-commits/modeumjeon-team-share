# -*- coding: utf-8 -*-
"""고객 표면노출가 — 받아오면서 버리던 discountedPrice 를 저장·표시 (스스 한정).

사장님 실브라우저 검사 지적(2026-08-04): 「판매가와 고객 표면노출가로 나누어줘」.
지도 확인 결과 **이미 쓰는 목록 API 가 discountedPrice 를 같이 주는데 버리고 있었다**
(leafCategoryId 함정과 같은 부류). 새 API 0 — 저장만 추가.
🔴 다른 마켓 노출가는 미확인 → NULL 그대로(날조 금지). 마켓별 실측 후 하나씩.
"""
import pytest


def test_스스_fetcher_가_노출가를_읽는다():
    from lemouton.catalog.fetchers import _smartstore

    class FakeClient:
        def request(self, *a, **k):
            return {'totalElements': 1, 'contents': [{'channelProducts': [{
                'channelProductNo': 111, 'name': '검사', 'statusType': 'SALE',
                'salePrice': 147900, 'discountedPrice': 135820,
                'brandName': '르무통'}]}]}
    page = _smartstore(FakeClient(), 1)
    assert page.rows[0].sale_price == 147900
    assert page.rows[0].exposed_price == 135820, '버리던 값을 이제 담아야 한다'


def test_안_주면_NULL_그대로다():
    """0 이나 판매가로 채우면 날조다 — 없는 값은 없다고 둔다."""
    from lemouton.catalog.fetchers import _smartstore

    class FakeClient:
        def request(self, *a, **k):
            return {'totalElements': 1, 'contents': [{'channelProducts': [{
                'channelProductNo': 112, 'name': '검사2', 'statusType': 'SALE',
                'salePrice': 100000}]}]}
    page = _smartstore(FakeClient(), 1)
    assert page.rows[0].exposed_price is None


def test_저장까지_이어진다(monkeypatch):
    monkeypatch.setenv('DISABLE_AUTH', '1')
    import app as appmod
    appmod.create_app()
    from shared.db import SessionLocal
    from lemouton.catalog.fetchers import CatalogRow
    from lemouton.catalog.repository import upsert_rows
    from lemouton.catalog.models import MarketProduct
    s = SessionLocal()
    try:
        upsert_rows(s, 'smartstore', '노출가검사계정', [CatalogRow(
            market_product_id='EXP-1', name='노출가 검사', status='sale',
            sale_price=147900, exposed_price=135820)])
        s.commit()
        m = (s.query(MarketProduct)
             .filter_by(market='smartstore', account_key='노출가검사계정').first())
        assert m.exposed_price == 135820
        # 검색 행에도 실려 화면까지 간다
        from lemouton.catalog.search import search
        r = search(s, 'EXP-1', market='smartstore')
        assert r['rows'][0]['exposed_price'] == 135820
    finally:
        s.query(MarketProduct).filter_by(account_key='노출가검사계정').delete()
        s.commit(); s.close()


def test_화면에_두_칸이_있다(monkeypatch):
    monkeypatch.setenv('DISABLE_AUTH', '1')
    import app as appmod
    a = appmod.create_app(); a.config['TESTING'] = True
    html = a.test_client().get('/optgen?tab=market').get_data(as_text=True)
    assert '노출가' in html
    assert 'exposed_price' in html, '화면 JS 가 노출가를 안 그린다'
