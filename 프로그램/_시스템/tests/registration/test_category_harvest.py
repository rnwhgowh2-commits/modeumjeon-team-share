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


def test_쿠팡_on_progress가_노드마다_누적_행수로_호출된다():
    """[2026-07-23 M1 실측 후속] 쿠팡은 수 시간 걸릴 수 있어 진행 콜백이 필요하다 —
    노드(큐에서 꺼낸 코드)를 하나 처리할 때마다 그 시점까지 쌓인 행 수로 호출된다."""
    tree = {
        '0':   {'displayItemCategoryCode': 0, 'name': 'ROOT', 'status': 'ACTIVE',
                'child': [{'displayItemCategoryCode': 10, 'name': '패션잡화', 'status': 'ACTIVE'}]},
        '10':  {'displayItemCategoryCode': 10, 'name': '패션잡화', 'status': 'ACTIVE',
                'child': [{'displayItemCategoryCode': 101, 'name': '여성운동화', 'status': 'ACTIVE'}]},
        '101': {'displayItemCategoryCode': 101, 'name': '여성운동화', 'status': 'ACTIVE', 'child': []},
    }
    calls = []
    rows = ch.harvest_coupang(lambda c: tree[c], sleep=lambda s: None, on_progress=calls.append)
    assert len(calls) == 3                # 노드 3개(루트 포함) 처리마다 한 번씩
    assert calls == [0, 1, 2]              # 루트는 행을 안 늘리므로 첫 콜은 0, 이후 누적
    assert calls[-1] == len(rows)          # 마지막 콜 값 = 최종 행 수


def test_쿠팡_on_progress_없이도_기존_동작_그대로():
    """콜백을 안 주면(기존 호출부) 예전과 동일하게 동작한다 — keyword-only 기본값 None."""
    tree = {
        '0':  {'displayItemCategoryCode': 0, 'name': 'ROOT', 'status': 'ACTIVE',
               'child': [{'displayItemCategoryCode': 10, 'name': '패션잡화', 'status': 'ACTIVE'}]},
        '10': {'displayItemCategoryCode': 10, 'name': '패션잡화', 'status': 'ACTIVE', 'child': []},
    }
    rows = ch.harvest_coupang(lambda c: tree[c], sleep=lambda s: None)
    assert [r['code'] for r in rows] == ['10']


def test_ESM_on_progress가_노드마다_누적_행수로_호출된다():
    tree = {
        None:        {'subCats': [{'catCode': '100000002', 'catName': '패션의류', 'isLeaf': False}]},
        '100000002': {'catCode': '100000002', 'catName': '패션의류', 'isLeaf': False,
                      'subCats': [{'catCode': '200001091', 'catName': '여성운동화', 'isLeaf': True}]},
    }
    calls = []
    rows = ch.harvest_esm_site(lambda code: tree[code], sleep=lambda s: None, on_progress=calls.append)
    assert calls == [1, 2]
    assert calls[-1] == len(rows)


def test_롯데온_on_progress가_페이지마다_누적_건수로_호출된다():
    page1 = [{'std_cat_id': 'C1', 'std_cat_nm': '패션잡화', 'upr_std_cat_id': None, 'depth_no': 1}] * 1
    page1 += [{'std_cat_id': f'C1{i}', 'std_cat_nm': f'하위{i}', 'upr_std_cat_id': 'C1', 'depth_no': 2}
              for i in range(99)]
    page2 = [{'std_cat_id': 'C2', 'std_cat_nm': '여성운동화', 'upr_std_cat_id': 'C1', 'depth_no': 2}]
    pages = {0: page1, 100: page2}
    calls = []
    rows = ch.harvest_lotteon(lambda skip, limit: pages.get(skip, []), sleep=lambda s: None,
                               on_progress=calls.append)
    assert calls == [100, 101]
    assert calls[-1] == len(rows)


