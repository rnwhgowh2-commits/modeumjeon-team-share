# -*- coding: utf-8 -*-
"""소싱처 카테고리 경로 텍스트 → 상품고시정보 유형(SHOES|BAG) 자동 판정 (순수함수).

[배경 — 2026-08-20]
  `ProductDraft.notice_type` 기본값은 'WEAR'(의류)다(registration/models.py:43).
  "모음전 경로"(send/as_draft.py::upsert)는 이 값을 전혀 채우지 않아, 신발·가방
  상품도 전부 「의류」 고시정보로 마켓에 나가고 있었다(policy/fixed_sends.py
  COMMON_DEFAULTS「고시 유형」에 기록됨). 이 모듈은 초안이 이미 들고 있는
  `source_category_path`(예: '신발>스니커즈>여성운동화') 텍스트만 보고 SHOES·BAG
  를 판정한다 — 새로 크롤하거나 API 를 부르지 않는다(순수함수).

[판정 못하면 WEAR] — 신발도 가방도 아니라고 확신할 근거가 없으면 None 을 돌려준다.
  호출자는 None 이면 지금과 같이 컬럼 기본값 'WEAR' 를 그대로 둔다. 잘못 단정해서
  실제로는 의류인 상품에 SHOES/BAG 고시(다른 필수 필드를 요구함 — notice.py
  _PER_TYPE_REQUIRED 참고)를 붙이는 것보다, 기존 동작(WEAR)을 유지하는 편이
  안전하다 — 이 프로젝트의 폴백 금지 원칙과 같은 방향("없는 값을 지어내지 않는다").

  BAG 과 FASHION_ITEMS(패션잡화 — 벨트·모자·장갑·주얼리 등) 은 구분하지 않는다.
  이번 버그 리포트가 다루는 범위는 「신발·가방」 뿐이고(fixed_sends.py 의 note
  원문도 그렇다), 카테고리 텍스트만으로 이 둘을 신뢰성 있게 가르는 것은 별개의
  작업이라 손대지 않았다 — 패션잡화 대상 카테고리는 지금과 같이 WEAR 로 남는다.

[함정 — 짧은 한글 토큰의 부분일치 오탐] (registration/category_suggest.py 의
  "짧은 토큰일수록 우연히 낀다" 절 · registration/word_match.py 참고)
  '가방' ⊂ '가방걸이', '신발' ⊂ '신발장' 처럼, 2자 이하 한글 낱말은 무관한 낱말
  안에나 뒤에 우연히 낀다. 그렇다고 완전일치만 요구하면 '여성가방'·'남성신발'
  같은 흔한 성별 합성어를 다 놓친다(수식어가 붙어도 뜻은 그대로 「가방」·「신발」다).
  그래서 두 단계로 나눈다:
    · 3자 이상 키워드는 그 마디('>' 로 나눈 경로 조각) 안 부분일치를 인정한다
      (예: '여성운동화' ⊃ '운동화') — word_match.contains_word 의 한글 규칙(3자
      이상은 합성어 포함 인정)과 같은 기준이다.
    · 2자 이하 키워드는 그 마디 **전체**가 (성별·연령 수식어)* + 키워드 모양일
      때만 인정한다(`_segment_is_keyword`). '가방걸이'는 수식어도 키워드도 아닌
      '걸이'가 남아 전체일치가 안 되므로 걸러지고, '여성가방'은 '여성'(수식어)
      + '가방'(키워드)로 정확히 나뉘어 잡힌다.
  성별·연령 수식어 낱말은 category_suggest.py 의 _FEMALE_RE/_MALE_RE/_KIDS_RE/
  _ADULT_RE/_UNISEX_RE 가 쓰는 것과 같은 어휘를 쓴다(중복·모순 금지 — 뜻의
  정본은 그 파일. 여기서는 "수식어 접두" 판정에만 쓴다).
"""
from __future__ import annotations

import re

