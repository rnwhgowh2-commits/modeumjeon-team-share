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


from lemouton.registration import category_harvest as ch

_XML_11ST = """<?xml version="1.0" encoding="euc-kr"?>
<ns2:categorys xmlns:ns2="http://skt.tmall.business.openapi.spring.service.client.domain/">
  <ns2:category><depth>1</depth><dispNm>패션잡화</dispNm><dispNo>1001</dispNo><parentDispNo>0</parentDispNo><leafYn>N</leafYn></ns2:category>
  <ns2:category><depth>2</depth><dispNm>운동화</dispNm><dispNo>1002</dispNo><parentDispNo>1001</parentDispNo><leafYn>N</leafYn></ns2:category>
  <ns2:category><depth>3</depth><dispNm>여성운동화</dispNm><dispNo>1003</dispNo><parentDispNo>1002</parentDispNo><leafYn>Y</leafYn></ns2:category>
</ns2:categorys>"""


def test_11번가_XML을_행으로_파싱하고_경로를_조립한다():
    rows = ch.parse_eleven11(_XML_11ST)
    assert len(rows) == 3
    leaf = [r for r in rows if r['code'] == '1003'][0]
    assert leaf['name'] == '여성운동화'
    assert leaf['parent_code'] == '1002'
    assert leaf['is_leaf'] is True
    assert leaf['full_path'] == '패션잡화>운동화>여성운동화'


def test_11번가_필수태그_누락이면_HarvestError():
    import pytest
    bad = '<category><dispNm>이름만</dispNm></category>'
    with pytest.raises(ch.HarvestError):
        ch.parse_eleven11(bad)