def test_쿠팡_on_chunk이_50건마다_누적_rows로_호출된다():
    """[2026-07-23 실측 사고 대응 #3] 200 문턱은 실측 3회차(124건에서 정지)에 한 번도 못
    넘겨 저장 0건이었다 — CHUNK_SIZE 를 50 으로 낮췄다. 쿠팡은 노드당 1콜 BFS 라 완주까지
    수 시간 걸리는데, 종전엔 전량을 메모리에 쌓았다가 맨 마지막에만 저장해 중간에 스레드가
    죽으면 전부 유실됐다. 누적 행 수가 50건 단위로 늘 때마다 그 시점까지의 rows 를 통째로
    넘겨 on_chunk 를 호출한다 — 콜백이 저장을 담당한다."""
    assert ch.CHUNK_SIZE == 50
    children = [{'displayItemCategoryCode': i, 'name': f'cat{i}', 'status': 'ACTIVE'}
                for i in range(1, 56)]
    tree = {'0': {'displayItemCategoryCode': 0, 'name': 'ROOT', 'status': 'ACTIVE',
                  'child': children}}
    for i in range(1, 56):
        tree[str(i)] = {'displayItemCategoryCode': i, 'name': f'cat{i}', 'status': 'ACTIVE',
                         'child': []}
    chunks = []
    rows = ch.harvest_coupang(lambda c: tree[c], sleep=lambda s: None, on_chunk=chunks.append)
    assert len(rows) == 55
    assert len(chunks) == 1                 # 50 문턱 1번만 넘음(55 < 100)
    assert len(chunks[0]) == 50             # 그 시점까지 누적된 행 수
    assert chunks[0] == rows[:50]


def test_ESM_on_chunk이_50건마다_누적_rows로_호출된다():
    """harvest_coupang 과 동일 기준(CHUNK_SIZE=50)이 ESM 에도 적용된다."""
    assert ch.CHUNK_SIZE == 50
    tree = {None: {'subCats': [{'catCode': f'C{i}', 'catName': f'cat{i}', 'isLeaf': True}
                                for i in range(1, 56)]}}
    chunks = []
    rows = ch.harvest_esm_site(lambda code: tree[code], sleep=lambda s: None, on_chunk=chunks.append)
    assert len(rows) == 55
    assert len(chunks) == 1
    assert len(chunks[0]) == 50
    assert chunks[0] == rows[:50]


def test_쿠팡_on_chunk_없이도_기존_동작_그대로():
    """콜백을 안 주면(기존 호출부) 예전과 동일하게 동작한다 — keyword-only 기본값 None."""
    tree = {
        '0':  {'displayItemCategoryCode': 0, 'name': 'ROOT', 'status': 'ACTIVE',
               'child': [{'displayItemCategoryCode': 10, 'name': '패션잡화', 'status': 'ACTIVE'}]},
        '10': {'displayItemCategoryCode': 10, 'name': '패션잡화', 'status': 'ACTIVE', 'child': []},
    }
    rows = ch.harvest_coupang(lambda c: tree[c], sleep=lambda s: None)
    assert [r['code'] for r in rows] == ['10']


def _coupang_known_fixture():
    """이미 확보된 가지: 10(비-리프, child_count=2 와 저장된 children 2개가 정확히 일치)
    →101,102(리프). 20 은 미탐색(known 밖)."""
    return {
        '10': {'is_leaf': False, 'name': '패션잡화', 'raw': '{}',
               'child_count': 2, 'children': ['101', '102']},
        '101': {'is_leaf': True, 'name': '여성운동화', 'raw': '{}',
                'child_count': 0, 'children': []},
        '102': {'is_leaf': True, 'name': '남성운동화', 'raw': '{}',
                'child_count': 0, 'children': []},
    }


