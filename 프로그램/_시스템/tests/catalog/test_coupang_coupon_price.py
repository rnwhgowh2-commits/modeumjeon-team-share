# -*- coding: utf-8 -*-
"""쿠팡 쿠폰적용가 — 실측(run 30960940495) 응답 모양 그대로 검증.

사장님 확정: 쿠팡 고객 노출가 = 쿠폰적용가. 실측 사실 —
  · 쿠폰 type='PRICE'(정액 원) + discount, 대상은 옵션(vendorItemId) 단위
  · 목록 훑기엔 가격이 아예 없다 → 상세 items[].salePrice 로 계산
🔴 실측에 없던 쿠폰 type 은 계산에 넣지 않는다(추측=날조) — 로그만.
"""
import pytest

from lemouton.catalog.coupang_coupon import enrich_prices, fetch_coupon_discounts


class FakeClient:
    """실측 응답 꼴({code,data:{content:[…]}})을 그대로 흉내낸다."""

    def __init__(self, coupons, items_by_coupon):
        self.coupons = coupons
        self.items_by_coupon = items_by_coupon
        self._cfg = {'vendor_id': 'A9TEST'}
        self.calls = []

    def request(self, method, path, query=''):
        self.calls.append(path)
        if path.endswith('/coupons'):
            page = int(query.split('page=')[1].split('&')[0])
            return {'code': 200, 'data': {
                'content': self.coupons if page == 1 else []}}
        cid = int(path.split('/coupons/')[1].split('/')[0])
        page = int(query.split('page=')[1].split('&')[0])
        items = self.items_by_coupon.get(cid, [])
        chunk = items[(page - 1) * 50: page * 50]
        return {'code': 200, 'data': {'content': chunk}}


def _coupon(cid, disc, ctype='PRICE'):
    return {'couponId': cid, 'status': 'APPLIED', 'type': ctype,
            'discount': float(disc), 'promotionName': '검사쿠폰'}


def test_실측_모양대로_할인표를_만든다():
    c = FakeClient([_coupon(92831974, 1400)],
                   {92831974: [{'vendorItemId': 95285850693},
                               {'vendorItemId': 95285664328}]})
    d = fetch_coupon_discounts(c, 'A9TEST')
    assert d == {'95285850693': 1400, '95285664328': 1400}


def test_모르는_쿠폰_type_은_계산에_안_넣는다():
    """RATE 같은 건 실측에 없었다 — 추측으로 %를 곱하면 날조다."""
    c = FakeClient([_coupon(1, 10, ctype='RATE'), _coupon(2, 500)],
                   {1: [{'vendorItemId': 111}], 2: [{'vendorItemId': 222}]})
    d = fetch_coupon_discounts(c, 'A9TEST')
    assert d == {'222': 500}, 'PRICE 만 들어가야 한다'


def test_아이템_여러_페이지도_다_읽는다():
    items = [{'vendorItemId': 1000 + i} for i in range(120)]   # 50씩 3페이지
    c = FakeClient([_coupon(7, 300)], {7: items})
    d = fetch_coupon_discounts(c, 'A9TEST')
    assert len(d) == 120


def test_같은_옵션에_쿠폰_둘이면_큰_할인_하나만():
    c = FakeClient([_coupon(1, 300), _coupon(2, 1400)],
                   {1: [{'vendorItemId': 5}], 2: [{'vendorItemId': 5}]})
    assert fetch_coupon_discounts(c, 'A9TEST') == {'5': 1400}


# ── 상세 결합 — 판매가·노출가 계산 ──────────────────────────────────────
@pytest.fixture
def db(monkeypatch):
    monkeypatch.setenv('DISABLE_AUTH', '1')
    import app as appmod
    appmod.create_app()
    from shared.db import SessionLocal
    s = SessionLocal()
    yield s
    from lemouton.catalog.models import MarketProduct
    s.query(MarketProduct).filter_by(account_key='쿠폰가검사계정').delete()
    s.commit(); s.close()


