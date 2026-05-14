"""[B] 메인 진입점.

[A] 출력 + GlobalSettings → 마켓별 가격 결정 + 알림 배열.
"""
from collections import defaultdict
from .ss_decide import decide_ss
from .coupang_decide import decide_coupang
from .guardrail import check_external_price


def run_pricing_engine(
    a_output: dict[str, dict],
    settings: dict,
) -> dict:
    """[A] 출력 → 마켓별 결정 + 알림.

    settings 형식:
      {ss_fee_rate, coupang_fee_rate, delivery_fee, rounding_unit}

    반환:
      {
        "decisions": { canonical_sku: {ss: {price, displayed, reason},
                                       coupang: {...}} },
        "alerts": [...]
      }
    """
    options = list(a_output.values())
    ss_fee = settings.get("ss_fee_rate", 0.06)
    coupang_fee = settings.get("coupang_fee_rate", 0.1155)
    delivery_fee = settings.get("delivery_fee", 3000)
    rounding_unit = settings.get("rounding_unit", 100)

    # SS — 색상별 통일 처리
    ss_decisions = decide_ss(
        options, fee_rate=ss_fee, delivery_fee=delivery_fee,
        rounding_unit=rounding_unit,
    )
    ss_by_sku = {d.canonical_sku: d for d in ss_decisions}

    # 쿠팡 — 옵션별 처리 + 알림 수집
    alerts: list[dict] = []
    coupang_by_sku: dict = {}

    for opt in options:
        sku = opt["canonical_sku"]

        # 가드레일 알림 별도 수집 (decision의 부수효과로 발생하지만 명시적으로 한 번 더)
        for src in opt.get("sources", []):
            gr = check_external_price(
                external_price=src["price"],
                guardrail_lower=opt["pricing"].get("guardrail_lower_effective", 99000),
                guardrail_upper=opt["pricing"].get("guardrail_upper_effective", 120000),
                canonical_sku=sku,
                source=src["name"],
            )
            if gr.alert:
                alerts.append(gr.alert)

        c = decide_coupang(
            opt, fee_rate=coupang_fee, delivery_fee=delivery_fee,
            rounding_unit=rounding_unit,
        )
        coupang_by_sku[sku] = c

    # 머지
    decisions: dict = {}
    for sku in a_output.keys():
        ss_d = ss_by_sku.get(sku)
        c_d = coupang_by_sku.get(sku)
        decisions[sku] = {
            "ss": {
                "price": ss_d.price if ss_d else 0,
                "displayed": ss_d.displayed if ss_d else False,
                "reason": ss_d.reason if ss_d else "out_of_stock",
                "color_group_unified_at": ss_d.color_group_unified_at if ss_d else None,
            },
            "coupang": {
                "price": c_d.price if c_d else 0,
                "displayed": c_d.displayed if c_d else False,
                "reason": c_d.reason if c_d else "out_of_stock",
            },
        }

    # 알림 dedup (같은 sku+source+type 중복 제거)
    seen = set()
    deduped = []
    for a in alerts:
        key = (a.get("canonical_sku"), a.get("source"), a.get("type"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(a)

    return {"decisions": decisions, "alerts": deduped}