def test_쿠팡_known에_있는_코드는_fetch되지_않는다():
    """[2026-07-23 이어받기] 이미 DB 에 확보된(리프로 확정됐거나 자식까지 저장된) 노드는
    fetch 를 건너뛴다 — 호출 목록에 그 코드가 없다는 것으로 증명한다."""
    tree = {
        '0': {'name': 'ROOT', 'child': [
            {'displayItemCategoryCode': 10, 'status': 'ACTIVE'},
            {'displayItemCategoryCode': 20, 'status': 'ACTIVE'},
        ]},
        '20': {'name': '스포츠', 'child': []},
        # '10'/'101'/'102' 는 일부러 안 넣는다 — fetch 되면 KeyError 로 즉시 드러난다.
    }
    calls = []
    def fetch(code):
        calls.append(code)
        return tree[code]
    rows = ch.harvest_coupang(fetch, sleep=lambda s: None, known=_coupang_known_fixture())
    assert calls == ['0', '20']              # 루트 + 미탐색 프런티어만 fetch
    assert '10' not in calls and '101' not in calls and '102' not in calls


def test_쿠팡_known의_자식이_큐에_들어가_미탐색_가지만_새로_fetch된다():
    """known 노드 자체는 skip 되지만 그 children 은 큐에 들어가 행으로 재구성되고,
    known 밖의 진짜 미탐색 가지(20)는 정상 fetch 로 새로 발견된다."""
    tree = {
        '0': {'name': 'ROOT', 'child': [
            {'displayItemCategoryCode': 10, 'status': 'ACTIVE'},
            {'displayItemCategoryCode': 20, 'status': 'ACTIVE'},
        ]},
        '20': {'name': '스포츠', 'child': []},
    }
    rows = ch.harvest_coupang(lambda c: tree[c], sleep=lambda s: None,
                               known=_coupang_known_fixture())
    by_code = {r['code']: r for r in rows}
    assert set(by_code) == {'10', '101', '102', '20'}
    assert by_code['10']['is_leaf'] is False
    assert by_code['10']['full_path'] == '패션잡화'
    assert by_code['101']['full_path'] == '패션잡화>여성운동화'
    assert by_code['102']['full_path'] == '패션잡화>남성운동화'
    assert by_code['20']['is_leaf'] is True
    assert by_code['20']['full_path'] == '스포츠'


def test_쿠팡_known에_있어도_비리프인데_children이_비어있으면_안전하게_다시_fetch한다():
    """자식 존재는 확인됐지만(is_leaf=False) 죽어서 하나도 저장 못 한 경계 케이스 —
    children 이 비어 있으면 추측하지 않고 평소처럼 fetch 한다(과소수집 방지)."""
    tree = {
        '0': {'name': 'ROOT', 'child': [{'displayItemCategoryCode': 10, 'status': 'ACTIVE'}]},
        '10': {'name': '패션잡화', 'child': [{'displayItemCategoryCode': 101, 'status': 'ACTIVE'}]},
        '101': {'name': '여성운동화', 'child': []},
    }
    calls = []
    def fetch(code):
        calls.append(code)
        return tree[code]
    known = {'10': {'is_leaf': False, 'name': '패션잡화', 'raw': '{}', 'children': []}}
    rows = ch.harvest_coupang(fetch, sleep=lambda s: None, known=known)
    assert calls == ['0', '10', '101']       # '10' 도 다시 fetch 됨 — children 을 못 믿음
    assert {r['code'] for r in rows} == {'10', '101'}


def test_쿠팡_known이_None이면_기존_동작과_동일():
    """known 기본값 None — 이 인자를 아예 모르던 기존 호출부와 100% 동일하게 동작한다."""
    tree = {
        '0': {'displayItemCategoryCode': 0, 'name': 'ROOT', 'status': 'ACTIVE',
              'child': [{'displayItemCategoryCode': 10, 'name': '패션잡화', 'status': 'ACTIVE'}]},
        '10': {'displayItemCategoryCode': 10, 'name': '패션잡화', 'status': 'ACTIVE',
               'child': [{'displayItemCategoryCode': 101, 'name': '여성운동화', 'status': 'ACTIVE'}]},
        '101': {'displayItemCategoryCode': 101, 'name': '여성운동화', 'status': 'ACTIVE', 'child': []},
    }
    calls = []
    def fetch(code):
        calls.append(code)
        return tree[code]
    rows = ch.harvest_coupang(fetch, sleep=lambda s: None)
    assert calls == ['0', '10', '101']
    assert [r['code'] for r in rows] == ['10', '101']


