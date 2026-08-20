# -*- coding: utf-8 -*-
"""캐시 읽기·쓰기 — 같은 상품을 두 번 넣어도 한 줄이어야 한다."""
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from lemouton.catalog import repository as R
from lemouton.catalog.fetchers import CatalogRow
from lemouton.catalog.models import (
    MarketProduct, MarketProductCount, MarketProductGroup,
)
from shared.db import Base


def _session():
    engine = sa.create_engine('sqlite://')
    Base.metadata.create_all(engine, tables=[
        MarketProduct.__table__, MarketProductCount.__table__,
        MarketProductGroup.__table__,
    ])
    return sessionmaker(bind=engine)()


def _rows(n=2):
    return [CatalogRow(market_product_id=f'LO{i}', name=f'상품{i}',
                       status='sale', raw_status='SALE', sale_price=1000 + i)
            for i in range(n)]


def test_처음_넣으면_그대로_들어간다():
    s = _session()
    n = R.upsert_rows(s, 'lotteon', '브랜드위시', _rows(3))
    assert n == 3
    assert s.query(MarketProduct).count() == 3


def test_두_번_넣어도_한_줄이고_값이_갱신된다():
    s = _session()
    R.upsert_rows(s, 'lotteon', '브랜드위시', _rows(2))
    changed = [CatalogRow(market_product_id='LO0', name='이름 바뀜',
                          status='soldout', raw_status='SOUT', sale_price=9999)]
    R.upsert_rows(s, 'lotteon', '브랜드위시', changed)
    assert s.query(MarketProduct).count() == 2
    row = s.query(MarketProduct).filter_by(market_product_id='LO0').one()
    assert row.name == '이름 바뀜'
    assert row.status == 'soldout'
    assert row.sale_price == 9999


def test_같은_상품번호라도_계정이_다르면_따로():
    s = _session()
    R.upsert_rows(s, 'lotteon', '브랜드위시', _rows(1))
    R.upsert_rows(s, 'lotteon', '브랜드박스', _rows(1))
    assert s.query(MarketProduct).count() == 2


def test_이번에_안_보인_상품은_지운_것으로_표시만_한다():
    """마켓에서 사라진 것도 이력 — 행은 남긴다."""
    s = _session()
    R.upsert_rows(s, 'lotteon', '브랜드위시', _rows(3))
    R.mark_missing(s, 'lotteon', '브랜드위시', seen_ids={'LO0', 'LO1'})
    gone = s.query(MarketProduct).filter_by(market_product_id='LO2').one()
    assert gone.deleted_at is not None
    assert s.query(MarketProduct).count() == 3   # 지우지 않았다


def test_되살아나면_지움_표시가_풀린다():
    s = _session()
    R.upsert_rows(s, 'lotteon', '브랜드위시', _rows(1))
    R.mark_missing(s, 'lotteon', '브랜드위시', seen_ids=set())
    assert s.query(MarketProduct).one().deleted_at is not None
    R.upsert_rows(s, 'lotteon', '브랜드위시', _rows(1))
    assert s.query(MarketProduct).one().deleted_at is None


def test_건수를_캐시에서_세어_스냅샷으로_굳힌다():
    s = _session()
    rows = [CatalogRow(market_product_id='A', name='가', status='sale'),
            CatalogRow(market_product_id='B', name='나', status='sale'),
            CatalogRow(market_product_id='C', name='다', status='soldout')]
    R.upsert_rows(s, 'coupang', '세소쿠팡', rows)
    R.refresh_counts_from_cache(s, 'coupang', '세소쿠팡')
    got = {c.status: c.count for c in s.query(MarketProductCount).all()}
    assert got['sale'] == 2
    assert got['soldout'] == 1
    assert all(c.source == 'cache' for c in s.query(MarketProductCount).all())


def test_지운_상품은_건수에서_빠진다():
    s = _session()
    R.upsert_rows(s, 'coupang', '세소쿠팡', _rows(3))
    R.mark_missing(s, 'coupang', '세소쿠팡', seen_ids={'LO0'})
    R.refresh_counts_from_cache(s, 'coupang', '세소쿠팡')
    got = {c.status: c.count for c in s.query(MarketProductCount).all()}
    assert got['sale'] == 1


def test_전부_사라지면_건수가_0_으로_내려간다():
    """★ 옛 숫자가 남아 있으면 없는 상품을 있다고 보여준다."""
    s = _session()
    R.upsert_rows(s, 'coupang', '세소쿠팡', _rows(3))
    R.refresh_counts_from_cache(s, 'coupang', '세소쿠팡')
    assert s.query(MarketProductCount).filter_by(status='sale').one().count == 3
    R.mark_missing(s, 'coupang', '세소쿠팡', seen_ids=set())
    R.refresh_counts_from_cache(s, 'coupang', '세소쿠팡')
    assert s.query(MarketProductCount).filter_by(status='sale').one().count == 0


def test_마켓이_직접_알려준_건수는_api_로_남긴다():
    s = _session()
    R.set_count(s, 'lotteon', '브랜드위시', 'sale', 44102, source='api')
    c = s.query(MarketProductCount).one()
    assert c.count == 44102
    assert c.source == 'api'


def test_같은_칸을_두_번_써도_한_줄이고_최신값이다():
    s = _session()
    R.set_count(s, 'lotteon', '브랜드위시', 'sale', 1, source='api')
    R.set_count(s, 'lotteon', '브랜드위시', 'sale', 44102, source='api')
    assert s.query(MarketProductCount).count() == 1
    assert s.query(MarketProductCount).one().count == 44102


def test_대시보드용_건수를_마켓_계정으로_묶어_돌려준다():
    s = _session()
    R.set_count(s, 'lotteon', '브랜드위시', 'sale', 44102, source='api')
    R.set_count(s, 'lotteon', '브랜드위시', 'soldout', 612, source='api')
    R.set_count(s, 'coupang', '세소쿠팡', 'sale', 72, source='cache')
    out = R.dashboard_counts(s)
    assert out['lotteon']['브랜드위시']['sale'] == 44102
    assert out['lotteon']['브랜드위시']['soldout'] == 612
    assert out['coupang']['세소쿠팡']['sale'] == 72
