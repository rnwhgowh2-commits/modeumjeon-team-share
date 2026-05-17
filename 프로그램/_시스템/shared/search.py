"""다중 키워드 AND 교집합 검색 — 박스히어로식 칩 UI 백엔드 헬퍼.

원칙
- 공백/콤마/탭 단위로 토큰화
- 토큰 간 AND, 토큰 안에서는 인자로 받은 컬럼들끼리 OR
- 빈 문자열·공백만 있는 토큰은 자동 제거
- 중복 토큰은 호출 측에서 미리 dedup 권장 (백엔드는 보수적으로 그대로 처리)

사용 예
    from shared.search import split_tokens, apply_and_filter

    tokens = split_tokens(request.args.get('q'))
    query = apply_and_filter(query, tokens, Option.canonical_sku, Option.boxhero_sku)

또는 ilike 가 필요한 경우 (대소문자 무시):
    query = apply_and_filter(query, tokens, Model.model_code, Model.brand, op='ilike')
"""
from __future__ import annotations
import re
from typing import Iterable

from sqlalchemy import or_

# 공백·콤마·탭·세미콜론·여러 공백을 1개 구분자로
_SPLIT = re.compile(r"[\s,;]+")


def split_tokens(q: str | None) -> list[str]:
    """검색 문자열을 토큰 리스트로 분해 (공백·콤마·세미콜론 구분, 빈 토큰 제거).

    예: "르무통 메이트  그레이" → ["르무통", "메이트", "그레이"]
    예: "르무통,메이트,그레이" → ["르무통", "메이트", "그레이"]
    """
    if not q:
        return []
    return [t.strip() for t in _SPLIT.split(q.strip()) if t.strip()]


def apply_and_filter(query, tokens: Iterable[str], *columns, op: str = 'like'):
    """tokens 를 AND 로 묶고, 토큰 안에서는 columns 들 사이 OR.

    Parameters
    ----------
    query : SQLAlchemy Query
    tokens : iterable of str
    *columns : InstrumentedAttribute (Option.canonical_sku 등)
    op : 'like' | 'ilike'
    """
    if not columns:
        return query
    for tok in tokens:
        if not tok:
            continue
        like_pat = f'%{tok}%'
        ored = []
        for c in columns:
            if op == 'ilike':
                ored.append(c.ilike(like_pat))
            else:
                ored.append(c.like(like_pat))
        query = query.filter(or_(*ored))
    return query
