"""소싱처 매입가 순차 누적 차감 — 순수 계산(DB 의존 없음).

compute_breakdown(api_benefits.py)의 계산 꼬리를 추출. 동작 100% 동일.
effective: [(kind, item)] where item has .benefit_name/.benefit_type('rate'|'amount')/.value/.enabled

M2b 확장:
- preapplied skip (선반영 항목은 차감 안 하고 items_used 에만 기록)
- tagged-mode: pay_method/channel 태그가 하나라도 있으면 경로 열거 최저가 선택
- 태그 없으면 legacy 경로 (7개 기존 테스트 byte-identical)
"""
from __future__ import annotations
from itertools import product as _product


# ────────────────────────────────────────────────────────────────────────────
# 공통 헬퍼
# ────────────────────────────────────────────────────────────────────────────

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


def _is_tagged(effective):
    """apply_mode/pay_method/channel 신규 필드가 하나라도 있으면 tagged-mode."""
    return any(
        getattr(it, 'pay_method', None) in ('affiliate_card', 'naver_pay')
        or getattr(it, 'channel', None) == 'naver_via'
        for _k, it in effective
    )


# ────────────────────────────────────────────────────────────────────────────
# 단일 경로 실행기 (tagged-mode 전용; shared item 객체 불변)
# ────────────────────────────────────────────────────────────────────────────

def _run(sale_price, ordered, active, *, card_enabled, card_issuer, base_override):
    """ordered[(kind,it)] 와 active(kind,it)->bool 을 받아 한 경로의 결과를 반환.

    shared item 객체를 일절 변경하지 않는다 (active callable 로 활성화 판정).
    """
    base = float(base_override if base_override is not None else sale_price)
    steps = []
    items_used = []
    for kind, it in ordered:
        apply_mode = getattr(it, 'apply_mode', None)
        is_preapplied = (apply_mode == 'preapplied')

        _by_card_off = ((not card_enabled) and card_issuer
                        and (card_issuer in (it.benefit_name or '')))
        # 활성화 = base enabled AND active(path 조건) AND not card-off
        # preapplied 는 items_used 기록만, 차감 없음
        if is_preapplied:
            is_effective_enabled = bool(it.enabled) and not _by_card_off
            items_used.append({
                'kind': kind, 'id': it.id, 'name': it.benefit_name,
                'type': it.benefit_type, 'value': float(it.value or 0),
                'category': getattr(it, 'category', None),
                'enabled': is_effective_enabled, 'disabled_by_card_off': _by_card_off,
                'preapplied': True,
            })
            continue  # 차감 없음 — 선반영 항목

        is_effective_enabled = (
            bool(it.enabled) and not _by_card_off and active(kind, it)
        )
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


# ────────────────────────────────────────────────────────────────────────────
# Legacy 경로 (태그 없음 — 기존 동작 완전 보존)
# ────────────────────────────────────────────────────────────────────────────

def _compute_legacy(sale_price, effective, *, card_enabled, card_issuer, base_override):
    """기존 compute_final_price 동작 (tagged 필드 없는 항목 집합). 7개 기존 테스트 전용."""
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
        apply_mode = getattr(it, 'apply_mode', None)
        is_preapplied = (apply_mode == 'preapplied')

        _by_card_off = ((not card_enabled) and card_issuer
                        and (card_issuer in (it.benefit_name or '')))
        if is_preapplied:
            is_effective_enabled = bool(it.enabled) and not _by_card_off
            items_used.append({
                'kind': kind, 'id': it.id, 'name': it.benefit_name,
                'type': it.benefit_type, 'value': float(it.value or 0),
                'category': getattr(it, 'category', None),
                'enabled': is_effective_enabled, 'disabled_by_card_off': _by_card_off,
                'preapplied': True,
            })
            continue

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
    result = {
        'sale_price': float(base_override if base_override is not None else sale_price),
        'final_price': int(base),
        'steps': steps,
        'items_used': items_used,
        'path': None,
    }
    return result


# ────────────────────────────────────────────────────────────────────────────
# Tagged 경로 (경로 열거 최저가)
# ────────────────────────────────────────────────────────────────────────────

def _compute_tagged(sale_price, effective, *, card_enabled, card_issuer, base_override):
    """세트 제약(결제택1 + 네이버경유↔캐시백) 경로를 열거해 최저가 경로를 반환."""
    # 카테고리 정렬 (stable)
    ordered = sorted(effective, key=lambda x: _benefit_priority(x[1]))

    # pay_choice 후보: enabled payment 항목의 distinct pay_method + None(무결제)
    payment_methods = list(dict.fromkeys(
        getattr(it, 'pay_method', None)
        for _k, it in ordered
        if (getattr(it, 'apply_mode', None) == 'payment' and bool(it.enabled)
            and getattr(it, 'pay_method', None) is not None)
    ))
    pay_choices = payment_methods + [None]  # None = 무결제

    # via 후보: naver_via 항목이 있으면 {False,True} 아니면 {False}
    has_naver_via = any(getattr(it, 'channel', None) == 'naver_via' for _k, it in ordered)
    via_choices = [False, True] if has_naver_via else [False]

    best = None
    best_path = None

    for pay_choice, via in _product(pay_choices, via_choices):
        def active(kind, it, _pc=pay_choice, _via=via):
            apply_mode = getattr(it, 'apply_mode', None)
            channel = getattr(it, 'channel', None)
            pay_method = getattr(it, 'pay_method', None)

            # payment 항목: 선택된 pay_choice 와 일치해야 활성
            if apply_mode == 'payment':
                return pay_method == _pc

            # cashback 항목: 네이버경유 시 비활성 (제약②)
            if apply_mode == 'cashback':
                return not _via

            # naver_via 전용 혜택: 경유일 때만 활성
            if channel == 'naver_via':
                return _via

            # 나머지: base enabled (card-off 는 _run 내부에서 처리)
            return True

        res = _run(sale_price, ordered, active,
                   card_enabled=card_enabled, card_issuer=card_issuer,
                   base_override=base_override)
        if best is None or res['final_price'] < best['final_price']:
            best = res
            best_path = {'pay_method': pay_choice, 'naver_via': via}

    best['path'] = best_path
    return best


# ────────────────────────────────────────────────────────────────────────────
# 공개 API
# ────────────────────────────────────────────────────────────────────────────

def compute_final_price(sale_price, effective, *, card_enabled=True,
                        card_issuer=None, base_override=None) -> dict:
    """effective(조립된 혜택 리스트) → 순차 누적 차감 결과.

    태그 없음(legacy): 기존 동작 100% 보존 + path=None 추가.
    태그 있음(tagged): 세트 제약(결제택1·네이버경유↔캐시백) 경로 열거 → 최저가 반환.
    """
    effective = list(effective)  # 반복 소비 방지 (generator 대응)
    if _is_tagged(effective):
        return _compute_tagged(sale_price, effective,
                               card_enabled=card_enabled, card_issuer=card_issuer,
                               base_override=base_override)
    return _compute_legacy(sale_price, effective,
                           card_enabled=card_enabled, card_issuer=card_issuer,
                           base_override=base_override)
