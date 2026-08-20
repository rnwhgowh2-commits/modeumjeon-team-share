# -*- coding: utf-8 -*-
"""카탈로그 테이블 3개 — 스키마 규약 고정.

무결성 규약이 깨지면 같은 마켓상품이 두 줄로 들어가 건수가 부풀거나(중복),
사라진 상품이 조용히 없어져 이력이 끊긴다.
"""
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from lemouton.catalog.models import (
    MarketProduct, MarketProductCount, MarketProductGroup,
)
from shared.db import Base


def _session():
    """메모리 SQLite — 라이브 DB 를 건드리지 않는다."""
    engine = sa.create_engine('sqlite://')
    Base.metadata.create_all(engine, tables=[
        MarketProduct.__table__, MarketProductCount.__table__,
        MarketProductGroup.__table__,
    ])
    return sessionmaker(bind=engine)()


def _row(**kw):
    base = dict(market='lotteon', account_key='브랜드위시',
                market_product_id='LO2727575855', name='아디다스골프 썬 햇',
                status='sale', raw_status='SALE')
    base.update(kw)
    return MarketProduct(**base)


def test_같은_마켓상품은_두_줄이_될_수_없다():
    """(마켓, 계정, 마켓상품번호)가 유일 — 중복이면 건수가 부푼다."""
    s = _session()
    s.add(_row()); s.commit()
    s.add(_row(name='이름만 다름'))
    try:
        s.commit()
        raise AssertionError('중복이 들어갔다 — 유일 제약이 없다')
    except sa.exc.IntegrityError:
        s.rollback()


def test_같은_상품번호라도_계정이_다르면_따로_들어간다():
    s = _session()
    s.add(_row(account_key='브랜드위시'))
    s.add(_row(account_key='브랜드박스'))
    s.commit()
    assert s.query(MarketProduct).count() == 2


def test_지운_상품은_지우지_않고_표시만_한다():
    """마켓에서 사라진 것도 이력이다 — 행을 없애지 않는다."""
    s = _session()
    r = _row(); s.add(r); s.commit()
    assert r.deleted_at is None
    assert hasattr(r, 'deleted_at')


def test_가격이_없으면_None_이지_0_이_아니다():
    """0 원으로 저장하면 '공짜 상품'으로 보인다 — 미상은 미상으로."""
    s = _session()
    r = _row(sale_price=None); s.add(r); s.commit()
    assert s.query(MarketProduct).one().sale_price is None


def test_묶음은_소싱처_모델_없이도_만들어진다():
    """★ ProductSet 과 다른 점 — 마켓에서 거꾸로 긁어온 상품은 소싱처 모델이 없다."""
    s = _session()
    g = MarketProductGroup(name='아디다스골프 썬 햇 모자')
    s.add(g); s.commit()
    assert g.id is not None
    assert g.model_code is None
    assert g.set_id is None


def test_상품을_묶음에_붙일_수_있다():
    s = _session()
    g = MarketProductGroup(name='아디다스골프 썬 햇 모자'); s.add(g); s.commit()
    r = _row(group_id=g.id); s.add(r); s.commit()
    assert s.query(MarketProduct).one().group_id == g.id


def test_건수_스냅샷은_마켓_계정_상태마다_한_줄():
    s = _session()
    s.add(MarketProductCount(market='lotteon', account_key='브랜드위시',
                             status='sale', count=44102, source='api'))
    s.commit()
    s.add(MarketProductCount(market='lotteon', account_key='브랜드위시',
                             status='sale', count=1, source='api'))
    try:
        s.commit()
        raise AssertionError('같은 칸이 두 줄 — 화면 숫자가 갈린다')
    except sa.exc.IntegrityError:
        s.rollback()


def test_건수는_어디서_왔는지_남긴다():
    """api(마켓에 직접 물음) vs cache(우리 캐시를 셈) — 신선도가 다르다."""
    s = _session()
    s.add(MarketProductCount(market='coupang', account_key='세소쿠팡',
                             status='sale', count=72, source='cache'))
    s.commit()
    assert s.query(MarketProductCount).one().source == 'cache'
