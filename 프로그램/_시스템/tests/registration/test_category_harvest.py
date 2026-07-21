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


def test_스마트스토어_평면리스트를_행으로_파싱한다():
    payload = [
        {'id': 50000000, 'name': '패션잡화', 'wholeCategoryName': '패션잡화', 'last': False},
        {'id': 50000167, 'name': '여성운동화', 'wholeCategoryName': '패션잡화>운동화>여성운동화', 'last': True},
    ]
    rows = ch.parse_smartstore(payload)
    leaf = [r for r in rows if r['code'] == '50000167'][0]
    assert leaf['is_leaf'] is True
    assert leaf['full_path'] == '패션잡화>운동화>여성운동화'
    assert leaf['depth'] == 3


def test_스마트스토어_빈_응답이면_HarvestError():
    import pytest
    with pytest.raises(ch.HarvestError):
        ch.parse_smartstore([])


def test_쿠팡_BFS가_전_노드를_수집하고_자식없음을_리프로_판정한다():
    tree = {
        '0':   {'displayItemCategoryCode': 0, 'name': 'ROOT', 'status': 'ACTIVE',
                'child': [{'displayItemCategoryCode': 10, 'name': '패션잡화', 'status': 'ACTIVE'}]},
        '10':  {'displayItemCategoryCode': 10, 'name': '패션잡화', 'status': 'ACTIVE',
                'child': [{'displayItemCategoryCode': 101, 'name': '여성운동화', 'status': 'ACTIVE'}]},
        '101': {'displayItemCategoryCode': 101, 'name': '여성운동화', 'status': 'ACTIVE', 'child': []},
    }
    calls = []
    def fetch(code):
        calls.append(code)
        return tree[code]
    rows = ch.harvest_coupang(fetch, sleep=lambda s: None)
    assert [r['code'] for r in rows] == ['10', '101']       # 루트(0)는 행 제외
    leaf = rows[-1]
    assert leaf['is_leaf'] is True and leaf['full_path'] == '패션잡화>여성운동화'
    assert calls == ['0', '10', '101']                       # 전 노드 1회씩


def test_쿠팡_DISABLED_노드는_행에서_제외하고_하위도_안내려간다():
    tree = {
        '0':  {'displayItemCategoryCode': 0, 'name': 'ROOT', 'status': 'ACTIVE',
               'child': [{'displayItemCategoryCode': 10, 'name': '중단분류', 'status': 'DISABLED'}]},
    }
    rows = ch.harvest_coupang(lambda c: tree[c], sleep=lambda s: None)
    assert rows == []


def test_ESM_site_cats를_재귀수집하고_isLeaf를_그대로_쓴다():
    tree = {
        None:        {'subCats': [{'catCode': '100000002', 'catName': '패션의류', 'isLeaf': False}]},
        '100000002': {'catCode': '100000002', 'catName': '패션의류', 'isLeaf': False,
                      'subCats': [{'catCode': '200001091', 'catName': '여성운동화', 'isLeaf': True}]},
    }
    def fetch(code):
        return tree[code]
    rows = ch.harvest_esm_site(fetch, sleep=lambda s: None)
    assert [r['code'] for r in rows] == ['100000002', '200001091']
    assert rows[1]['is_leaf'] is True
    assert rows[1]['full_path'] == '패션의류>여성운동화'
    # 리프는 재호출하지 않는다 (isLeaf 를 믿는다 — 콜 수 절약)


def test_ESM_resultCode_실패응답이면_HarvestError():
    import pytest
    def fetch(code):
        return {'resultCode': 9001, 'message': '인증 오류'}
    with pytest.raises(ch.HarvestError):
        ch.harvest_esm_site(fetch, sleep=lambda s: None)
