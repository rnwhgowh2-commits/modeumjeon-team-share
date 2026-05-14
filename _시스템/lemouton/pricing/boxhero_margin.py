"""[I] 박스히어로 사입 마진 — 3계층 우선순위 해결 (R2 핵심).

ai-workflow STEP 7 Sprint 2 Task 2.6 ★★★

3계층 우선순위 (자체 = 박스히어로 사입):
  Option > Model > PriceTemplate

3계층 우선순위 (외부 = 소싱처 사입):
  Option > PriceTemplate (Model 단 ❌)

mode 종류:
  'rate'   — *100 정수 (예: 25.00% → 2500)
  'amount' — 원 (예: 30000 = +30,000원)

source_type:
  'self'     — 박스히어로 자체 사입
  'external' — 외부 소싱처 사입
"""
from __future__ import annotations

from typing import Optional, Tuple


def resolve_margin(option, model, template, source_type: str = 'self') -> Tuple[str, int, str]:
    """3계층 우선순위로 마진 mode·value 해결.

    Returns:
        (mode, value, source_layer) — source_layer = 'option'|'model'|'template'

    예외 발생 ❌. None 입력 시 template default 사용.
    """
    if source_type not in ('self', 'external'):
        raise ValueError(f"source_type must be 'self'|'external', got {source_type!r}")

    if source_type == 'self':
        # Layer 1: Option
        if option and option.option_boxhero_margin_mode and option.option_boxhero_margin_value is not None:
            return option.option_boxhero_margin_mode, option.option_boxhero_margin_value, 'option'
        # Layer 2: Model
        if model and model.boxhero_margin_mode_override and model.boxhero_margin_value_override is not None:
            return model.boxhero_margin_mode_override, model.boxhero_margin_value_override, 'model'
        # Layer 3: Template
        if template:
            return (
                template.boxhero_margin_mode_self or 'rate',
                template.boxhero_margin_value_self if template.boxhero_margin_value_self is not None else 2500,
                'template',
            )
        # Fallback default (template 없을 때)
        return 'rate', 2500, 'default'

    # external
    if option and option.option_external_margin_mode and option.option_external_margin_value is not None:
        return option.option_external_margin_mode, option.option_external_margin_value, 'option'
    if template:
        return (
            template.boxhero_margin_mode_external or 'rate',
            template.boxhero_margin_value_external if template.boxhero_margin_value_external is not None else 2000,
            'template',
        )
    return 'rate', 2000, 'default'


def apply_margin(purchase_price: int, mode: str, value: int) -> int:
    """매입가 + 마진 → 판매가 (정수 원, 반올림).

    mode='rate'   value=2500 → purchase * 1.25
    mode='amount' value=30000 → purchase + 30000
    """
    if purchase_price is None or purchase_price <= 0:
        return 0
    if mode == 'rate':
        return int(round(purchase_price * (1 + (value or 0) / 10000)))
    if mode == 'amount':
        return int(purchase_price + (value or 0))
    raise ValueError(f"mode must be 'rate'|'amount', got {mode!r}")


def compute_sale_price(option, model, template, source_type: str = 'self',
                       purchase_price_override: Optional[int] = None) -> dict:
    """옵션 매트릭스 셀 계산 — 매입가 + 3계층 마진 → 최종 판매가.

    Args:
        option: Option ORM (필수, boxhero_avg_purchase_price 사용)
        model: Model ORM (자체 사입 model 오버라이드 lookup)
        template: PriceTemplate ORM (default 마진)
        source_type: 'self' | 'external'
        purchase_price_override: 외부 사입 시 다른 매입가 (옵션)

    Returns:
        {
          'purchase_price': int,
          'mode': 'rate'|'amount',
          'value': int,
          'source_layer': 'option'|'model'|'template'|'default',
          'sale_price': int,
          'margin_amount': int,  # sale - purchase
        }
    """
    if purchase_price_override is not None:
        purchase = purchase_price_override
    else:
        purchase = (option.boxhero_avg_purchase_price or 0) if option else 0

    mode, value, layer = resolve_margin(option, model, template, source_type)
    sale = apply_margin(purchase, mode, value)

    return {
        'purchase_price': purchase,
        'mode': mode,
        'value': value,
        'source_layer': layer,
        'sale_price': sale,
        'margin_amount': sale - purchase if sale > 0 else 0,
    }
