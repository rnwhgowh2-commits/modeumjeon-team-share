# -*- coding: utf-8 -*-
"""배송비 표시 + 쿠팡 가격 누적 — 사장님 실브라우저 지적(2026-08-05 「왜 배송비가 안보여?」).

지도 확인: 배송비도 **이미 받는 응답이 주는데 버리던 값** —
  · 스스 목록 deliveryFee (기본 배송비)
  · 쿠팡 상세 deliveryCharge (무료형이면 0)
같이 잡은 실결함 2건 —
  🔴 훑기 upsert 가 쿠팡 가격을 매번 None 으로 도로 지움(목록엔 가격이 없어서)
  🔴 상세 500개를 밤마다 같은 최신 500개만 골라 나머지는 영영 안 채워짐
"""
import pytest


def test_스스_fetcher_가_배송비를_읽는다():
    from lemouton.catalog.fetchers import _smartstore

    class FakeClient:
        def request(self, *a, **k):
            return {'totalElements': 1, 'contents': [{'channelProducts': [{
                'channelProductNo': 211, 'name': '배송비 검사', 'statusType': 'SALE',
                'salePrice': 100000, 'deliveryFee': 3000}]}]}
    page = _smartstore(FakeClient(), 1)
    assert page.rows[0].delivery_fee == 3000


def test_안_주면_배송비_NULL_그대로다():
    from lemouton.catalog.fetchers import _smartstore

    class FakeClient:
        def request(self, *a, **k):
            return {'totalElements': 1, 'contents': [{'channelProducts': [{
                'channelProductNo': 212, 'name': '검사', 'statusType': 'SALE',
                'salePrice': 100000}]}]}
    assert _smartstore(FakeClient(), 1).rows[0].delivery_fee is None


@pytest.fixture
def db(monkeypatch):
    monkeypatch.setenv('DISABLE_AUTH', '1')
    import app as appmod
    appmod.create_app()
    from shared.db import SessionLocal
    s = SessionLocal()
    yield s
    from lemouton.catalog.models import MarketProduct
    s.query(MarketProduct).filter_by(account_key='배송비검사계정').delete()
    s.commit(); s.close()


def _mk(db, pid, **kw):
    from lemouton.catalog.models import MarketProduct
    m = MarketProduct(market='coupang', account_key='배송비검사계정',
                      market_product_id=pid, name=pid, status='sale', **kw)
    db.add(m)
    return m


def test_가격없는_목록으로_다시_훑어도_채운_가격이_안_지워진다(db):
    """🔴 실결함 — 쿠팡 목록엔 가격이 없어(None) 매 훑기가 채운 값을 도로 지웠다."""
    from lemouton.catalog.fetchers import CatalogRow
    from lemouton.catalog.repository import upsert_rows

    _mk(db, 'ACC-1', sale_price=14900, exposed_price=13500, delivery_fee=0)
    db.commit()
    upsert_rows(db, 'coupang', '배송비검사계정', [CatalogRow(
        market_product_id='ACC-1', name='ACC-1', status='sale')])   # 가격 전부 None
    db.expire_all()
    from lemouton.catalog.models import MarketProduct
    m = (db.query(MarketProduct)
         .filter_by(account_key='배송비검사계정', market_product_id='ACC-1').first())
    assert m.sale_price == 14900 and m.exposed_price == 13500, \
        '목록이 가격을 안 준다고 채운 값을 지우면 누적이 안 된다'
    assert m.delivery_fee == 0


def test_상한이_모자라면_빈_것부터_채운다(db, monkeypatch):
    """🔴 실결함 — 최신순만 뽑으면 밤마다 같은 500개만 다시 채운다."""
    from lemouton.catalog.coupang_coupon import enrich_prices

    _mk(db, 'ROT-이미채움', sale_price=10000, exposed_price=10000)
    _mk(db, 'ROT-빈것1')
    _mk(db, 'ROT-빈것2')
    db.commit()

    called = []
    monkeypatch.setattr(
        'shared.platforms.coupang.products.get_product',
        lambda pid, client=None: called.append(pid) or {
            'items': [{'vendorItemId': 1, 'salePrice': 5000}]})

    class NoCouponClient:
        _cfg = {'vendor_id': 'A9TEST'}
        def request(self, *a, **k):
            return {'code': 200, 'data': {'content': []}}

    enrich_prices(db, NoCouponClient(), account_key='배송비검사계정',
                  vendor_id='A9TEST', limit=2)
    assert set(called) == {'ROT-빈것1', 'ROT-빈것2'}, \
        f'빈 것부터 채워야 하는데 {called} 를 골랐다'


