# -*- coding: utf-8 -*-
"""할인 반영 리허설 — **아무것도 바꾸지 않고** 무엇이 어떻게 될지만 본다.

🔴 판매가가 바뀌는 변경은 사장님 승인 없이 마켓에 나가면 안 된다. 그런데
  승인하려면 **무엇이 얼마나 바뀌는지** 볼 수 있어야 한다. 그 표를 만든다.

🔴 **계산은 여기 한 곳에서만.** 스크립트(터미널)와 화면이 각자 계산하면 두
  숫자가 갈리고, 그러면 승인 자체가 무의미해진다.

읽는 법 (한 줄 = 정책 × 마켓 × 대표 매입가):
  · `price_before` → `price_after`   마켓 화면에 보이는 **표시 판매가**
  · `customer_after`                 고객이 실제로 내는 값(**전체** 할인 뺀 값)
  · `margin_before` → `margin_after` **우리 수입 기준**(판매가 − 우리 부담) 마진

🔴 「고객이 내는 값」과 「우리 수입 기준」은 다른 숫자다. 마켓이 할인을 같이
  부담하면 고객은 전체 할인만큼 싸게 사고, 마켓이 낸 몫은 우리에게 들어온다.
"""
from __future__ import annotations

#: 매입가는 정책에 없다 — 폭을 보여 주려고 대표값 몇 개로 잰다.
SAMPLES = (10_000, 50_000, 200_000)


def _products_on(session, policy_id: int) -> int:
    """이 정책이 붙은 상품·구성 수. 🔴 「정책 1건」과 「상품 300개」는 무게가 다르다."""
    from lemouton.policy.models import BundlePolicyLink, SetPolicyLink
    n = session.query(BundlePolicyLink).filter(
        BundlePolicyLink.policy_id == policy_id).count()
    n += session.query(SetPolicyLink).filter(
        SetPolicyLink.policy_id == policy_id).count()
    return int(n)


def rehearse(session, *, min_margin: int = 0, samples=SAMPLES) -> dict:
    """읽기 전용. `{policies_total, policies_with_discount, rows, newly_held, errors}`.

    Args:
        min_margin: 역마진 가드 기준(원). 이보다 마진이 적으면 전송이 보류된다.
        samples: 대표 매입가들.

    🔴 이 함수는 **아무것도 저장하지 않는다.** commit·flush 를 부르지 않는다.
    """
    from lemouton.policy.as_template import PREFIX_TO_MARKET, policy_as_template
    from lemouton.policy.discount import discount_of, exposed_price, seller_share
    from lemouton.policy.fields import MARKET_KEYS
    from lemouton.policy.models import MarketPolicy
    from lemouton.policy.service import values_for
    from lemouton.pricing.unified import compute_market_price, compute_sale_price_unified
    from lemouton.uploader.reconcile import compute_margin_amount

    to_prefix = {v: k for k, v in PREFIX_TO_MARKET.items()}
    rows, errors = [], []

    policies = [p for p in session.query(MarketPolicy).all() if p.deleted_at is None]
    targets = []
    for p in policies:
        for mk in MARKET_KEYS:
            price = ((values_for(session, p.id, mk) or {}).get('price') or {})
            if discount_of({'price': price}):
                targets.append((p, mk, price))

    for p, mk, price in targets:
        prefix = to_prefix.get(mk)
        if not prefix:
            errors.append(f'{p.name} / {mk}: 가격 엔진이 모르는 마켓입니다')
            continue
        tpl = policy_as_template(session, p.id)
        if tpl is None:
            errors.append(f'{p.name} / {mk}: 판매가를 하나도 안 정한 정책입니다')
            continue

        전체할인 = discount_of({'price': price})
        단위, 우리몫 = seller_share(price)
        products = _products_on(session, p.id)
        수수료 = float(getattr(tpl, f'{prefix}_fee_rate', None) or 0)

        for purchase in samples:
            try:
                after = compute_market_price(tpl, prefix, 'sourcing', purchase)
                before = compute_sale_price_unified(
                    purchase,
                    margin_rate=getattr(tpl, f'{prefix}_rate_sourcing', None) or 0,
                    fee_rate=수수료,
                    shipping_fee=getattr(tpl, f'{prefix}_delivery_fee', 0) or 0,
                    rounding_unit=getattr(tpl, 'rounding_unit', 100) or 100,
                    mode=str(getattr(tpl, f'{prefix}_mode_sourcing', 'rate') or 'rate'),
                    margin_amount=getattr(tpl, f'{prefix}_amount_sourcing', 0) or 0,
                    fixed_price=getattr(tpl, f'{prefix}_external_sale_price', 0) or 0)
            except Exception as e:                       # noqa: BLE001
                errors.append(f'{p.name} / {mk} / 매입 {purchase:,}: {e}')
                continue

            # 🔴 마진 기준은 **우리 수입**(판매가 − 우리 부담). 고객가로 재면
            #   마켓이 낸 몫까지 우리 손해로 세어 멀쩡한 정책을 적자로 오보한다.
            기준_전 = exposed_price(before.final_price,
                                    {'value': 우리몫, 'unitType': 단위}) \
                if 우리몫 else before.final_price
            margin_before = int(round(기준_전 * (1 - 수수료))) - purchase
            margin_after = compute_margin_amount(after, purchase)

            rows.append({
                'policy_id': p.id, 'policy': p.name, 'market': mk,
                'products': products, 'purchase': purchase,
                'discount': f"{전체할인['value']}"
                            f"{'%' if 전체할인['unitType'] == 'PERCENT' else '원'}",
                'burden': str(price.get('discount_burden') or 'seller'),
                'price_before': before.final_price,
                'price_after': after.final_price,
                'customer_before': exposed_price(before.final_price, 전체할인),
                'customer_after': exposed_price(after.final_price, 전체할인),
                'margin_before': margin_before,
                'margin_after': margin_after,
                'newly_held': bool(margin_before >= min_margin
                                   and margin_after is not None
                                   and margin_after < min_margin),
            })

    return {
        'policies_total': len(policies),
        'policies_with_discount': len(targets),
        'rows': rows,
        'newly_held': sum(1 for r in rows if r['newly_held']),
        'loss_before': sum(1 for r in rows if r['margin_before'] < 0),
        'products_affected': sum({(r['policy_id'], r['market']): r['products']
                                  for r in rows}.values()),
        'min_margin': int(min_margin),
        'errors': errors,
    }
