# -*- coding: utf-8 -*-
"""계정 하나 동기화 — 페이지를 끝까지 넘기고, 실패해도 다음 계정으로 간다."""
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from lemouton.catalog import sync as S
from lemouton.catalog.fetchers import CatalogPage, CatalogRow
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


def _page(ids, total=None, token=None):
    return CatalogPage(
        rows=[CatalogRow(market_product_id=str(i), name=f'상품{i}',
                         status='sale', raw_status='SALE') for i in ids],
        total=total, next_token=token)


def test_총건수를_주는_마켓은_그_수만큼_넘긴다(monkeypatch):
    """롯데온 250건 = 100씩 3페이지."""
    calls = []

    def fake(market, client, page_index, **kw):
        calls.append(page_index)
        start = (page_index - 1) * 100
        return _page(range(start, min(start + 100, 250)), total=250)

    monkeypatch.setattr(S, 'fetch_page', fake)
    s = _session()
    r = S.sync_account(s, 'lotteon', '브랜드위시', client=object())
    assert calls == [1, 2, 3]
    assert r['saved'] == 250
    assert s.query(MarketProduct).count() == 250


def test_총건수를_안_주는_마켓은_덜_찬_페이지에서_멈춘다(monkeypatch):
    """11번가 — 마지막 페이지가 덜 차면 거기서 멈춘다."""
    def fake(market, client, page_index, **kw):
        if page_index == 1:
            return _page(range(0, 100))
        if page_index == 2:
            return _page(range(100, 130))    # 100 미만 = 마지막
        raise AssertionError('더 부르면 안 된다')

    monkeypatch.setattr(S, 'fetch_page', fake)
    s = _session()
    r = S.sync_account(s, 'eleven11', '브랜드마켓11번가', client=object())
    assert r['saved'] == 130


def test_쿠팡은_다음_열쇠가_없을_때까지(monkeypatch):
    seen = []

    def fake(market, client, page_index, **kw):
        seen.append(kw.get('next_token'))
        if kw.get('next_token') is None:
            return _page(range(0, 100), token='TK2')
        if kw.get('next_token') == 'TK2':
            return _page(range(100, 150), token=None)
        raise AssertionError('더 부르면 안 된다')

    monkeypatch.setattr(S, 'fetch_page', fake)
    s = _session()
    r = S.sync_account(s, 'coupang', '세소쿠팡', client=object())
    assert seen == [None, 'TK2']
    assert r['saved'] == 150


def test_동기화가_끝나면_건수_스냅샷이_생긴다(monkeypatch):
    monkeypatch.setattr(S, 'fetch_page',
                        lambda m, c, p, **kw: _page(range(0, 5), total=5))
    s = _session()
    S.sync_account(s, 'lotteon', '브랜드위시', client=object())
    counts = {c.status: c.count for c in s.query(MarketProductCount).all()}
    assert counts['sale'] == 5


def test_사라진_상품은_두_번째_훑기에서_표시된다(monkeypatch):
    monkeypatch.setattr(S, 'fetch_page',
                        lambda m, c, p, **kw: _page(range(0, 3), total=3))
    s = _session()
    S.sync_account(s, 'lotteon', '브랜드위시', client=object())

    monkeypatch.setattr(S, 'fetch_page',
                        lambda m, c, p, **kw: _page(range(0, 2), total=2))
    r = S.sync_account(s, 'lotteon', '브랜드위시', client=object())
    assert r['missing'] == 1
    assert s.query(MarketProduct).count() == 3           # 지우지 않았다
    counts = {c.status: c.count for c in s.query(MarketProductCount).all()}
    assert counts['sale'] == 2                            # 건수에선 빠졌다


def test_한_페이지가_터져도_그때까지_받은_건_남긴다(monkeypatch):
    """중간 실패로 전부 잃으면 안 된다 — 받은 만큼은 저장하고 실패를 알린다."""
    def fake(market, client, page_index, **kw):
        if page_index == 1:
            return _page(range(0, 100), total=250)
        raise RuntimeError('마켓이 응답하지 않습니다')

    monkeypatch.setattr(S, 'fetch_page', fake)
    s = _session()
    r = S.sync_account(s, 'lotteon', '브랜드위시', client=object())
    assert r['saved'] == 100
    assert r['ok'] is False
    assert '마켓이 응답하지 않습니다' in r['error']
    assert s.query(MarketProduct).count() == 100


def test_중간에_실패하면_사라짐_표시를_하지_않는다(monkeypatch):
    """★ 절반만 받고 나머지를 '사라졌다'고 하면 멀쩡한 상품이 사라진다."""
    monkeypatch.setattr(S, 'fetch_page',
                        lambda m, c, p, **kw: _page(range(0, 3), total=3))
    s = _session()
    S.sync_account(s, 'lotteon', '브랜드위시', client=object())

    def boom(market, client, page_index, **kw):
        if page_index == 1:
            return _page(range(0, 1), total=3)
        raise RuntimeError('끊김')

    monkeypatch.setattr(S, 'fetch_page', boom)
    r = S.sync_account(s, 'lotteon', '브랜드위시', client=object())
    assert r['ok'] is False
    assert r['missing'] == 0
    assert s.query(MarketProduct).filter(
        MarketProduct.deleted_at.isnot(None)).count() == 0


def test_중간에_실패하면_건수도_건드리지_않는다(monkeypatch):
    """★ 절반만 센 숫자를 화면에 쓰면 '상품이 갑자기 줄었다'로 보인다."""
    monkeypatch.setattr(S, 'fetch_page',
                        lambda m, c, p, **kw: _page(range(0, 3), total=3))
    s = _session()
    S.sync_account(s, 'lotteon', '브랜드위시', client=object())
    assert s.query(MarketProductCount).filter_by(status='sale').one().count == 3

    def boom(market, client, page_index, **kw):
        raise RuntimeError('첫 페이지부터 끊김')

    monkeypatch.setattr(S, 'fetch_page', boom)
    S.sync_account(s, 'lotteon', '브랜드위시', client=object())
    assert s.query(MarketProductCount).filter_by(status='sale').one().count == 3


def test_페이지_상한을_넘지_않는다(monkeypatch):
    """마켓이 이상한 총건수를 주더라도 무한히 돌지 않는다."""
    monkeypatch.setattr(S, 'fetch_page',
                        lambda m, c, p, **kw: _page(range(0, 100), total=10 ** 9))
    s = _session()
    r = S.sync_account(s, 'lotteon', '브랜드위시', client=object(), max_pages=5)
    assert r['pages'] == 5
    assert r['truncated'] is True