def test_쿠팡_known_children이_child_count보다_적으면_안전하게_재fetch한다():
    """[2026-07-23 자식누락 차단] 실제 자식이 A,B,C(child_count=3)인데 A 만 저장된 채
    죽은 경우 — children=['101'] 이 '비어있지 않음'이라 예전엔 그대로 skip 해 102,103 을
    영원히 놓쳤다. child_count 와 개수가 안 맞으면 재fetch 해서 온전히 다시 확보한다."""
    tree = {
        '0': {'name': 'ROOT', 'child': [{'displayItemCategoryCode': 10, 'status': 'ACTIVE'}]},
        '10': {'name': '패션잡화', 'child': [
            {'displayItemCategoryCode': 101, 'name': '여성운동화', 'status': 'ACTIVE'},
            {'displayItemCategoryCode': 102, 'name': '남성운동화', 'status': 'ACTIVE'},
            {'displayItemCategoryCode': 103, 'name': '아동운동화', 'status': 'ACTIVE'},
        ]},
        '101': {'name': '여성운동화', 'child': []},
        '102': {'name': '남성운동화', 'child': []},
        '103': {'name': '아동운동화', 'child': []},
    }
    calls = []
    def fetch(code):
        calls.append(code)
        return tree[code]
    # DB 에 '10'(child_count=3 이었어야 함) 의 자식이 '101' 하나만 저장된 채 죽은 상태를 재현.
    known = {'10': {'is_leaf': False, 'name': '패션잡화', 'raw': '{}',
                     'child_count': 3, 'children': ['101']}}
    rows = ch.harvest_coupang(fetch, sleep=lambda s: None, known=known)
    assert '10' in calls                     # 개수가 안 맞아 '10' 재fetch 됨
    assert {r['code'] for r in rows} == {'10', '101', '102', '103'}   # 102·103 유실 없이 전부 확보


def test_쿠팡_known_children이_child_count와_정확히_일치하면_건너뛴다():
    """child_count 와 저장된 children 개수가 정확히 같으면 "완전히 확보했다"고 믿고 skip.
    (기존 _coupang_known_fixture 재사용 — '10' 뿐 아니라 그 자식 '101'/'102' 도 known 에
    리프로 등록돼 있어 큐에 다시 들어가도 fetch 없이 skip 된다.)"""
    tree = {
        '0': {'name': 'ROOT', 'child': [{'displayItemCategoryCode': 10, 'status': 'ACTIVE'}]},
        # '10'/'101'/'102' 는 일부러 안 넣는다 — fetch 되면 KeyError 로 즉시 드러난다.
    }
    calls = []
    def fetch(code):
        calls.append(code)
        return tree[code]
    rows = ch.harvest_coupang(fetch, sleep=lambda s: None, known=_coupang_known_fixture())
    assert calls == ['0']                     # '10'/'101'/'102' 전부 skip — fetch 안 됨
    assert {r['code'] for r in rows} == {'10', '101', '102'}


def test_쿠팡_known_child_count가_NULL이면_옛데이터로_보고_재fetch한다():
    """child_count 컬럼 추가 전에 저장된 옛 행은 NULL — "완전히 확보했는지" 판정 근거가
    없으므로 children 이 채워져 있어도 안전하게 재fetch 한다."""
    tree = {
        '0': {'name': 'ROOT', 'child': [{'displayItemCategoryCode': 10, 'status': 'ACTIVE'}]},
        '10': {'name': '패션잡화', 'child': [
            {'displayItemCategoryCode': 101, 'name': '여성운동화', 'status': 'ACTIVE'},
        ]},
        '101': {'name': '여성운동화', 'child': []},
    }
    calls = []
    def fetch(code):
        calls.append(code)
        return tree[code]
    known = {'10': {'is_leaf': False, 'name': '패션잡화', 'raw': '{}',
                     'child_count': None, 'children': ['101']}}
    rows = ch.harvest_coupang(fetch, sleep=lambda s: None, known=known)
    assert '10' in calls                      # child_count NULL → 재fetch
    assert {r['code'] for r in rows} == {'10', '101'}


