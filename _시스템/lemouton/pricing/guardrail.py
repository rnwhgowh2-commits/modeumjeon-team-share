"""가드레일 검증."""
from dataclasses import dataclass


@dataclass
class GuardrailResult:
    is_usable: bool
    alert: dict | None


def check_external_price(
    *,
    external_price: int,
    guardrail_lower: int,
    guardrail_upper: int,
    canonical_sku: str,
    source: str,
) -> GuardrailResult:
    if external_price < guardrail_lower:
        return GuardrailResult(
            is_usable=False,
            alert={
                "type": "low_price",
                "level": "info",
                "canonical_sku": canonical_sku,
                "source": source,
                "value": external_price,
                "threshold": guardrail_lower,
                "message": f"하한가 미달 ({external_price} < {guardrail_lower}) — 사입 기회 또는 에러",
            },
        )
    if external_price >= guardrail_upper:
        return GuardrailResult(
            is_usable=False,
            alert={
                "type": "high_price",
                "level": "info",
                "canonical_sku": canonical_sku,
                "source": source,
                "value": external_price,
                "threshold": guardrail_upper,
                "message": f"상한가 도달 ({external_price} >= {guardrail_upper}) — 외부 재고 0 처리",
            },
        )
    return GuardrailResult(is_usable=True, alert=None)
