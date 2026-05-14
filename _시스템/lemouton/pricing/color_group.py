"""SS 색상 단위 가격 통일.

사용자 정책 (spec §5.2):
- 색상 내 사입품 ≥ 1 → 사입품 사이즈만 노출, 가격=사입품 SS 고정가
- 색상 내 사입품 = 0 → 모델 최저 소싱처 1곳 → 그 소싱처 재고 사이즈만 노출,
  가격=external_ss_price (또는 마진 공식)
- lemouton_only 사이즈 → SS 미노출
- 옵션 단위 오버라이드 → 색상 그룹 전체에 강제 통일
"""
from collections import defaultdict
from .models import Decision
from .guardrail import check_external_price
from .rounding import round_to_unit


def _formula_price(unit_price, fee_rate, margin_rate, delivery_fee):
    denom = 1.0 - fee_rate - margin_rate
    if denom <= 0:
        raise ValueError("invalid denom")
    return int((unit_price + delivery_fee) / denom)


def decide_ss_color_group(
    options: list[dict],
    *,
    fee_rate: float = 0.06,
    delivery_fee: int = 3000,
    rounding_unit: int = 100,
) -> list[Decision]:
    """단일 (모델, 색상) 그룹의 SS 결정.
    options: 같은 model_code + color_code 인 옵션 리스트.
    """
    if not options:
        return []

    # 0. 옵션 오버라이드 검사 (한 옵션이라도 있으면 색상 전체 통일)
    override_price = None
    for opt in options:
        ovr = opt.get("pricing", {}).get("option_ss_price_override")
        if ovr is not None:
            override_price = ovr
            break

    if override_price is not None:
        return [
            Decision(
                market="ss",
                canonical_sku=opt["canonical_sku"],
                price=round_to_unit(override_price, rounding_unit),
                displayed=not opt.get("lemouton_only", False),
                reason="option_override" if not opt.get("lemouton_only", False)
                       else "lemouton_only_blocked",
                color_group_unified_at=override_price,
            )
            for opt in options
        ]

    # 1. 색상 내 사입품 합계 (lemouton_only 옵션 제외, SS는 lemouton_only 미노출)
    color_boxhero_total = sum(
        opt.get("boxhero_stock", 0)
        for opt in options
        if not opt.get("lemouton_only", False)
    )

    if color_boxhero_total >= 1:
        # 사입품 모드 — 사입품 사이즈만 노출
        ref_pricing = options[0]["pricing"]
        unified_price = ref_pricing.get("boxhero_ss_price_effective", 115900)
        unified_price = round_to_unit(unified_price, rounding_unit)
        results = []
        for opt in options:
            if opt.get("lemouton_only", False):
                results.append(Decision(
                    market="ss", canonical_sku=opt["canonical_sku"],
                    price=0, displayed=False,
                    reason="lemouton_only_blocked",
                    color_group_unified_at=unified_price))
            elif opt.get("boxhero_stock", 0) >= 1:
                results.append(Decision(
                    market="ss", canonical_sku=opt["canonical_sku"],
                    price=unified_price, displayed=True,
                    reason="boxhero_mode",
                    color_group_unified_at=unified_price))
            else:
                results.append(Decision(
                    market="ss", canonical_sku=opt["canonical_sku"],
                    price=0, displayed=False,
                    reason="out_of_stock",
                    color_group_unified_at=unified_price))
        return results

    # 2. 색상 내 사입품 = 0 → 모델 최저 소싱처 1곳 선정
    # 가드레일 통과한 소싱처 가격 집계 (모델별로 다른 가격 모음)
    source_prices = defaultdict(list)  # source_name → [prices]
    source_alerts = []
    for opt in options:
        for src in opt.get("sources", []):
            gr = check_external_price(
                external_price=src["price"],
                guardrail_lower=opt["pricing"].get("guardrail_lower_effective", 99000),
                guardrail_upper=opt["pricing"].get("guardrail_upper_effective", 120000),
                canonical_sku=opt["canonical_sku"],
                source=src["name"],
            )
            if gr.alert:
                source_alerts.append(gr.alert)
            if gr.is_usable:
                source_prices[src["name"]].append(src["price"])

    if not source_prices:
        # 어떤 소싱처도 가드레일 통과 못 함
        return [
            Decision(
                market="ss", canonical_sku=opt["canonical_sku"],
                price=0, displayed=False,
                reason="lemouton_only_blocked" if opt.get("lemouton_only") else "out_of_stock",
            )
            for opt in options
        ]

    # 모델 최저 소싱처 = 평균(또는 최저) 가격이 제일 낮은 곳
    # 사용자 명시: "동일 소싱처 내 동일 모델 가격 단일" → 첫 가격 또는 set 내 한 값
    cheapest_source = min(source_prices.keys(),
                          key=lambda s: min(source_prices[s]))

    # 가격 결정 — 마진 공식 또는 고정가
    ref_pricing = options[0]["pricing"]
    if ref_pricing.get("use_margin_formula_for_external_effective", False):
        margin = ref_pricing.get("external_ss_margin_effective", {})
        margin_rate = margin.get("value", 0.0945) if margin.get("mode") == "rate" else 0.0
        unit_price = min(source_prices[cheapest_source])
        unified_price = _formula_price(unit_price, fee_rate, margin_rate, delivery_fee)
        primary_reason = "external_formula"
    else:
        unified_price = ref_pricing.get("external_ss_price_effective", 128900)
        primary_reason = "external_fixed"

    unified_price = round_to_unit(unified_price, rounding_unit)

    # 3. 그 소싱처에 재고 있는 사이즈만 노출
    results = []
    for opt in options:
        if opt.get("lemouton_only", False):
            results.append(Decision(
                market="ss", canonical_sku=opt["canonical_sku"],
                price=0, displayed=False,
                reason="lemouton_only_blocked",
                color_group_unified_at=unified_price))
            continue
        # cheapest_source의 재고가 있는지 확인
        has_stock = any(
            src["name"] == cheapest_source and src.get("stock", 0) >= 1
            for src in opt.get("sources", [])
        )
        if has_stock:
            results.append(Decision(
                market="ss", canonical_sku=opt["canonical_sku"],
                price=unified_price, displayed=True,
                reason=primary_reason,
                color_group_unified_at=unified_price))
        else:
            results.append(Decision(
                market="ss", canonical_sku=opt["canonical_sku"],
                price=0, displayed=False,
                reason="out_of_stock",
                color_group_unified_at=unified_price))
    return results
