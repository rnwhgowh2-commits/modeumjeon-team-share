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


def test_build_paths_고아_부모면_HarvestError():
    """parent_code 가 있는데 배치에 그 코드가 없으면(고아) 리프 이름으로 조용히 붕괴하지 않고 HarvestError."""
    import pytest
    rows = [{'code': 'C2', 'name': '여성운동화', 'parent_code': 'C_MISSING'}]
    with pytest.raises(ch.HarvestError):
        ch.build_paths(rows)


def test_build_paths_순환_참조면_HarvestError():
    import pytest
    rows = [
        {'code': 'A', 'name': 'A', 'parent_code': 'B'},
        {'code': 'B', 'name': 'B', 'parent_code': 'A'},
    ]
    with pytest.raises(ch.HarvestError):
        ch.build_paths(rows)


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


def test_쿠팡_응답이_dict가_아니면_HarvestError():
    import pytest
    def fetch(code):
        return ['array', 'not', 'dict']
    with pytest.raises(ch.HarvestError):
        ch.harvest_coupang(fetch, sleep=lambda s: None)


def test_쿠팡_child에_코드_누락이면_HarvestError():
    import pytest
    tree = {
        '0': {'displayItemCategoryCode': 0, 'name': 'ROOT', 'status': 'ACTIVE',
              'child': [{'name': '코드없음', 'status': 'ACTIVE'}]},
    }
    with pytest.raises(ch.HarvestError):
        ch.harvest_coupang(lambda c: tree[c], sleep=lambda s: None)


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


def test_ESM_자기조상을_다시가리켜도_무한루프없이_종료하고_중복없다():
    """B 의 subCats 가 이미 방문한 A 를 다시 가리키는 순환 응답 — seen 가드로 재큐잉·행중복 없이 종료."""
    tree = {
        None: {'subCats': [{'catCode': 'A', 'catName': '패션', 'isLeaf': False}]},
        'A':  {'subCats': [{'catCode': 'B', 'catName': '운동화', 'isLeaf': False}]},
        'B':  {'subCats': [{'catCode': 'A', 'catName': '패션(순환)', 'isLeaf': False}]},
    }
    def fetch(code):
        return tree[code]
    rows = ch.harvest_esm_site(fetch, sleep=lambda s: None)
    codes = [r['code'] for r in rows]
    assert codes == ['A', 'B']
    assert len(codes) == len(set(codes))


def test_롯데온_표준카테고리를_페이징으로_전수수집한다():
    page1 = [{'std_cat_id': 'C1', 'std_cat_nm': '패션잡화', 'upr_std_cat_id': None, 'depth_no': 1}] * 1
    page1 += [{'std_cat_id': f'C1{i}', 'std_cat_nm': f'하위{i}', 'upr_std_cat_id': 'C1', 'depth_no': 2}
              for i in range(99)]
    page2 = [{'std_cat_id': 'C2', 'std_cat_nm': '여성운동화', 'upr_std_cat_id': 'C1', 'depth_no': 2}]
    pages = {0: page1, 100: page2}
    rows = ch.harvest_lotteon(lambda skip, limit: pages.get(skip, []), sleep=lambda s: None)
    assert len(rows) == 101
    last = [r for r in rows if r['code'] == 'C2'][0]
    assert last['full_path'] == '패션잡화>여성운동화'
    # 리프 판정 = 아무도 나를 부모로 안 가리킴
    assert last['is_leaf'] is True
    assert [r for r in rows if r['code'] == 'C1'][0]['is_leaf'] is False


def test_롯데온_upr_std_cat_id가_0이면_부모없음_루트로_처리():
    """parse_eleven11 과 같은 기준 — 센티넬 '0'/0/''/None 은 parent 없음."""
    page1 = [{'std_cat_id': 'C1', 'std_cat_nm': '패션잡화', 'upr_std_cat_id': '0', 'depth_no': 1}]
    rows = ch.harvest_lotteon(lambda skip, limit: page1 if skip == 0 else [], sleep=lambda s: None)
    root = [r for r in rows if r['code'] == 'C1'][0]
    assert root['parent_code'] is None
    assert root['full_path'] == '패션잡화'


def test_롯데온_응답이_배열이_아니면_HarvestError():
    import pytest
    with pytest.raises(ch.HarvestError):
        ch.harvest_lotteon(lambda skip, limit: {'not': 'a list'}, sleep=lambda s: None)


# ── 저장·diff 엔진 ───────────────────────────────────────
def _rows(*specs):
    return [{'code': c, 'name': n, 'parent_code': None, 'depth': 1,
             'is_leaf': True, 'full_path': n, 'raw': '{}'} for c, n in specs]


def test_save_snapshot_추가_갱신_삭제마킹_부활을_구분한다():
    s = _mem_session()
    t1 = datetime.datetime(2026, 7, 22, 10, 0, 0)
    r1 = ch.save_snapshot(s, 'eleven11', _rows(('1', '가'), ('2', '나')), now=t1)
    assert (r1['added'], r1['removed'], r1['total']) == (2, 0, 2)

    # 2차: '2' 사라지고 '3' 추가, '1' 이름 변경
    t2 = datetime.datetime(2026, 7, 22, 11, 0, 0)
    r2 = ch.save_snapshot(s, 'eleven11', _rows(('1', '가나'), ('3', '다')), now=t2)
    assert (r2['added'], r2['updated'], r2['removed']) == (1, 1, 1)
    gone = s.query(MarketCategory).filter_by(market='eleven11', code='2').one()
    assert gone.removed_at == t2                      # 지우지 않고 마킹

    # 3차: '2' 부활
    t3 = datetime.datetime(2026, 7, 22, 12, 0, 0)
    ch.save_snapshot(s, 'eleven11', _rows(('1', '가나'), ('2', '나'), ('3', '다')), now=t3)
    back = s.query(MarketCategory).filter_by(market='eleven11', code='2').one()
    assert back.removed_at is None


def test_save_snapshot_빈_rows는_거부한다():
    import pytest
    s = _mem_session()
    with pytest.raises(ch.HarvestError):
        ch.save_snapshot(s, 'eleven11', [], now=datetime.datetime(2026, 7, 22))
    # 이유: 수집 실패를 "전부 삭제됨" 으로 오기록하는 조용한 대참사 방지
