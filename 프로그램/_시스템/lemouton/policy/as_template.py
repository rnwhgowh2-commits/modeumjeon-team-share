# -*- coding: utf-8 -*-
"""정책을 **가격 엔진이 읽을 수 있는 모양**으로 — 엔진은 건드리지 않는다.

가격은 `pricing/unified.py:resolve_market_policy(tpl, market, side)` 하나가 정한다.
그게 읽는 건 PriceTemplate 의 칸 이름 몇 개뿐이다. 그래서 **그 이름들만 흉내 내는
껍데기**를 만들면, 엔진·호출처를 고치지 않고도 정책이 가격을 정하게 할 수 있다.

🔴 **이 파일은 값을 만들지 않는다.** 정책이 안 정한 칸은 `None` 을 돌려줘
   엔진이 원래 하던 대로(마켓 기본값·폴백) 처리하게 둔다. 여기서 0 을 채우면
   그 가격이 그대로 마켓에 나간다.

쓰는 법:
    tpl = policy_as_template(session, policy_id) or 원래_템플릿
    compute_market_price(tpl, 'ss', 'sourcing', 매입가)
"""
from __future__ import annotations

from lemouton.policy.price_cfg import read_side

#: 엔진의 마켓 접두어 → 정책의 마켓 키. unified._PREFIX_MAP 과 짝이다.
PREFIX_TO_MARKET = {
    'ss': 'smartstore', 'coupang': 'coupang', 'lotteon': 'lotteon',
    'eleven11': 'eleven11', 'auction': 'auction', 'gmarket': 'gmarket',
}

#: 방식 이름 — 정책 → 엔진(compute_sale_price_unified 가 아는 말)
MODE_TO_ENGINE = {'margin_rate': 'rate', 'margin_amount': 'amount',
                  'fixed_price': 'fixed'}


class _PolicyTemplate:
    """PriceTemplate 흉내 — 엔진이 묻는 칸만 정책에서 꺼내 준다.

    엔진은 `getattr(tpl, '<접두>_rate_sourcing', None)` 처럼 묻는다.
    여기서는 그 이름을 풀어 (마켓, 쪽, 무엇) 으로 바꿔 정책값을 찾는다.
    """

    def __init__(self, values_by_market: dict, rounding_unit: int = 100,
                 guardrail: tuple | None = None, policy_id: int | None = None):
        self._v = values_by_market or {}
        self.rounding_unit = rounding_unit or 100
        self.guardrail_lower = guardrail[0] if guardrail else None
        self.guardrail_upper = guardrail[1] if guardrail else None
        self.policy_id = policy_id

    # ── 내부 ────────────────────────────────────────────────────────
    def _price(self, prefix: str) -> dict:
        mk = PREFIX_TO_MARKET.get(prefix)
        return ((self._v.get(mk) or {}).get('price') or {}) if mk else {}

    def _ship(self, prefix: str) -> dict:
        mk = PREFIX_TO_MARKET.get(prefix)
        return ((self._v.get(mk) or {}).get('shipping') or {}) if mk else {}

    # ── 엔진이 묻는 이름들 ──────────────────────────────────────────
    def __getattr__(self, name: str):
        for prefix in PREFIX_TO_MARKET:
            if not name.startswith(prefix + '_'):
                continue
            tail = name[len(prefix) + 1:]
            cfg = self._price(prefix)

            for side in ('sourcing', 'purchase'):
                if tail == f'mode_{side}':
                    return MODE_TO_ENGINE.get(read_side(cfg, side).mode)
                if tail == f'rate_{side}':
                    r = read_side(cfg, side).rate
                    return None if r is None else r / 100.0   # 엔진은 소수로 받는다
                if tail == f'amount_{side}':
                    return read_side(cfg, side).amount

            if tail == 'external_sale_price':        # 소싱 지정가
                return read_side(cfg, 'sourcing').fixed
            if tail == 'boxhero_sale_price':         # 사입 지정가
                return read_side(cfg, 'purchase').fixed
            if tail == 'fee_rate':
                v = cfg.get('fee_rate')
                if isinstance(v, bool) or not isinstance(v, (int, float)):
                    return None                      # 안 정함 → 엔진이 마켓 기본값
                return float(v) / 100.0
            if tail == 'delivery_fee':
                # 🔴 배송비는 「배송」 항목이 주인이다 — 판매가에 같은 칸을 만들지 않았다.
                sh = self._ship(prefix)
                if (sh.get('fee_mode') or 'free') == 'free':
                    return 0
                v = sh.get('fee_amount')
                return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0
            break
        # 엔진이 묻지 않는 이름 — 없다고 답한다(PriceTemplate 이 아니니 당연하다)
        raise AttributeError(name)


def policy_as_template(session, policy_id: int):
    """정책 하나를 엔진이 읽을 수 있는 껍데기로. 정책이 없으면 None.

    🔴 **판매가를 하나도 안 정한 정책이면 None** 을 돌려준다 — 빈 정책을 물리면
      엔진이 마켓 기본 마진율로 계산해 **엉뚱한 가격**을 만든다. 그럴 바엔
      쓰던 템플릿을 그대로 쓰는 게 옳다.
    """
    from lemouton.policy.fields import MARKET_KEYS
    from lemouton.policy.models import MarketPolicy
    from lemouton.policy.service import values_for

    p = session.get(MarketPolicy, policy_id)
    if p is None or p.deleted_at is not None:
        return None

    by_market, guard, rounding = {}, None, 100
    for mk in MARKET_KEYS:
        v = values_for(session, p.id, mk)
        if v:
            by_market[mk] = v
            pr = v.get('price') or {}
            if guard is None and (pr.get('floor_price') or pr.get('cap_price')):
                guard = (pr.get('floor_price'), pr.get('cap_price'))
            if isinstance(pr.get('rounding_unit'), int):
                rounding = pr['rounding_unit']

    has_price = any((v.get('price') or {}) for v in by_market.values())
    if not has_price:
        return None
    return _PolicyTemplate(by_market, rounding_unit=rounding,
                           guardrail=guard, policy_id=p.id)


def policy_template_for_model(session, model_code: str):
    """그 상품에 붙은 정책을 껍데기로. 없으면 None(= 쓰던 템플릿을 그대로)."""
    from lemouton.policy.models import BundlePolicyLink
    link = session.get(BundlePolicyLink, model_code)
    if link is None:
        return None
    return policy_as_template(session, link.policy_id)
