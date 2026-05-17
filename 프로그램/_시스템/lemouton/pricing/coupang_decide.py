# lemouton/pricing/coupang_decide.py
"""쿠팡 가격 결정 (옵션 단위).

결정 트리 (spec §5.3 + §5.4):
  1. 옵션 오버라이드 → 1차
  2. 사입품 재고 ≥ 1 → 사입품 가격
  3. 사입품 = 0 → 외부 가격 (가드레일 검증 후 사용)
     ├─ use_margin_formula → 공식
     └─ 그 외 → external_coupang_price
  4. 위너매치 적용 (5.4)
  5. 모든 재고 0 → out_of_stock
"""
from .models import Decision
from .winner_match import apply_winner_match
from .guardrail import check_external_price
from .rounding import round_to_unit


def _formula_price(unit_price: int, fee_rate: float, margin_rate: float,
                   delivery_fee: int) -> int:
    """판매가 = (단가 + 택배비) / (1 - fee% - margin%)."""
    denom = 1.0 - fee_rate - margin_rate
    if denom <= 0:
        raise ValueError(f"invalid denom: fee={fee_rate}, margin={margin_rate}")
    return int((unit_price + delivery_fee) / denom)


def decide_coupang(
    option_data: dict,
    *,
    fee_rate: float = 0.1155,
    delivery_fee: int = 3000,
    rounding_unit: int = 100,
) -> Decision:
    """단일 옵션의 쿠팡 가격 결정."""
    sku = option_data["canonical_sku"]
    pricing = option_data["pricing"]
    competitor = option_data.get("competitor_status", {}).get("coupang")
    winner_price = pricing.get("coupang_winner_premium_effective", 149000)

    # 가용 외부 소싱 식별 — 가드레일 통과 + 재고 ≥ 1
    external_alerts = []
    usable_external_prices = []
    for src in option_data.get("sources", []):
        if src.get("stock", 0) <= 0:
            continue
        gr = check_external_price(
            external_price=src["price"],
            guardrail_lower=pricing.get("guardrail_lower_effective", 99000),
            guardrail_upper=pricing.get("guardrail_upper_effective", 120000),
            canonical_sku=sku,
            source=src["name"],
        )
        if gr.alert:
            external_alerts.append(gr.alert)
        if gr.is_usable:
            usable_external_prices.append(src["price"])

    boxhero_stock = option_data.get("boxhero_stock", 0)

    # 1. 옵션 오버라이드 (위너매치 분기 가능 — apply_winner_match로 처리)
    option_override = pricing.get("option_coupang_price_override")
    if option_override is not None:
        wm = apply_winner_match(
            primary_price=option_override,
            primary_reason="option_override",
            winner_price=winner_price,
            competitor_status=competitor,
        )
        return Decision(market="coupang", canonical_sku=sku,
                        price=round_to_unit(wm.price, rounding_unit),
                        displayed=True, reason=wm.reason)

    # 2. 사입품 재고
    if boxhero_stock >= 1:
        primary = pricing.get("boxhero_coupang_price_effective", 128900)
        wm = apply_winner_match(
            primary_price=primary,
            primary_reason="boxhero_mode",
            winner_price=winner_price,
            competitor_status=competitor,
        )
        return Decision(market="coupang", canonical_sku=sku,
                        price=round_to_unit(wm.price, rounding_unit),
                        displayed=True, reason=wm.reason)

    # 3. 외부 소싱 (사입품 0)
    if not usable_external_prices:
        return Decision(market="coupang", canonical_sku=sku, price=0,
                        displayed=False, reason="out_of_stock")

    # 외부 최저가 사용
    min_external = min(usable_external_prices)

    use_formula = pricing.get("use_margin_formula_for_external_effective", False)
    if use_formula:
        margin = pricing.get("external_coupang_margin_effective", {})
        margin_rate = margin.get("value", 0.1242) if margin.get("mode") == "rate" else 0.0
        primary = _formula_price(min_external, fee_rate, margin_rate, delivery_fee)
        primary_reason = "external_formula"
    else:
        primary = pricing.get("external_coupang_price_effective", 128900)
        primary_reason = "external_fixed"

    wm = apply_winner_match(
        primary_price=primary,
        primary_reason=primary_reason,
        winner_price=winner_price,
        competitor_status=competitor,
    )
    return Decision(market="coupang", canonical_sku=sku,
                    price=round_to_unit(wm.price, rounding_unit),
                    displayed=True, reason=wm.reason)
