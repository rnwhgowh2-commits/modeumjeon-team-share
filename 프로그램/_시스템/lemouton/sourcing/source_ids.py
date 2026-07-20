# -*- coding: utf-8 -*-
"""소싱처 번호 변환 — 단일 원천.

소싱처를 가리키는 번호가 이 저장소에 **두 가지** 있다.

  화면 번호  `SourcingSource.id`   — 소싱처 관리·크롤 가이드 화면이 쓴다
  계산 번호  `SourceRegistry.id`   — 최종 매입가 계산(혜택 템플릿·override)이 쓴다

2026-06-30 단일명부 이관은 가이드 **내용만** 복사했고 번호는 정렬하지 않았다
(roster.py:153 migrate_guides_from_registry — 도메인·이름으로 매칭해 내용만 복사).
그 결과 8개 소싱처 전부에서 두 번호가 어긋났고, 화면에서 저장한 혜택이 다른
소싱처 계산에 들어갔다(무신사 후기적립 500원 → 롯데온, 2026-07-20 라이브 실측).

두 체계를 합치는 마이그레이션은 범위가 크므로, **변환을 여기 한 곳에만 둔다.**
번호를 직접 하드코딩하는 코드는 이 모듈을 쓰도록 바꾼다.
"""
from __future__ import annotations

# 계산 번호 → 소싱처 키. api_benefits._SITE_BY_SRC 가 갖고 있던 표를 여기로 옮긴 것.
#   ⚠ SourceRegistry 행의 실제 id 와 일치해야 한다. 어긋나면 전 소싱처 금액이 틀어진다.
_SITE_BY_PRICING_ID: dict[int, str] = {
    1: 'lemouton', 2: 'ss_lemouton', 3: 'musinsa',
    4: 'ssf', 5: 'lotteon', 6: 'ssg',
}
_PRICING_ID_BY_SITE: dict[str, int] = {v: k for k, v in _SITE_BY_PRICING_ID.items()}

# SourceRegistry 에 행이 없는 카탈로그 소싱처 — 'key:<source_key>' 합성 id 를 쓴다
# (api_pricing.py:728). 혜택 템플릿은 Integer 컬럼이라 이 소싱처엔 붙일 수 없다.
_CATALOG_KEYS = ('hmall', 'lotteimall')


def pricing_source_id(source_key):
    """소싱처 키 → 계산이 쓰는 source_id. 모르는 키면 None.

    반환형이 int 또는 'key:...' 문자열 두 가지다 — compute_breakdown 이 둘 다 받는다.
    """
    k = (source_key or '').strip()
    if k in _PRICING_ID_BY_SITE:
        return _PRICING_ID_BY_SITE[k]
    if k in _CATALOG_KEYS:
        return 'key:' + k
    return None


def site_key(pricing_id) -> "str | None":
    """계산 source_id → 소싱처 키. 모르면 None(추측 금지)."""
    if isinstance(pricing_id, str) and pricing_id.startswith('key:'):
        return pricing_id[4:].strip() or None
    try:
        return _SITE_BY_PRICING_ID.get(int(pricing_id))
    except (TypeError, ValueError):
        return None


def supports_benefit_templates(source_key) -> bool:
    """혜택 템플릿(SourceBenefitTemplate.source_id = Integer)을 붙일 수 있는 소싱처인가.

    False 인 소싱처(현대H몰·롯데아이몰)는 템플릿을 저장해도 계산이 읽지 못한다 —
    호출자가 조용히 버리지 말고 사용자에게 알려야 한다.
    """
    return isinstance(pricing_source_id(source_key), int)
