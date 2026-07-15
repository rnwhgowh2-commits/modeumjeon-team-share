"""[2026-07-15] 마켓별 색상 통일 — 업로드 최종가를 같은 색끼리 하나로 통일.

정책(마켓별): 'color'=켜짐 / 'cheapest'=꺼짐(기본, no-op).
규칙: 'max'(가장 비싼 사이즈 기준·손해 방지) | 'src_cheapest'(그 색 최저가로 통일·마진 최대).

화면=업로드 원칙: 업로드 드라이런(preview.build_upload_preview) 의 **최종 업로드가**에만
적용한다 — 옵션마다 최종가가 1개(upload['ss'|'cp'])라 색상 그룹 max/min 이 결정적이고,
소싱/사입 카드 이중성으로 인한 화면↔업로드 어긋남이 생기지 않는다. 기본 'cheapest' 는
아무 값도 바꾸지 않아(no-op) 기존 템플릿 가격에 회귀 위험이 0 이다.
"""
from __future__ import annotations

from collections import defaultdict


def unify_price(prices, rule: str):
    """유효가(>0)만 모아 통일가 1개를 반환. 규칙 'max' | 'src_cheapest'. 없으면 None.

    'max'          → 그 색에서 가장 비싼 값 (어떤 사이즈도 원가보다 싸게 안 나감 = 손해 방지)
    'src_cheapest' → 그 색에서 가장 싼 값 (최저가 소싱처 기준 = 마진 최대)
    """
    valid = [int(p) for p in prices if p and int(p) > 0]
    if not valid:
        return None
    return max(valid) if rule == 'max' else min(valid)


# (market_key, price_field, policy_attr, rule_attr)
_MARKETS = [
    ('ss', 'ss_price', 'ss_pricing_policy', 'ss_unify_rule'),
    ('cp', 'cp_price', 'coupang_pricing_policy', 'coupang_unify_rule'),
]


def apply_color_unify(rows, tpl) -> None:
    """업로드 rows(각 dict: color·ss_price·cp_price)를 색상별로 통일 (제자리 수정).

    tpl 의 마켓별 정책이 'color' 일 때만 해당 마켓 price_field 를 색상 그룹 통일가로 덮는다.
    'cheapest'(기본)면 그 마켓은 건드리지 않는다. rows 는 한 모델(동일 model_code) 범위이므로
    color(색상 표시) 키로 그룹핑한다. 통일가가 없는(전부 가격없음) 색은 그대로 둔다.
    """
    if tpl is None or not rows:
        return
    for _mk, price_field, policy_attr, rule_attr in _MARKETS:
        policy = (getattr(tpl, policy_attr, None) or 'cheapest')
        if policy != 'color':
            continue
        rule = (getattr(tpl, rule_attr, None) or 'max')
        groups = defaultdict(list)
        for r in rows:
            groups[r.get('color')].append(r)
        for _color, grp in groups.items():
            unified = unify_price([r.get(price_field) for r in grp], rule)
            if unified is None:
                continue
            for r in grp:
                p = r.get(price_field)
                if p and int(p) > 0:
                    r[price_field] = unified
