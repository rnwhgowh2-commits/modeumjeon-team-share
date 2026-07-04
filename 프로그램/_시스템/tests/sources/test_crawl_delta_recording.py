from lemouton.sources.models import SourceProduct, CrawlDelta
from lemouton.sources.service import persist_crawled_options


def test_new_columns_and_delta_table_exist(db):
    sp = SourceProduct(site="musinsa", url="https://x/1")
    db.add(sp)
    db.flush()
    assert sp.crawl_weight == 1
    assert sp.no_change_streak == 0
    d = CrawlDelta(source_product_id=sp.id, stock_changed=True,
                   price_changed=False, detail="test")
    db.add(d)
    db.flush()
    assert d.id is not None


def _mk_product(db):
    sp = SourceProduct(site="musinsa", url="https://x/9")
    db.add(sp); db.flush()
    return sp


def test_first_crawl_records_delta_and_streak(db):
    sp = _mk_product(db)
    opts = [{"color_text": "블랙", "size_text": "220", "price": 50000, "stock": 3}]
    persist_crawled_options(db, source_product=sp, options=opts)
    db.flush()
    deltas = db.query(CrawlDelta).filter_by(source_product_id=sp.id).all()
    assert len(deltas) == 1
    assert sp.no_change_streak == 0   # 첫 크롤(옵션 생김)=변동


def test_second_crawl_no_change_increments_streak(db):
    sp = _mk_product(db)
    opts = [{"color_text": "블랙", "size_text": "220", "price": 50000, "stock": 3}]
    persist_crawled_options(db, source_product=sp, options=opts); db.flush()
    persist_crawled_options(db, source_product=sp, options=opts); db.flush()
    last = (db.query(CrawlDelta).filter_by(source_product_id=sp.id)
            .order_by(CrawlDelta.id.desc()).first())
    assert last.stock_changed is False and last.price_changed is False
    assert sp.no_change_streak == 1


def test_change_resets_streak(db):
    sp = _mk_product(db)
    a = [{"color_text": "블랙", "size_text": "220", "price": 50000, "stock": 3}]
    b = [{"color_text": "블랙", "size_text": "220", "price": 50000, "stock": 0}]
    persist_crawled_options(db, source_product=sp, options=a); db.flush()
    persist_crawled_options(db, source_product=sp, options=a); db.flush()  # streak=1
    persist_crawled_options(db, source_product=sp, options=b); db.flush()  # 재고변동
    assert sp.no_change_streak == 0
