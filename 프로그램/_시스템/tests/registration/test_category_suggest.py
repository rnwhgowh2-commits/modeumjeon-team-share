"""이름 유사도 후보 — 정확일치 > 리프 부분일치 > 경로 토큰 겹침."""
from lemouton.registration import category_suggest as cs

_MARKET_LEAVES = [
    {'code': '1', 'name': '여성운동화', 'full_path': '패션잡화>여성신발>여성운동화'},
    {'code': '2', 'name': '운동화', 'full_path': '패션잡화>남성신발>운동화'},
    {'code': '3', 'name': '러닝화', 'full_path': '스포츠>운동화>러닝화'},
    {'code': '4', 'name': '노트북가방', 'full_path': '가방>노트북가방'},
]


def test_정확일치가_1등이고_부분일치가_그_다음이다():
    ranked = cs.rank_candidates('신발>스니커즈>여성운동화', _MARKET_LEAVES, top=3)
    assert [r['code'] for r in ranked][:2] == ['1', '2']
    assert ranked[0]['score'] > ranked[1]['score']


def test_리프명이_없으면_경로_토큰_겹침으로라도_찾는다():
    ranked = cs.rank_candidates('스포츠>운동화>트레일화', _MARKET_LEAVES, top=3)
    assert ranked and ranked[0]['code'] in ('3', '2')   # '운동화' 토큰 겹침


def test_아무것도_안_겹치면_빈_리스트다():
    assert cs.rank_candidates('식품>과일>사과', _MARKET_LEAVES, top=3) == []
