# -*- coding: utf-8 -*-
"""가격 템플릿 → 정책 이관 · 값 대조.

사장님 확정 — 「가격은 정책이 이긴다. 단 정책이 템플릿보다 큰 범위여야 한다(누락 0)」.

🔴 **옮긴 뒤 값이 같은지 기계로 대조하기 전에는 전환하지 않는다.**
   손으로 옮기지도 않는다 — 115칸을 사람이 옮기면 반드시 빠진다.
"""
from __future__ import annotations

from lemouton.policy.as_template import PREFIX_TO_MARKET

#: 엔진이 실제로 읽는 칸만 옮긴다. 나머지(정상가·반품비 등)는 화면용이라 따로 다룬다.
#: (템플릿 접두어, 정책 마켓키) 는 PREFIX_TO_MARKET 이 단일 원천.
_MODE_FROM_TPL = {'rate': 'margin_rate', 'amount': 'margin_amount',
                  'fixed': 'fixed_price'}


def _num(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return v


def price_config_from_template(tpl, prefix: str) -> dict:
    """템플릿의 한 마켓 → 정책 「판매가」 설정 한 벌.

    ★ 엔진(resolve_market_policy)이 읽는 칸을 **그대로** 옮긴다.
      마진율은 템플릿이 소수(0.0945), 정책은 퍼센트(9.45)라 100배 한다.
    """
    def g(attr, default=None):
        return getattr(tpl, attr, default)

    out: dict = {}
    for side, fixed_attr in (('sourcing', 'external_sale_price'),
                             ('purchase', 'boxhero_sale_price')):
        mode = _MODE_FROM_TPL.get(str(g(f'{prefix}_mode_{side}') or 'rate').lower())
        if mode:
            out[f'{side}_mode'] = mode
        rate = _num(g(f'{prefix}_rate_{side}'))
        if rate is not None:
            out[f'{side}_rate'] = round(rate * 100, 4)      # 소수 → 퍼센트
        amount = _num(g(f'{prefix}_amount_{side}'))
        if amount:                                           # 0 은 「안 씀」이라 안 옮긴다
            out[f'{side}_amount'] = int(amount)
        fixed = _num(g(f'{prefix}_{fixed_attr}'))
        if fixed:
            out[f'{side}_fixed'] = int(fixed)

    fee = _num(g(f'{prefix}_fee_rate'))
    if fee is not None:
        out['fee_rate'] = round(fee * 100, 4)
    normal = _num(g(f'{prefix}_normal_price'))
    if normal:
        out['normal_price'] = int(normal)

    lower, upper = _num(g('guardrail_lower')), _num(g('guardrail_upper'))
    if lower:
        out['floor_price'] = int(lower)
    if upper:
        out['cap_price'] = int(upper)
    unit = _num(g('rounding_unit'))
    if unit:
        out['rounding_unit'] = int(unit)

    pick = str(g(f'{prefix}_pricing_policy') or g('pricing_policy') or '').lower()
    if pick in ('cheapest', 'priciest', 'average'):
        out['source_pick'] = pick
    unify = str(g(f'{prefix}_unify_rule') or '').lower()
    if unify in ('max', 'min'):
        out['size_unify'] = unify
    return out


def shipping_config_from_template(tpl, prefix: str) -> dict:
    """템플릿의 배송·반품·교환비 → 정책 「배송」 항목.

    🔴 **판매가 계산에 배송비가 들어간다.** 이걸 안 옮기면 옮긴 정책이 배송비만큼
      싼 가격을 낸다(2026-08-01 전수 대조가 실제로 잡아냈다 — 스스 3,000 · 쿠팡 3,500).
    """
    def g(attr):
        v = getattr(tpl, attr, None)
        return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None

    out: dict = {}
    fee = g(f'{prefix}_delivery_fee')
    if fee is not None:
        out['fee_mode'] = 'paid' if fee > 0 else 'free'
        out['fee_amount'] = int(fee)
    ret = g(f'{prefix}_return_fee')
    if ret is not None:
        out['return_fee'] = int(ret)
    exc = g(f'{prefix}_exchange_fee')
    if exc:                      # 0 은 「안 정함」과 못 가르므로 값이 있을 때만
        out['exchange_fee'] = int(exc)
    return out


def migrate_template(session, *, tpl, policy_name: str = '') -> dict:
    """템플릿 하나를 정책 하나로 옮긴다(멱등 — 같은 이름이면 값만 갱신).

    Returns:
        {policy_id, name, markets: {마켓: 옮긴 칸 수}}
    """
    from lemouton.policy.models import MarketPolicy
    from lemouton.policy.service import create_policy, save_item
    from sqlalchemy import select

    name = (policy_name or f'{tpl.name} (가격 템플릿에서 옮김)').strip()
    p = session.scalar(select(MarketPolicy).where(
        MarketPolicy.name == name, MarketPolicy.deleted_at.is_(None)))
    if p is None:
        p = create_policy(session, name=name)

    moved = {}
    for prefix, market in PREFIX_TO_MARKET.items():
        cfg = price_config_from_template(tpl, prefix)
        if cfg:
            save_item(session, policy=p, market=market, item_key='price', config=cfg)
            moved[market] = len(cfg)
        # 배송비는 판매가 계산에 들어간다 — 같이 옮기지 않으면 가격이 그만큼 싸진다.
        ship = shipping_config_from_template(tpl, prefix)
        if ship:
            save_item(session, policy=p, market=market, item_key='shipping', config=ship)
            moved[market] = moved.get(market, 0) + len(ship)
    session.flush()
    return {'policy_id': p.id, 'name': p.name, 'markets': moved}


def compare_prices(session, *, tpl, policy_id: int, purchases=(50000, 92400, 150000)) -> dict:
    """옮긴 정책이 **같은 가격**을 내는지 기계로 대조한다.

    같은 매입가를 넣어 (마켓 × 소싱/사입) 으로 두 경로의 최종판매가를 비교한다.
    한 원이라도 다르면 그 줄을 담아 돌려준다 — **다르면 전환하지 않는다.**

    Returns:
        {ok, checked, rows:[{market, side, purchase, template, policy, diff}]}
        rows 는 **다른 것만** 담는다(같으면 담지 않는다).
    """
    from lemouton.policy.as_template import policy_as_template
    from lemouton.pricing.unified import compute_market_price

    shim = policy_as_template(session, policy_id)
    if shim is None:
        return {'ok': False, 'checked': 0, 'rows': [],
                'reason': '옮긴 정책에 판매가가 없습니다 — 이관이 안 된 것 같습니다.'}

    bad, checked = [], 0
    for prefix in PREFIX_TO_MARKET:
        for side in ('sourcing', 'purchase'):
            for purchase in purchases:
                checked += 1
                try:
                    a = compute_market_price(tpl, prefix, side, purchase).final_price
                except Exception as e:              # noqa: BLE001
                    a = f'오류: {e}'
                try:
                    b = compute_market_price(shim, prefix, side, purchase).final_price
                except Exception as e:              # noqa: BLE001
                    b = f'오류: {e}'
                if a != b:
                    bad.append({'market': prefix, 'side': side, 'purchase': purchase,
                                'template': a, 'policy': b,
                                'diff': (b - a) if isinstance(a, int) and isinstance(b, int)
                                        else None})
    return {'ok': not bad, 'checked': checked, 'rows': bad}


def attach_to_template_users(session, *, template_id: int, policy_id: int) -> dict:
    """그 가격 템플릿을 **쓰던 상품**에 옮긴 정책을 붙인다.

    🔴 이렇게 붙여야 가격이 안 바뀐다 — 값이 같은 정책이 같은 상품에 붙기 때문이다.
      아무 상품에나 붙이면 그 상품이 쓰던 템플릿과 값이 달라 가격이 흔들린다.

    Returns:
        {attached, skipped, codes}
        · 이미 **다른 정책**이 붙어 있는 상품은 건드리지 않는다(skipped) —
          사장님이 손으로 붙인 것을 말없이 갈아 끼우면 안 된다.
    """
    from lemouton.policy.models import BundlePolicyLink
    from lemouton.sourcing.models import Model

    codes = [m.model_code for m in session.query(Model)
             .filter(Model.price_template_id == template_id).all()]
    if not codes:
        return {'attached': 0, 'skipped': 0, 'codes': []}

    linked = {l.model_code: l for l in session.query(BundlePolicyLink)
              .filter(BundlePolicyLink.model_code.in_(codes)).all()}
    attached, skipped = [], []
    for c in codes:
        cur = linked.get(c)
        if cur is None:
            session.add(BundlePolicyLink(model_code=c, policy_id=policy_id))
            attached.append(c)
        elif cur.policy_id == policy_id:
            attached.append(c)                  # 이미 이 정책 — 멱등
        else:
            skipped.append(c)                   # 다른 정책이 붙어 있다 — 그대로 둔다
    session.flush()
    return {'attached': len(attached), 'skipped': len(skipped), 'codes': attached}
