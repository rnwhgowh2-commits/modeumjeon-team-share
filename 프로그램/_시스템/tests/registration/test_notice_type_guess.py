# -*- coding: utf-8 -*-
"""notice_type_guess.guess_notice_type — 카테고리 텍스트 → SHOES|BAG|None(WEAR 유지).

버그 배경: send/as_draft.py::upsert() 가 notice_type 을 전혀 채우지 않아 신발·가방도
전부 「의류」로 나갔다(policy/fixed_sends.py COMMON_DEFAULTS「고시 유형」). 이 시험은
그 자리를 메우는 판정 함수가 (1) 실제 신발·가방 카테고리를 잡고 (2) category_suggest.py
가 이미 겪은 부분일치 오탐 함정('가방' ⊂ '가방걸이' 류)에 다시 걸리지 않는가를 본다.
"""
import pytest

from lemouton.registration.notice_type_guess import guess_notice_type


# ── 신발 ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize('path', [
    '신발>스니커즈>여성운동화',                  # models.py:121 comment 의 예시 그대로
    '패션잡화>여성신발>스니커즈',                 # 성별 합성어가 앞마디에
    '남성신발',                                  # 성별 합성어 단독
    '신발',                                      # 대분류 단독
    '슈즈',
    '워커',
    '남성구두',
    '하이힐',
    '슬리퍼>여름신발',
    '유아동신발>운동화',                          # 연령 수식어
    '남녀공용>슬리퍼',
])
def test_신발_카테고리는_SHOES(path):
    assert guess_notice_type(path) == 'SHOES'


# ── 가방 ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize('path', [
    '가방>숄더백>여성숄더백',
    '여성가방>크로스백',
    '남성가방',
    '가방',
    '백팩',
    '여행가방',
    '서류가방',
    '클러치>이브닝클러치',
    '에코백',
])
def test_가방_카테고리는_BAG(path):
    assert guess_notice_type(path) == 'BAG'


# ── 오탐 방지(짧은 한글 토큰 부분일치 함정) ────────────────────────────────
#   category_suggest.py 가 이미 겪은 '가방' ⊂ '가방걸이', '반지' ⊂ '반지갑' 과
#   같은 종류의 함정을 신발·가방 판정에서도 다시 밟지 않는지 확인한다.

@pytest.mark.parametrize('path', [
    '생활잡화>가방걸이',        # '가방' 이 '가방걸이' 에 우연히 포함
    '수납가구>신발장',          # '신발' 이 '신발장' 에 우연히 포함
    '잡화>구두쇠세일',          # '구두' 가 '구두쇠' 에 우연히 포함
])
def test_부분일치_오탐은_판정하지_않는다(path):
    assert guess_notice_type(path) is None


# ── 일반 의류 → 판정 안 함(WEAR 유지) ──────────────────────────────────────

@pytest.mark.parametrize('path', [
    '여성의류>원피스',
    '남성의류>셔츠',
    '아우터>코트',
    '',
    None,
    '   ',
])
def test_일반_카테고리는_판정하지_않는다(path):
    assert guess_notice_type(path) is None


# ── 신발·가방 신호가 동시에 있으면 단정하지 않는다 ──────────────────────────

def test_신발과_가방_신호가_동시에_있으면_None():
    assert guess_notice_type('신발>가방') is None


# ── 순수함수 — 같은 입력엔 같은 결과 ────────────────────────────────────────

def test_결정적이다():
    path = '신발>스니커즈>여성운동화'
    assert guess_notice_type(path) == guess_notice_type(path) == 'SHOES'
