# -*- coding: utf-8 -*-
"""브랜드·지재권 제한 판정 (스펙 §D). 순수함수 — DB 는 라우트가 읽어 rules 로 넘긴다.

원칙: 걸리면 그 마켓만 제외(+사유). 카테고리 미정 상태에서 프리픽스 규칙이 있으면
보수적으로 막는다 — 지재권은 잘못 올리는 쪽이 잘못 막는 쪽보다 비싸다.
"""
from __future__ import annotations

import re


#: 브랜드가 비어 제한표를 **판정조차 못 하는** 상태에 붙는 사유. 화면·등록 라우트가 같은 문장을 쓴다.
BRAND_REQUIRED_REASON = (
    '브랜드가 비어 있어 브랜드·지재권 제한표로 판정할 수 없습니다 — 제한 규칙이 '
    '등록돼 있는 동안에는 브랜드 없는 상품을 올릴 수 없습니다. 상품의 실제 브랜드를 '
    '넣어 주세요(상품명에서 지어내면 제한 브랜드가 그대로 올라갑니다).')


def normalize(brand):
    """대소문자·공백·중간점 차이를 무시하는 비교 키."""
    return re.sub(r'[\s·.\-_]+', '', str(brand or '')).lower()


def needs_brand(rules, brand):
    """브랜드가 비어 제한표가 무력해지는 상태면 사유, 아니면 None.

    ★ [2026-07-23 리뷰 C2] :func:`is_blocked` 는 브랜드가 비면 ``None``(무판정)이다.
      크롤이 만든 초안은 브랜드가 대개 비어 있으므로, 그대로 두면 **제한표가 만드는
      모든 방어가 통째로 꺼진다.** 제한 규칙이 하나라도 살아 있으면 「모름」을
      「통과」로 읽지 않는다 — 지재권은 잘못 막는 쪽이 잘못 올리는 쪽보다 싸다.
    """
    if normalize(brand):
        return None
    if not any(r.get('active') for r in (rules or [])):
        return None
    return BRAND_REQUIRED_REASON


def is_blocked(rules, brand, market, cat_path):
    """막히면 사유 문자열, 아니면 None. rules=[{brand,market,category_prefix,active,reason}]."""
    key = normalize(brand)
    if not key:
        return None
    for r in rules:
        if not r.get('active'):
            continue
        if normalize(r.get('brand')) != key:
            continue
        if r.get('market') not in ('*', market):
            continue
        prefix = (r.get('category_prefix') or '').strip()
        if prefix and cat_path and not str(cat_path).startswith(prefix):
            continue
        return f"{r.get('brand')} — {r.get('reason') or '지재권 제한'}"
    return None
