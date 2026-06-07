"""소싱처 매입가 순차 누적 차감 — 순수 계산(DB 의존 없음).

compute_breakdown(api_benefits.py)의 계산 꼬리를 추출. 동작 100% 동일.
effective: [(kind, item)] where item has .benefit_name/.benefit_type('rate'|'amount')/.value/.enabled
"""
from __future__ import annotations


def _benefit_priority(it):
    if (it.benefit_type or 'rate') == 'amount':
        return 0
    if '적립' in (it.benefit_name or ''):
        return 1
    return 2


def _is_payment(nm):
    nm = nm or ''
    if '네이버' in nm:
        return False
    return any(t in nm for t in ('카드', '페이', '무신사머니', '청구할인', '캐시백'))


def compute_final_price(sale_price, effective, *, card_enabled=True,
                        card_issuer=None, base_override=None) -> dict:
    """effective(조립된 혜택 리스트) → 순차 누적 차감 결과.

    동작은 기존 compute_breakdown 꼬리(라인 720~822)와 100% 동일.
    """
    # 카테고리 정렬 (stable): 정액 → %적립 → %할인
    effective = sorted(effective, key=lambda x: _benefit_priority(x[1]))

    # 결제 수단 택1 (네이버 제외, 차감액 가장 큰 1개만 남김)
    _pay = [(k, it) for (k, it) in effective if it.enabled and _is_payment(it.benefit_name)]
    if len(_pay) > 1:
        def _approx_deduct(it):
            v = float(it.value or 0)
            return v if (it.benefit_type or 'rate') == 'amount' else float(sale_price) * v
        _best_it = max((it for _k, it in _pay), key=_approx_deduct)
        for _k, it in _pay:
            if it is not _best_it:
                it.enabled = False

    base = float(base_override if base_override is not None else sale_price)
    steps = []
    items_used = []
    for kind, it in effective:
        _by_card_off = ((not card_enabled) and card_issuer
                        and (card_issuer in (it.benefit_name or '')))
        is_effective_enabled = bool(it.enabled) and not _by_card_off
        items_used.append({
            'kind': kind, 'id': it.id, 'name': it.benefit_name,
            'type': it.benefit_type, 'value': float(it.value or 0),
            'category': getattr(it, 'category', None),
            'enabled': is_effective_enabled, 'disabled_by_card_off': _by_card_off,
        })
        if not is_effective_enabled:
            continue
        if it.benefit_type == 'rate':
            deduct = int(base * (it.value or 0))
        else:
            deduct = int(it.value or 0)
        deduct = min(deduct, int(base))
        base = max(base - deduct, 0)
        steps.append({
            'name': it.benefit_name, 'type': it.benefit_type,
            'value': float(it.value or 0), 'deduct': deduct, 'base_after': int(base),
        })
    return {
        'sale_price': float(base_override if base_override is not None else sale_price),
        'final_price': int(base),
        'steps': steps,
        'items_used': items_used,
    }