def test_쿠팡_known_리프는_child_count_무관하게_건너뛴다():
    """is_leaf=True 면 child_count 유무와 상관없이 그대로 skip(예전과 동일 — 리프는 항상 안전)."""
    tree = {
        '0': {'name': 'ROOT', 'child': [{'displayItemCategoryCode': 10, 'status': 'ACTIVE'}]},
        # '10' 은 일부러 안 넣는다 — fetch 되면 KeyError.
    }
    calls = []
    def fetch(code):
        calls.append(code)
        return tree[code]
    known = {'10': {'is_leaf': True, 'name': '여성운동화', 'raw': '{}',
                     'child_count': None, 'children': []}}
    rows = ch.harvest_coupang(fetch, sleep=lambda s: None, known=known)
    assert calls == ['0']
    assert [r['code'] for r in rows] == ['10']
    assert rows[0]['is_leaf'] is True


def test_쿠팡_행에_child_count가_담긴다():
    """harvest_coupang 이 만드는 각 행에 그 노드 자신의 자식 수가 담긴다(리프는 0)."""
    tree = {
        '0': {'name': 'ROOT', 'child': [{'displayItemCategoryCode': 10, 'status': 'ACTIVE'}]},
        '10': {'name': '패션잡화', 'child': [
            {'displayItemCategoryCode': 101, 'name': '여성운동화', 'status': 'ACTIVE'},
            {'displayItemCategoryCode': 102, 'name': '남성운동화', 'status': 'ACTIVE'},
        ]},
        '101': {'name': '여성운동화', 'child': []},
        '102': {'name': '남성운동화', 'child': []},
    }
    rows = ch.harvest_coupang(lambda c: tree[c], sleep=lambda s: None)
    by_code = {r['code']: r for r in rows}
    assert by_code['10']['child_count'] == 2
    assert by_code['101']['child_count'] == 0
    assert by_code['102']['child_count'] == 0


# ── [2026-07-23 사고 #5] 콜 예산(max_calls)으로 "한 번에 조금씩, 확실히 전진" ────────
def _wide_tree(n):
    """루트 아래 n개의 리프가 달린 트리 — 콜 수를 세기 좋다(콜 = 1 + n)."""
    tree = {'0': {'name': 'ROOT', 'child': [
        {'displayItemCategoryCode': i, 'status': 'ACTIVE'} for i in range(1, n + 1)]}}
    for i in range(1, n + 1):
        tree[str(i)] = {'name': f'cat{i}', 'child': []}
    return tree


def test_쿠팡_max_calls에_도달하면_큐가_남아도_예외없이_정상반환한다():
    """실측: 서버가 백그라운드 스레드를 2~3분(200~400콜)밖에 못 살린다. 죽어서 끝나면
    최종 저장·마무리가 통째로 날아가므로, 정해진 콜 수만 쓰고 **스스로 정상 종료**한다."""
    tree = _wide_tree(20)
    calls = []
    def fetch(code):
        calls.append(code)
        return tree[code]
    rows = ch.harvest_coupang(fetch, sleep=lambda s: None, max_calls=5)
    assert len(calls) == 5                    # 예산을 정확히 지킨다(루트 1 + 리프 4)
    assert len(rows) == 4                     # 루트는 행이 없으므로 4건
    assert all(r['code'] in {'1', '2', '3', '4'} for r in rows)


def test_쿠팡_max_calls로_끝나면_progress_state에_미완이_기록된다():
    """반환값 계약(행 리스트)은 그대로 두고, 미완 여부는 progress_state dict 로 통지한다 —
    호출부는 이 값으로 `save_snapshot(partial=True)` 를 선택해야 한다(대참사 방지)."""
    tree = _wide_tree(20)
    state = {}
    ch.harvest_coupang(lambda c: tree[c], sleep=lambda s: None, max_calls=5,
                       progress_state=state)
    assert state['incomplete'] is True
    assert state['calls'] == 5
    assert state['pending'] > 0               # 아직 안 훑은 노드가 남아 있다


