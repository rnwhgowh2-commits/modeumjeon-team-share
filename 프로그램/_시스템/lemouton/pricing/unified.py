"""통합 가격 계산기 — 모음전 시스템 가격 계산의 단일 진실 원천.

ai-workflow cycle 20260521 · Phase 1 · Task 1

문제:
  가격 계산이 3곳으로 흩어져 같은 옵션에 다른 가격이 나옴.
    ① 스케줄러 엔진 (pricing/engine.py) — 분모형 마진식
    ② 매트릭스 화면 (sourcing/models_pricing.py:calc_auto_price) — 곱셈형
    ③ 재고관리 (pricing/boxhero_margin.py:compute_sale_price) — rate/amount

해결:
  이 모듈의 compute_sale_price_unified() 하나로 통일.
  ①②③ 모두 이 함수를 경유하게 하여 "화면값 = 마켓 업로드값" 보장.

계산식 (사용자 확정 — 곱셈형):
    판매가 = 원가 × (1 + 마진율) × (1 + 수수료율) + 배송비

용어:
  · 원가(purchase_price): 혜택(적립·할인)이 모두 반영된 실매입가 (정수 원).
                          혜택 차감은 이 함수 호출 전에 끝나 있어야 함.
  · margin_rate / fee_rate: 소수 표기 (0.10 = 10%).
  · 라운딩: round_to_unit (floor 기반 round-half-up) — 전 경로 통일.
  · 가드레일: (하한, 상한). 벗어나면 status 로만 표시하고 가격은 그대로 산출한다.
             "그 소싱처를 후보에서 제외" 같은 판단은 호출자 몫.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .rounding import round_to_unit


@dataclass
class PriceResult:
    """통합 가격 계산 결과."""
    final_price: int                      # 최종 판매가 (정수 원)
    guardrail_status: str = 'none'         # 'ok' | 'below' | 'above' | 'none'
    breakdown: dict = field(default_factory=dict)   # 산출과정 표시용


def compute_sale_price_unified(
    purchase_price: int | None,
    margin_rate: float,
    fee_rate: float,
    shipping_fee: int = 0,
    rounding_unit: int = 100,
    guardrail: tuple[int, int] | None = None,
) -> PriceResult:
    """판매가 = 원가 × (1 + 마진율) × (1 + 수수료율) + 배송비.

    Args:
        purchase_price: 혜택 모두 반영된 실매입가 (원). 0 이하/None 이면 판매가 0.
        margin_rate: 마진율 소수 (0.10 = 10%).
        fee_rate: 마켓 수수료율 소수 (0.1155 = 11.55%).
        shipping_fee: 배송비 (원).
        rounding_unit: 끝자리 라운딩 단위 (기본 100원).
        guardrail: (하한, 상한). None 이면 검사 안 함.
                   final < 하한 → 'below' / final >= 상한 → 'above' / 그 외 'ok'.

    Returns:
        PriceResult(final_price, guardrail_status, breakdown)
    """
    purchase_price = int(purchase_price or 0)

    if purchase_price <= 0:
        return PriceResult(
            final_price=0,
            guardrail_status='none',
            breakdown={
                'purchase_price': 0, 'margin_rate': margin_rate,
                'fee_rate': fee_rate, 'shipping_fee': shipping_fee,
                'raw_total': 0.0, 'rounding_unit': rounding_unit,
                'final_price': 0, 'guardrail': guardrail,
                'guardrail_status': 'none',
            },
        )

    after_margin = purchase_price * (1 + margin_rate)
    after_fee = after_margin * (1 + fee_rate)
    raw = after_fee + shipping_fee
    final = round_to_unit(int(round(raw)), rounding_unit)

    status = 'none'
    if guardrail is not None:
        lower, upper = guardrail
        if final < lower:
            status = 'below'
        elif final >= upper:
            status = 'above'
        else:
            status = 'ok'

    breakdown = {
        'purchase_price': purchase_price,
        'margin_rate': margin_rate,
        'margin_amount': int(round(purchase_price * margin_rate)),
        'subtotal_after_margin': int(round(after_margin)),
        'fee_rate': fee_rate,
        'fee_amount': int(round(after_margin * fee_rate)),
        'subtotal_after_fee': int(round(after_fee)),
        'shipping_fee': shipping_fee,
        'raw_total': raw,
        'rounding_unit': rounding_unit,
        'final_price': final,
        'guardrail': guardrail,
        'guardrail_status': status,
    }
    return PriceResult(final_price=final, guardrail_status=status, breakdown=breakdown)
