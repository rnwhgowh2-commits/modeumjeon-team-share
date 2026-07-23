# -*- coding: utf-8 -*-
"""「말 단위 포함」 판정 — 카테고리 제안과 금지어가 **같은 잣대**를 쓴다.

원래 `category_suggest.py` 안에만 있던 규칙이다. 2026-07-23 금지어 기능이 같은 판정을
필요로 하면서 밖으로 뺐다 — 규칙을 두 벌 만들면 한쪽만 고쳐져 갈린다(중복·모순 금지).

왜 맨 포함검사(`a in b`)면 안 되나 — 라이브 회귀가 두 번 났다:
  · 카테고리 제안(2026-07-23): 소싱처 'Men' 에 쿠팡 'Mentoring & Coaching' 이 1등.
  · 금지어(리뷰 C1): 수집 금지어 'Men' 이 상품명 'Mentoring Jacket' 에 걸려
    **초안 자체가 안 만들어졌다.** 'SET'·'BAG'·'SALE' 같은 짧은 영단어를 넣으면
    카탈로그가 통째로 사라진다.

어떤 규칙이 맞는지는 **언어의 성질**로 갈린다:
  · 영문은 띄어쓰기로 말을 끊는다 → 경계 없는 포함은 거의 항상 우연이다.
    그래서 **단어경계**를 요구한다(대소문자 무시). 복수형(Bag↔Bags)만 덤으로 허용.
  · 한글은 붙여 합성어를 만든다 → 포함이 곧 뜻의 포함인 경우가 많다
    ('여성운동화' ⊃ '운동화'). 단어경계를 걸면 정상 일치까지 다 날아간다.
    대신 **짧을수록 우연히 낀다**('가방' ⊂ '가방걸이', '반지' ⊂ '반지갑')는 성질을 써서
    2자 이하일 때만 경계를 추가로 요구한다.
"""
# [2026-07-23] 리뷰 C1 — 금지어 부분일치 사고 방지. category_suggest 에서 승격.
from __future__ import annotations

import re

_HANGUL_RE = re.compile(r'[가-힣]')
#: 이하면 한글도 경계를 요구한다. ★ 2자를 통째로 금지하지는 않는다 — 라이브 실측
#: '여성신발>플랫/로퍼' → 옥션 '여성화>로퍼' 가 그 예다('로퍼' 는 2자지만 앞이 '/').
SHORT_HANGUL_LEN = 2
# \b 대신 명시적 부정 룩어라운드 — 짧은 쪽이 기호로 시작·끝나면(예 'C++', '/로퍼')
# \b 의 의미가 뒤집혀 엉뚱하게 걸리거나 빠진다.
EDGE_L = r'(?<![0-9A-Za-z가-힣])'
EDGE_R = r'(?![0-9A-Za-z가-힣])'


def is_hangul(text) -> bool:
    return bool(_HANGUL_RE.search(str(text or '')))


def contains_word(haystack, needle) -> bool:
    """`haystack` 안에 `needle` 이 **말 단위로** 들어 있는가.

    'Mentoring Jacket'.contains_word('Men') → False   (영문 단어경계)
    'Mens Jacket'.contains_word('Men')      → True    (복수형 허용)
    '여성운동화'.contains_word('운동화')      → True    (3자 이상 한글 합성어)
    '반지갑'.contains_word('반지')            → False   (2자 이하 한글은 경계 필요)
    """
    hay, short = str(haystack or ''), str(needle or '').strip()
    if not hay or not short:
        return False
    hangul = is_hangul(short)
    if hangul and len(short) > SHORT_HANGUL_LEN:
        return short in hay                      # 3자 이상 한글 — 합성어 포함을 인정
    # 영문 복수형(Bag↔Bags)만 덤으로 허용한다. 's?' 를 붙여도 'Men' 이 'Mentoring' 에
    # 걸리지는 않는다(뒤가 't' 라 오른쪽 경계에서 막힌다).
    suffix = '' if hangul else 's?'
    return re.search(EDGE_L + re.escape(short) + suffix + EDGE_R, hay, re.I) is not None
