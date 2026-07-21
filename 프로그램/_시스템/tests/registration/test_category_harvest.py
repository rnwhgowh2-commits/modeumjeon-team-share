# -*- coding: utf-8 -*-
"""market_categories 사전 — 모델·파서·저장 diff 테스트."""
import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shared.db import Base
from lemouton.registration.models import MarketCategory


def _mem_session():
    eng = create_engine('sqlite://')
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


def test_market_categories_테이블에_행을_넣고_읽는다():
    s = _mem_session()
    s.add(MarketCategory(
        market='eleven11', code='1011634', name='여성운동화',
        full_path='패션잡화>운동화>여성운동화', parent_code='1011630',
        depth=3, is_leaf=True, raw_json='{}',
        harvested_at=datetime.datetime(2026, 7, 22, 12, 0, 0)))
    s.commit()
    row = s.query(MarketCategory).filter_by(market='eleven11', code='1011634').one()
    assert row.is_leaf is True
    assert row.removed_at is None