def test_쿠팡_상세의_배송비가_저장된다(db, monkeypatch):
    from lemouton.catalog.coupang_coupon import enrich_prices

    _mk(db, 'DF-1')
    db.commit()
    monkeypatch.setattr(
        'shared.platforms.coupang.products.get_product',
        lambda pid, client=None: {'deliveryCharge': 2500, 'items': [
            {'vendorItemId': 1, 'salePrice': 39900}]})

    class NoCouponClient:
        _cfg = {'vendor_id': 'A9TEST'}
        def request(self, *a, **k):
            return {'code': 200, 'data': {'content': []}}

    enrich_prices(db, NoCouponClient(), account_key='배송비검사계정',
                  vendor_id='A9TEST', limit=10)
    from lemouton.catalog.models import MarketProduct
    m = (db.query(MarketProduct)
         .filter_by(account_key='배송비검사계정', market_product_id='DF-1').first())
    assert m.delivery_fee == 2500 and m.sale_price == 39900


def test_화면_표에_배송비_칸이_있다(monkeypatch):
    monkeypatch.setenv('DISABLE_AUTH', '1')
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config['TESTING'] = True
    html = (flask_app.test_client().get('/optgen?tab=market')
            .get_data(as_text=True))
    assert '<th class="r">배송비</th>' in html
    assert 'r.delivery_fee' in html, '칸만 있고 값 배선이 없으면 영영 「—」'


def test_구형_중첩_모양도_읽는다(db, monkeypatch):
    """🔴 2026-08-06 프로브 실측 — 상세가 registrationType 따라 두 모양.

    구형(세소쿠팡 60/63): items[].marketplaceItemData.priceData.salePrice 중첩
    + 배송비는 marketplaceShippingAndReturnInfo 안. 신형만 읽으면 통째로 NULL.
    """
    from lemouton.catalog.coupang_coupon import enrich_prices

    _mk(db, 'LEG-1')
    db.commit()
    # 실측 응답 모양 그대로 (probe run 31023766509)
    monkeypatch.setattr(
        'shared.platforms.coupang.products.get_product',
        lambda pid, client=None: {
            'statusName': '승인완료',
            'marketplaceShippingAndReturnInfo': {
                'deliveryChargeType': 'NOT_FREE', 'deliveryCharge': 4000},
            'items': [
                {'marketplaceItemData': {'vendorItemId': 93775228689,
                                         'priceData': {'salePrice': 46000}}},
                {'marketplaceItemData': {'vendorItemId': 93775228692,
                                         'priceData': {'salePrice': 46000}}},
            ]})

    class OneCouponClient:
        _cfg = {'vendor_id': 'A9TEST'}
        def request(self, method, path, query=''):
            if path.endswith('/coupons'):
                page = int(query.split('page=')[1].split('&')[0])
                return {'code': 200, 'data': {'content': [
                    {'couponId': 7, 'status': 'APPLIED', 'type': 'PRICE',
                     'discount': 100.0}] if page == 1 else []}}
            page = int(query.split('page=')[1].split('&')[0])
            return {'code': 200, 'data': {'content': [
                {'vendorItemId': 93775228689}] if page == 1 else []}}

    r = enrich_prices(db, OneCouponClient(), account_key='배송비검사계정',
                      vendor_id='A9TEST', limit=10)
    assert r['filled'] == 1 and r['couponed_items'] == 1
    from lemouton.catalog.models import MarketProduct
    m = (db.query(MarketProduct)
         .filter_by(account_key='배송비검사계정', market_product_id='LEG-1').first())
    assert m.sale_price == 46000
    assert m.exposed_price == 45900, '중첩 vendorItemId 로도 쿠폰이 붙어야 한다'
    assert m.delivery_fee == 4000, '구형 배송비 자리(배송 묶음 안)도 읽어야 한다'