def test_쿠팡_완주하면_progress_state_incomplete는_False():
    """예산 안에서 큐를 다 비웠으면 완주 — 이때만 호출부가 partial=False 로 저장해도 안전하다."""
    tree = _wide_tree(3)
    state = {}
    rows = ch.harvest_coupang(lambda c: tree[c], sleep=lambda s: None, max_calls=50,
                              progress_state=state)
    assert state['incomplete'] is False
    assert state['pending'] == 0
    assert state['calls'] == 4                # 루트 1 + 리프 3
    assert len(rows) == 3


def test_쿠팡_max_calls_None이면_기존_동작과_100퍼센트_동일():
    """기본값 None = 무제한 — 이 인자를 모르던 기존 호출부·테스트와 동작이 같다."""
    tree = _wide_tree(7)
    calls = []
    rows = ch.harvest_coupang(lambda c: (calls.append(c), tree[c])[1], sleep=lambda s: None)
    assert len(calls) == 8 and len(rows) == 7


def test_쿠팡_예산은_skip노드에는_안_쓰인다():
    """known 으로 확정된 노드는 fetch 를 안 하므로 예산을 깎지 않는다 — 이어받기 실행이
    이미 확보한 가지 때문에 예산을 낭비하지 않는다는 뜻."""
    tree = {
        '0': {'name': 'ROOT', 'child': [
            {'displayItemCategoryCode': 10, 'status': 'ACTIVE'},
            {'displayItemCategoryCode': 20, 'status': 'ACTIVE'},
        ]},
        '20': {'name': '스포츠', 'child': []},
    }
    state = {}
    calls = []
    def fetch(code):
        calls.append(code)
        return tree[code]
    rows = ch.harvest_coupang(fetch, sleep=lambda s: None, known=_coupang_known_fixture(),
                              max_calls=2, progress_state=state)
    assert calls == ['0', '20']               # skip 3개('10','101','102')는 예산을 안 씀
    assert state['incomplete'] is False        # 예산 2를 다 썼지만 큐도 같이 비었다 = 완주
    assert {r['code'] for r in rows} == {'10', '101', '102', '20'}


# ── [2026-07-23 사고 #5] 큐 우선순위 — 미탐색(new) 을 재fetch(refetch) 보다 먼저 ─────
def test_쿠팡_미탐색_가지를_재fetch_대상보다_먼저_판다():
    """이어받기 정체의 원인: 예전 단일 FIFO 는 「이미 확보한 가지의 재fetch」로 예산을 다
    쓰고 미탐색 가지에는 도달도 못 한 채 죽었다(저장 4,200건 정체). 이제 known 밖의 진짜
    미탐색 노드(new)를 child_count 불일치 재확인(refetch)보다 먼저 처리한다."""
    tree = {
        '0': {'name': 'ROOT', 'child': [
            # 큐에 들어가는 순서는 refetch 대상이 먼저지만, 처리 순서는 new 가 먼저여야 한다.
            {'displayItemCategoryCode': 10, 'status': 'ACTIVE'},   # known·child_count 불일치 → refetch
            {'displayItemCategoryCode': 20, 'status': 'ACTIVE'},   # known 밖 → new
        ]},
        '10': {'name': '패션잡화', 'child': []},
        '20': {'name': '스포츠', 'child': []},
    }
    known = {'10': {'is_leaf': False, 'name': '패션잡화', 'raw': '{}',
                    'child_count': 3, 'children': ['101']}}
    calls = []
    def fetch(code):
        calls.append(code)
        return tree[code]
    ch.harvest_coupang(fetch, sleep=lambda s: None, known=known)
    assert calls == ['0', '20', '10']          # 미탐색 '20' 이 재fetch '10' 보다 먼저


