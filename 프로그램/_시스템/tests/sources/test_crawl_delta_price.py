"""확장이 보낸 옵션에 price 가 있으면 가격 변동이 CrawlDelta 로 잡히는가.

라이브 실측: 회차 보고서의 '가격 변동'이 30개 회차 전부 0건이었다.
원인 = 확장이 options 를 {color,size,stock} 로만 보내 서버가 가격을 비교 못 함.
(persist_crawled_options 는 price 를 받을 걸로 설계돼 있음)
"""
from lemouton.sources.models import SourceProduct, CrawlDelta
from lemouton.sources.service import persist_crawled_options


def _sp(db):
    sp = SourceProduct(site="musinsa", url="https://www.musinsa.com/products/1")
    db.add(sp); db.flush()
    return sp


def _deltas(db):
    return db.query(CrawlDelta).order_by(CrawlDelta.id.asc()).all()


def test_price_change_detected_when_option_has_price(db):
    sp = _sp(db)
    # 1차 크롤 — 가격 115,000
    persist_crawled_options(db, source_product=sp,
                            options=[{"color": "블랙", "size": "265", "stock": 3, "price": 115000}])
    db.commit()
    # 2차 크롤 — 가격 119,900 (진짜 변동)
    persist_crawled_options(db, source_product=sp,
                            options=[{"color": "블랙", "size": "265", "stock": 3, "price": 119900}])
    db.commit()

    d = _deltas(db)[-1]
    assert d.price_changed is True
    assert "115000" in (d.detail or "") and "119900" in (d.detail or "")


def test_price_change_missed_when_option_lacks_price(db):
    """★현재 확장이 보내는 형태({color,size,stock}) — 가격 변동을 못 잡는다(버그 재현)."""
    sp = _sp(db)
    persist_crawled_options(db, source_product=sp,
                            options=[{"color": "블랙", "size": "265", "stock": 3, "price": 115000}])
    db.commit()
    # 확장이 price 를 빼고 보냄 → 서버는 기존 가격 보존 → '변동 없음'
    persist_crawled_options(db, source_product=sp,
                            options=[{"color": "블랙", "size": "265", "stock": 3}])
    db.commit()

    d = _deltas(db)[-1]
    assert d.price_changed is False          # 가격이 실제로 바뀌었어도 감지 불가


def test_stock_change_detected(db):
    """재고는 확장이 보내므로 원래 잡힌다(대조군)."""
    sp = _sp(db)
    persist_crawled_options(db, source_product=sp,
                            options=[{"color": "블랙", "size": "265", "stock": 3, "price": 115000}])
    db.commit()
    persist_crawled_options(db, source_product=sp,
                            options=[{"color": "블랙", "size": "265", "stock": 0, "price": 115000}])
    db.commit()

    d = _deltas(db)[-1]
    assert d.stock_changed is True
    assert "재고" in (d.detail or "")
