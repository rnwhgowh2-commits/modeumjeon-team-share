# -*- coding: utf-8 -*-
"""브랜드·지재권 제한 판정 (스펙 §D). 순수함수 — DB 는 라우트가 읽어 rules 로 넘긴다.

원칙: 걸리면 그 마켓만 제외(+사유). 카테고리 미정 상태에서 프리픽스 규칙이 있으면
보수적으로 막는다 — 지재권은 잘못 올리는 쪽이 잘못 막는 쪽보다 비싸다.
"""
from __future__ import annotations

import re


def normalize(brand):
    """대소문자·공백·중간점 차이를 무시하는 비교 키."""
    return re.sub(r'[\s·.\-_]+', '', str(brand or '')).lower()


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
