# -*- coding: utf-8 -*-
"""타마켓 가격·배송비 — 사장님 지적(2026-08-06 「쿠팡뿐만 아니라 타마켓도 동일문제」).

프로브 실측(run 31024768904) 근거 —
  · ESM 목록: price(사이트별) + sellerDiscount{type,discountAmt} + shipping.fee
    (type 0:사용안함 1:정액 2:정률 — 지도 esm.20. 정률은 단위 미실측 → 계산 금지)
  · 롯데온 목록: 가격·배송비 필드 0개 → 상세 itmLst[].slPrc 로 판매가만
  · 11번가 목록: 기본배송비·할인액 없음(반품 rtngdDlvCst·교환 exchDlvCst 뿐) → 「—」 유지
"""
import pytest


def _esm_item(**over):
    it = {
        'goodsNo': '5806568636',
        'siteGoodsNo': {'gmkt': None, 'iac': 'F292819719'},
        'sellStatus': {'gmkt': None, 'iac': '22'},
        'price': {'gmkt': 0.0, 'iac': 70600.0},
        'sellerDiscount': {'gmkt': {'type': 0, 'discountAmt': 0.0},
                           'iac': {'type': 0, 'discountAmt': 0.0}},
        'shipping': {'fee': 0.0, 'placeNo': 23590515},
        'goodsName': '필라 페이토 샌들', 'brand': {'id': 0, 'name': None},
    }
    it.update(over)
    return it


class _EsmClient:
    def __init__(self, items):
        self.items = items

    def request(self, **kw):
        return {'data': {'items': self.items, 'totalItems': len(self.items)}}


def _fetch(items):
    from lemouton.catalog.fetchers import _esm
    return _esm('auction', _EsmClient(items), 1).rows


def test_ESM_할인없음이면_노출가는_판매가_그대로다():
    r = _fetch([_esm_item()])[0]
    assert r.sale_price == 70600
    assert r.exposed_price == 70600, '할인 없음 = 고객가 그대로(실측 type 0)'
    assert r.delivery_fee == 0, 'shipping.fee 0 = 무료배송(실측)'


def test_ESM_정액할인은_뺀다():
    it = _esm_item(sellerDiscount={'gmkt': None,
                                   'iac': {'type': 1, 'discountAmt': 5000.0}})
    r = _fetch([it])[0]
    assert r.exposed_price == 65600


def test_ESM_정률은_계산_안_하고_비운다():
    """discountAmt 가 원인지 %인지 실측 못 함 — 추측하면 날조."""
    it = _esm_item(sellerDiscount={'gmkt': None,
                                   'iac': {'type': 2, 'discountAmt': 10.0}})
    r = _fetch([it])[0]
    assert r.exposed_price is None


def test_ESM_배송비가_있으면_담는다():
    it = _esm_item(shipping={'fee': 3000.0})
    assert _fetch([it])[0].delivery_fee == 3000


# ── 롯데온 상세 기반 판매가 ────────────────────────────────────────────
@pytest.fixture
def db(monkeypatch):
    monkeypatch.setenv('DISABLE_AUTH', '1')
    import app as appmod
    appmod.create_app()
    from shared.db import SessionLocal
    s = SessionLocal()
    yield s
    from lemouton.catalog.models import MarketProduct
    s.query(MarketProduct).filter_by(account_key='롯데온가격검사').delete()
    s.commit(); s.close()


def test_롯데온_상세의_옵션최저가가_판매가로_담긴다(db, monkeypatch):
    from lemouton.catalog.models import MarketProduct
    from lemouton.catalog.lotteon_prices import enrich_prices

    db.add(MarketProduct(market='lotteon', account_key='롯데온가격검사',
                         market_product_id='LO-1', name='롯데온 검사', status='sale'))
    db.commit()
    # 실측 모양: data.itmLst[].slPrc (옵션별 판매가)
    monkeypatch.setattr(
        'shared.platforms.lotteon.products.get_product_detail',
        lambda spd, client=None, **k: {'itmLst': [
            {'sitmNo': 'a', 'slPrc': 45000}, {'sitmNo': 'b', 'slPrc': 43000}]})
    r = enrich_prices(db, object(), account_key='롯데온가격검사')
    db.rollback()   # 커밋은 함수 안에서 끝났어야 한다(쿠팡과 같은 규약)
    assert r['filled'] == 1
    m = (db.query(MarketProduct)
         .filter_by(account_key='롯데온가격검사', market_product_id='LO-1').first())
    assert m.sale_price == 43000
    assert m.exposed_price is None, '노출가는 미실측 — 판매가 복제는 날조'
    assert m.delivery_fee is None, '배송비는 정책번호뿐(금액 미실측) — NULL'


def test_롯데온_상세가_비면_NULL_그대로다(db, monkeypatch):
    from lemouton.catalog.models import MarketProduct
    from lemouton.catalog.lotteon_prices import enrich_prices

    db.add(MarketProduct(market='lotteon', account_key='롯데온가격검사',
                         market_product_id='LO-2', name='빈 상세', status='sale'))
    db.commit()
    monkeypatch.setattr(
        'shared.platforms.lotteon.products.get_product_detail',
        lambda spd, client=None, **k: {'itmLst': []})
    enrich_prices(db, object(), account_key='롯데온가격검사')
    m = (db.query(MarketProduct)
         .filter_by(account_key='롯데온가격검사', market_product_id='LO-2').first())
    assert m.sale_price is None


def test_훑기가_롯데온이면_가격채우기를_부른다():
    from pathlib import Path
    src = (Path(__file__).resolve().parents[2] / 'lemouton' / 'catalog'
           / 'sync.py').read_text(encoding='utf-8')
    assert 'lotteon_prices' in src
    assert "market == 'lotteon'" in src