#: category_suggest.py 성별·연령 축(_FEMALE_RE/_MALE_RE/_KIDS_RE/_ADULT_RE/_UNISEX_RE)
#: 과 같은 어휘. 새 낱말을 추가하려면 그 파일의 축 판정도 같이 볼 것(두 벌로
#: 나뉘면 한쪽만 고쳐져 갈린다).
_GENDER_AGE_MODIFIERS = (
    '남녀공용', '유니섹스', '공용',
    '여성', '여자', '남성', '남자',
    '유아동', '아동', '유아', '키즈', '주니어', '베이비', '남아', '여아',
    '성인', '시니어',
)
_MODIFIER_RE = '(?:' + '|'.join(_GENDER_AGE_MODIFIERS) + ')'

#: 이 길이 이상이면 마디 안 부분일치를 인정한다.
#: word_match.SHORT_HANGUL_LEN(=2) 과 같은 경계 — "2자 이하는 위험, 3자부터 안전".
_SAFE_SUBSTRING_LEN = 3

#: 신발류 — 대분류('신발'·'슈즈')와 흔한 하위 유형.
SHOES_KEYWORDS = (
    '신발', '슈즈', '운동화', '스니커즈', '구두', '로퍼', '워커', '단화',
    '부츠', '첼시부츠', '앵클부츠', '롱부츠', '레인부츠', '어그부츠',
    '샌들', '슬리퍼', '힐', '하이힐', '펌프스', '옥스퍼드화', '캔버스화', '플랫슈즈',
)

#: 가방류 — 대분류('가방')와 흔한 하위 유형.
#:   🔴 '지갑'·'파우치' 는 일부러 뺐다 — 패션잡화(FASHION_ITEMS)로 분류될 수도
#:     있어 확신이 없다(모듈 docstring "BAG 과 FASHION_ITEMS" 절 참고).
BAG_KEYWORDS = (
    '가방', '백팩', '크로스백', '숄더백', '토트백', '메신저백', '클러치백', '클러치',
    '에코백', '웨이스트백', '버킷백', '호보백', '캔버스백', '보스턴백',
    '여행가방', '서류가방', '숄더가방', '크로스바디백',
)


def _segment_is_keyword(segment: str, keyword: str) -> bool:
    """`segment`(경로 한 마디) 전체가 (성별·연령 수식어)* + `keyword` 모양인가.

    전체일치(``re.fullmatch``)만 인정한다 — '가방걸이'처럼 키워드 뒤에 다른
    낱말이 붙으면 그 나머지가 수식어도 키워드도 아니라 실패한다.
    """
    if not segment or not keyword:
        return False
    pattern = f'^(?:{_MODIFIER_RE})*{re.escape(keyword)}$'
    return re.fullmatch(pattern, segment, re.I) is not None


def _has_keyword(path_text: str, keywords: tuple) -> bool:
    """path_text( '>' 로 이어진 카테고리 경로) 안에 keywords 중 하나가 안전하게 있는가."""
    segments = [s.strip() for s in str(path_text or '').split('>') if s.strip()]
    if not segments:
        return False
    for kw in keywords:
        for seg in segments:
            if _segment_is_keyword(seg, kw):
                return True
            if len(kw) >= _SAFE_SUBSTRING_LEN and kw in seg:
                return True
    return False


def guess_notice_type(source_category_path: str):
    """카테고리 경로 텍스트 → 'SHOES' | 'BAG' | None(판정 못함 — 호출자는 WEAR 유지).

    신발·가방 신호가 **동시에** 잡히면(예: 신발도 가방도 함께 적힌 모호한 경로)
    어느 한쪽으로 단정하지 않고 None 을 돌려준다 — 잘못 단정하는 것보다 지금처럼
    WEAR 로 남는 편이 안전하다.

    Args:
        source_category_path: `ProductDraft.source_category_path` 값. 예:
            '신발>스니커즈>여성운동화'. 빈 값·None 이면 None.

    Returns:
        'SHOES' | 'BAG' | None
    """
    text = str(source_category_path or '').strip()
    if not text:
        return None
    is_shoes = _has_keyword(text, SHOES_KEYWORDS)
    is_bag = _has_keyword(text, BAG_KEYWORDS)
    if is_shoes and is_bag:
        return None
    if is_shoes:
        return 'SHOES'
    if is_bag:
        return 'BAG'
    return None
