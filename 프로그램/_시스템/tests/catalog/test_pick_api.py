# -*- coding: utf-8 -*-
"""검색·담기 API 의 입력 검증 — 잘못된 입력을 조용히 넘기지 않는다.

★ 모르는 마켓을 넘겼는데 전체가 나오면 사장님은 「검색이 됐다」고 믿는다.
  ESM 이 정확히 그래서 사고가 났다(조건을 조용히 무시하고 전체 반환).
"""
import pytest

from webapp.routes.catalog.pick import parse_ids, parse_search_args


def test_검색어와_거르개를_읽는다():
    a = parse_search_args({'q': ' 아디다스 ', 'market': 'lotteon',
                           'status': 'sale', 'picked': 'false', 'limit': '30'})
    assert a['q'] == '아디다스'
    assert a['market'] == 'lotteon'
    assert a['status'] == 'sale'
    assert a['picked'] is False
    assert a['limit'] == 30


def test_picked_는_세_가지다():
    assert parse_search_args({'picked': 'true'})['picked'] is True
    assert parse_search_args({'picked': 'false'})['picked'] is False
    assert parse_search_args({})['picked'] is None


def test_모르는_마켓은_거절한다():
    with pytest.raises(ValueError, match='모르는 마켓'):
        parse_search_args({'market': '없는마켓'})


def test_모르는_상태는_거절한다():
    with pytest.raises(ValueError, match='모르는 상태'):
        parse_search_args({'status': '팔림'})


def test_아는_마켓_여섯은_다_통과한다():
    for m in ('smartstore', 'coupang', 'lotteon', 'eleven11',
              'auction', 'gmarket'):
        assert parse_search_args({'market': m})['market'] == m


def test_개수는_상한을_넘지_않는다():
    assert parse_search_args({'limit': '99999'})['limit'] == 200
    assert parse_search_args({'limit': '0'})['limit'] == 1
    assert parse_search_args({'limit': '가나다'})['limit'] == 50


def test_음수_쪽번호는_0_으로():
    assert parse_search_args({'offset': '-5'})['offset'] == 0


def test_상품번호_목록을_읽는다():
    assert parse_ids({'ids': [1, 2, 3]}) == [1, 2, 3]
    assert parse_ids({'ids': ['1', '2']}) == [1, 2]


def test_빈_목록은_거절한다():
    """0개를 붙이라고 하면 사장님이 뭔가 잘못 누른 것이다."""
    with pytest.raises(ValueError, match='고른 상품이 없습니다'):
        parse_ids({'ids': []})
    with pytest.raises(ValueError, match='고른 상품이 없습니다'):
        parse_ids({})


def test_숫자가_아니면_거절한다():
    with pytest.raises(ValueError, match='숫자'):
        parse_ids({'ids': ['가나다']})


def test_한_번에_너무_많이_붙이지_않는다():
    with pytest.raises(ValueError, match='한 번에'):
        parse_ids({'ids': list(range(300))})
