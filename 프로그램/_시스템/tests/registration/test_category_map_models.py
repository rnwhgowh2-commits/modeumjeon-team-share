"""M2 맵핑표·제한표 모델 테스트."""
import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shared.db import Base
from lemouton.registration.models import (
    SourceCategory, CategoryMapRow, BrandRestriction, ProductDraft)


def _mem():
    eng = create_engine('sqlite://')
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


def test_소싱처카테고리_행을_넣고_읽는다():
    s = _mem()
    s.add(SourceCategory(source_id='musinsa', path='신발>스니커즈>여성운동화',
                         leaf_name='여성운동화', depth=3,
                         first_seen_at=datetime.datetime(2026, 7, 23)))
    s.commit()
    assert s.query(SourceCategory).filter_by(source_id='musinsa').one().product_count == 0


def test_맵핑행은_소싱처경로x마켓_유니크이고_기본상태는_suggested():
    s = _mem()
    row = CategoryMapRow(source_id='musinsa', source_path='신발>스니커즈>여성운동화',
                        market='smartstore', market_cat_code='50000167',
                        market_cat_path='패션잡화>여성신발>운동화', method='name_sim',
                        confidence=0.9)
    s.add(row); s.commit()
    got = s.query(CategoryMapRow).one()
    assert got.status == 'suggested' and got.confirmed_at is None


def test_브랜드제한_행을_넣고_읽는다():
    s = _mem()
    s.add(BrandRestriction(brand='나이키', market='coupang',
                           category_prefix='', reason='지재권 신고 이력', active=True))
    s.commit()
    assert s.query(BrandRestriction).filter_by(market='coupang').one().active is True


def test_드래프트에_소싱처카테고리_컬럼이_있다():
    s = _mem()
    d = ProductDraft(name='테스트', sale_price=10000, source_site='musinsa',
                     source_category_path='신발>스니커즈>여성운동화')
    s.add(d); s.commit()
    assert s.query(ProductDraft).one().source_category_path.endswith('여성운동화')