def test_쿠팡_예산이_적으면_미탐색_가지에_먼저_쓰인다():
    """위 우선순위의 실질 효과 — 예산이 1콜뿐이면 그 1콜은 재fetch 가 아니라 미탐색에 쓴다."""
    tree = {
        '0': {'name': 'ROOT', 'child': [
            {'displayItemCategoryCode': 10, 'status': 'ACTIVE'},
            {'displayItemCategoryCode': 20, 'status': 'ACTIVE'},
        ]},
        '20': {'name': '스포츠', 'child': []},
        # '10' 은 일부러 안 넣는다 — 재fetch 되면 KeyError 로 즉시 드러난다.
    }
    known = {'10': {'is_leaf': False, 'name': '패션잡화', 'raw': '{}',
                    'child_count': 3, 'children': ['101']}}
    state = {}
    rows = ch.harvest_coupang(lambda c: tree[c], sleep=lambda s: None, known=known,
                              max_calls=2, progress_state=state)
    assert state['incomplete'] is True
    assert {r['code'] for r in rows} == {'20'}   # 예산은 미탐색 가지에 쓰였다


def test_쿠팡_큐순서를_바꿔도_완주_결과는_동일하다():
    """BFS 방문 순서만 바뀌고 최종 방문 집합·행 내용은 같다(우선순위 도입의 무해성 고정)."""
    tree = {
        '0': {'name': 'ROOT', 'child': [
            {'displayItemCategoryCode': 10, 'status': 'ACTIVE'},
            {'displayItemCategoryCode': 20, 'status': 'ACTIVE'},
        ]},
        '10': {'name': '패션잡화', 'child': [
            {'displayItemCategoryCode': 101, 'status': 'ACTIVE'},
            {'displayItemCategoryCode': 102, 'status': 'ACTIVE'},
        ]},
        '101': {'name': '여성운동화', 'child': []},
        '102': {'name': '남성운동화', 'child': []},
        '20': {'name': '스포츠', 'child': [{'displayItemCategoryCode': 201, 'status': 'ACTIVE'}]},
        '201': {'name': '등산화', 'child': []},
    }
    known = {'10': {'is_leaf': False, 'name': '패션잡화', 'raw': '{}',
                    'child_count': 9, 'children': ['101']},          # 불일치 → refetch
             '102': {'is_leaf': True, 'name': '남성운동화', 'raw': '{}',
                     'child_count': 0, 'children': []}}              # 확정 → skip
    plain = ch.harvest_coupang(lambda c: tree[c], sleep=lambda s: None)
    resumed = ch.harvest_coupang(lambda c: tree[c], sleep=lambda s: None, known=known)
    key = lambda rs: sorted((r['code'], r['full_path'], r['is_leaf'], r['child_count'],
                             r['parent_code']) for r in rs)
    assert key(plain) == key(resumed)


def test_쿠팡_on_chunk은_새로_fetch한_행만_델타로_보낸다():
    """known 재구성 행은 DB 에 이미 같은 내용이 있어 다시 쓸 이유가 없다. 예전엔 누적 rows
    를 통째로 매번 넘겨, 이어받기 실행이 같은 수천 행을 수십 번 다시 쓰느라(O(n²)) 정작
    새 fetch 에 쓸 시간을 다 잡아먹었다 — 이제 새로 fetch 한 행만 50건 델타로 넘긴다."""
    n = 60
    tree = {'0': {'name': 'ROOT', 'child': (
        [{'displayItemCategoryCode': f'k{i}', 'status': 'ACTIVE'} for i in range(1, 31)]
        + [{'displayItemCategoryCode': f'n{i}', 'status': 'ACTIVE'} for i in range(1, n + 1)])}}
    for i in range(1, n + 1):
        tree[f'n{i}'] = {'name': f'new{i}', 'child': []}
    known = {f'k{i}': {'is_leaf': True, 'name': f'kn{i}', 'raw': '{}',
                       'child_count': 0, 'children': []} for i in range(1, 31)}
    chunks = []
    ch.harvest_coupang(lambda c: tree[c], sleep=lambda s: None, known=known,
                       on_chunk=chunks.append)
    assert len(chunks) == 1                        # 새 행 60개 → 50 문턱 1회
    assert len(chunks[0]) == 50                    # 델타(누적 아님)
    assert all(r['code'].startswith('n') for r in chunks[0])   # known 재구성 행은 안 실린다


