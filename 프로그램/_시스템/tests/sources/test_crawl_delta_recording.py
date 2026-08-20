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


def test_incoming_none_stock_is_not_a_change(db):
    # 크롤이 stock=None(확인 불가) 반환 → upsert가 기존값 보존 → DB 안 바뀜 → 변동 아님, streak 증가
    sp = _mk_product(db)
    real = [{"color_text": "블랙", "size_text": "220", "price": 50000, "stock": 3}]
    persist_crawled_options(db, source_product=sp, options=real); db.flush()  # streak=0(첫크롤)
    persist_crawled_options(db, source_product=sp, options=real); db.flush()  # 무변동 streak=1
    unknown = [{"color_text": "블랙", "size_text": "220", "price": 50000, "stock": None}]
    persist_crawled_options(db, source_product=sp, options=unknown); db.flush()
    last = (db.query(CrawlDelta).filter_by(source_product_id=sp.id)
            .order_by(CrawlDelta.id.desc()).first())
    assert last.stock_changed is False   # DB엔 3 그대로 → 변동 아님
    assert sp.no_change_streak == 2       # 리셋되지 않고 누적
    # DB 실제값도 보존됐는지
    from lemouton.sources.models import SourceOption
    row = db.query(SourceOption).filter_by(source_product_id=sp.id, deleted_at=None).first()
    assert row.current_stock == 3


def test_incoming_none_price_is_not_a_change(db):
    # price 도 None 가드 있음(upsert §191) → 들어온 price=None 은 저장상태 보존 → 변동 아님
    sp = _mk_product(db)
    real = [{"color_text": "블랙", "size_text": "220", "price": 50000, "stock": 3}]
    persist_crawled_options(db, source_product=sp, options=real); db.flush()  # streak=0(첫크롤)
    persist_crawled_options(db, source_product=sp, options=real); db.flush()  # 무변동 streak=1
    unknown = [{"color_text": "블랙", "size_text": "220", "price": None, "stock": 3}]
    persist_crawled_options(db, source_product=sp, options=unknown); db.flush()
    last = (db.query(CrawlDelta).filter_by(source_product_id=sp.id)
            .order_by(CrawlDelta.id.desc()).first())
    assert last.price_changed is False   # DB엔 50000 그대로 → 변동 아님
    assert sp.no_change_streak == 2       # 리셋되지 않고 누적
    from lemouton.sources.models import SourceOption
    row = db.query(SourceOption).filter_by(source_product_id=sp.id, deleted_at=None).first()
    assert row.current_price == 50000


from lemouton.sources.service import changed_product_ids_since


def test_changed_product_ids(db):
    sp1 = _mk_product(db)
    sp2 = SourceProduct(site="ssf", url="https://y/1"); db.add(sp2); db.flush()
    a = [{"color_text": "블랙", "size_text": "220", "price": 50000, "stock": 3}]
    b = [{"color_text": "블랙", "size_text": "220", "price": 50000, "stock": 0}]
    # sp1: 마지막 크롤이 변동 / sp2: 첫 크롤(변동으로 간주)
    persist_crawled_options(db, source_product=sp1, options=a); db.flush()
    persist_crawled_options(db, source_product=sp1, options=a); db.flush()  # 무변동
    persist_crawled_options(db, source_product=sp1, options=b); db.flush()  # 변동
    persist_crawled_options(db, source_product=sp2, options=a); db.flush()
    ids = changed_product_ids_since(db, only_latest=True)
    assert sp1.id in ids   # 마지막 크롤이 변동
    assert sp2.id in ids   # 첫 크롤 = 변동


def test_changed_product_ids_only_latest_excludes_now_stable(db):
    # 변동 후 안정되면 only_latest=True 에서는 빠져야 함
    sp = _mk_product(db)
    a = [{"color_text": "블랙", "size_text": "220", "price": 50000, "stock": 3}]
    b = [{"color_text": "블랙", "size_text": "220", "price": 50000, "stock": 0}]
    persist_crawled_options(db, source_product=sp, options=a); db.flush()  # 첫크롤=변동
    persist_crawled_options(db, source_product=sp, options=b); db.flush()  # 변동
    persist_crawled_options(db, source_product=sp, options=b); db.flush()  # 무변동(최신)
    ids = changed_product_ids_since(db, only_latest=True)
    assert sp.id not in ids   # 최신 크롤은 무변동