def test_판매가와_쿠폰적용가가_채워진다(db, monkeypatch):
    from lemouton.catalog.models import MarketProduct
    db.add(MarketProduct(market='coupang', account_key='쿠폰가검사계정',
                         market_product_id='CP-1', name='쿠폰 검사', status='sale'))
    db.commit()

    c = FakeClient([_coupon(9, 1400)], {9: [{'vendorItemId': 501}]})
    # 상세 — 옵션 2개: 501(쿠폰 대상) 14,900 / 502(쿠폰 없음) 13,900
    monkeypatch.setattr(
        'shared.platforms.coupang.products.get_product',
        lambda pid, client=None: {'items': [
            {'vendorItemId': 501, 'salePrice': 14900},
            {'vendorItemId': 502, 'salePrice': 13900}]})
    r = enrich_prices(db, c, account_key='쿠폰가검사계정', vendor_id='A9TEST')
    # 🔴 커밋은 함수 안에서 이미 끝났어야 한다 — 밖에 커밋해 줄 사람이 없다
    #   (없으면 마지막 계정 몫이 세션 닫힐 때 증발 — 2026-08-05 실사고).
    db.rollback()
    assert r['filled'] == 1 and r['couponed_items'] == 1

    m = (db.query(MarketProduct)
         .filter_by(account_key='쿠폰가검사계정', market_product_id='CP-1').first())
    assert m.sale_price == 13900, '판매가 = 옵션 최저'
    # 노출가 = min(14900-1400=13500, 13900) = 13500 — 쿠폰이 최저를 바꾼다
    assert m.exposed_price == 13500


def test_상세가_비면_NULL_그대로다(db, monkeypatch):
    """값을 못 얻으면 못 얻은 채로 둔다 — 0/판매가 복제로 날조하지 않는다."""
    from lemouton.catalog.models import MarketProduct
    db.add(MarketProduct(market='coupang', account_key='쿠폰가검사계정',
                         market_product_id='CP-2', name='빈 상세', status='sale'))
    db.commit()
    c = FakeClient([], {})
    monkeypatch.setattr('shared.platforms.coupang.products.get_product',
                        lambda pid, client=None: {'items': []})
    enrich_prices(db, c, account_key='쿠폰가검사계정', vendor_id='A9TEST')
    m = (db.query(MarketProduct)
         .filter_by(account_key='쿠폰가검사계정', market_product_id='CP-2').first())
    assert m.sale_price is None and m.exposed_price is None


def test_상한에_걸리면_말한다(db, monkeypatch, caplog):
    """조용한 절반 채움 금지 — 로그로 표면화."""
    from lemouton.catalog.models import MarketProduct
    for i in range(3):
        db.add(MarketProduct(market='coupang', account_key='쿠폰가검사계정',
                             market_product_id=f'CP-L{i}', name=f'상한{i}',
                             status='sale'))
    db.commit()
    c = FakeClient([], {})
    monkeypatch.setattr('shared.platforms.coupang.products.get_product',
                        lambda pid, client=None: {'items': [
                            {'vendorItemId': 1, 'salePrice': 1000}]})
    import logging
    with caplog.at_level(logging.WARNING):
        r = enrich_prices(db, c, account_key='쿠폰가검사계정',
                          vendor_id='A9TEST', limit=2)
    assert r['truncated'] is True
    assert any('LIMIT' in rec.message or '만 가격' in rec.message
               for rec in caplog.records)


def test_훑기가_쿠팡이면_가격채우기를_부른다():
    """배선 확인 — sync_account 안에 훅이 있는지 글자로 고정."""
    from pathlib import Path
    src = (Path(__file__).resolve().parents[2] / 'lemouton' / 'catalog'
           / 'sync.py').read_text(encoding='utf-8')
    assert 'enrich_prices' in src, '훑기에 안 붙으면 새벽 3시에 영영 안 채워진다'
    assert "market == 'coupang'" in src