def test_save_snapshot이_child_count를_저장한다():
    s = _mem_session()
    rows = [{'code': '10', 'name': '패션잡화', 'parent_code': None, 'depth': 1,
             'is_leaf': False, 'full_path': '패션잡화', 'raw': '{}', 'child_count': 2}]
    ch.save_snapshot(s, 'coupang', rows, now=datetime.datetime(2026, 7, 23))
    row = s.query(MarketCategory).filter_by(market='coupang', code='10').one()
    assert row.child_count == 2


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


def test_save_snapshot_배치_내_중복코드는_HarvestError():
    """같은 rows 안에 같은 code 가 2번 오면 커밋 시점 IntegrityError 대신 여기서 표면화."""
    import pytest
    s = _mem_session()
    dup = _rows(('1', '가'), ('1', '가또'))
    with pytest.raises(ch.HarvestError):
        ch.save_snapshot(s, 'eleven11', dup, now=datetime.datetime(2026, 7, 22))


def test_save_snapshot_partial은_빈_rows를_거부하지_않는다():
    """[2026-07-23 체크포인트] 진행 중 콜백은 아직 아무 청크도 안 찼을 수 있다 — partial=True
    는 빈 rows 를 HarvestError 로 거부하지 않는다(전량 저장 partial=False 는 계속 거부)."""
    s = _mem_session()
    r = ch.save_snapshot(s, 'coupang', [], now=datetime.datetime(2026, 7, 23), partial=True)
    assert r == {'added': 0, 'updated': 0, 'removed': 0, 'total': 0}


def test_save_snapshot_partial은_사라진_코드를_removed_마킹하지_않는다():
    """[2026-07-23 체크포인트] 부분 수집은 '지금까지 수집한 일부'일 뿐이라 rows 에 없는
    기존 코드를 '없어졌다'고 판단할 근거가 없다 — partial=True 는 removed_at 을 안 건드린다.
    이후 partial=False 최종 저장에서만 진짜 사라진 코드가 removed 마킹된다."""
    s = _mem_session()
    t1 = datetime.datetime(2026, 7, 23, 10, 0, 0)
    ch.save_snapshot(s, 'coupang', _rows(('1', '가'), ('2', '나')), now=t1)

    # 재수집 1차 청크: '1' 만 다시 보임 — '2' 는 이 청크에 없지만 부분 수집이라 지우면 안 됨
    t2 = datetime.datetime(2026, 7, 23, 10, 5, 0)
    r = ch.save_snapshot(s, 'coupang', _rows(('1', '가')), now=t2, partial=True)
    assert r['removed'] == 0
    row1 = s.query(MarketCategory).filter_by(market='coupang', code='1').one()
    row2 = s.query(MarketCategory).filter_by(market='coupang', code='2').one()
    assert row1.removed_at is None
    assert row2.removed_at is None                    # 부분 수집이라 안 건드림


def test_save_snapshot_depth0을_1로_조용히_치환하지_않는다():
    """쿠팡 루트처럼 depth=0 이 뜻있는 값일 수 있다 — `or 1` 폴백은 0 을 지운다(리뷰 지적)."""
    s = _mem_session()
    rows = [{'code': 'R', 'name': '루트', 'parent_code': None, 'depth': 0,
             'is_leaf': False, 'full_path': '루트', 'raw': '{}'}]
    ch.save_snapshot(s, 'coupang', rows, now=datetime.datetime(2026, 7, 22))
    row = s.query(MarketCategory).filter_by(market='coupang', code='R').one()
    assert row.depth == 0
