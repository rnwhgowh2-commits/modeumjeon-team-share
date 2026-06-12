# -*- coding: utf-8 -*-
"""
스마트스토어 — 등록된 상품의 옵션별 가격(addPrice)·재고(stockQuantity) 변경.

공식 엔드포인트:
    PUT /external/v2/products/origin-products/{originProductNo}

Naver Commerce API 의 product edit 은 originProduct 전체를 그대로 다시 보내는 형식.
(GET 응답을 받은 뒤 변경분만 덮어써서 PUT) — partial body 는 reject.

호출 패턴:
    edit_options(
        origin_product_no=13153051689,
        sale_price=128900,
        option_updates={
            56632587351: {'stockQuantity': 5, 'price': 0},
            56632587353: {'stockQuantity': 10, 'price': 0},
            ...
        },
        client=...,
    )

옵션별 price 는 base salePrice 기준 add_price (delta) 임에 유의.
"""
from __future__ import annotations

import copy
import logging
from dataclasses import dataclass
from typing import Optional

from shared.platforms.smartstore.client import (
    SmartStoreClient, SmartStoreAPIError, SmartStoreRateLimitError,
)

logger = logging.getLogger(__name__)


@dataclass
class EditResult:
    success: bool
    origin_product_no: int
    options_changed: int = 0
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    invalid_inputs: Optional[list] = None


def edit_options(
    origin_product_no: int,
    *,
    sale_price: Optional[int] = None,
    option_updates: dict[int, dict] = None,
    immediate_discount: Optional[dict] = None,
    client: Optional[SmartStoreClient] = None,
) -> EditResult:
    """원상품의 salePrice + optionCombinations[*] + 즉시할인 변경.

    Args:
        origin_product_no: 원상품번호
        sale_price: 새 base salePrice (None 이면 현재값 유지)
        option_updates: {option_id: {'stockQuantity': int, 'price': int}}
        immediate_discount: 즉시할인 설정 (None 이면 현재값 유지). 형식:
            {'value': int, 'unitType': 'WON'|'PERCENT'}  → 절대 갱신
            {'value': 0}                                  → 즉시할인 제거
        client: SmartStoreClient

    Returns:
        EditResult
    """
    if origin_product_no is None or int(origin_product_no) <= 0:
        raise ValueError(f"origin_product_no 양의 정수 필요 (입력: {origin_product_no})")
    # [안전 게이트 2026-06-13] 0/음수/비정상 판매가 라이브 PUT 차단(송신 전 abort).
    #   sale_price=None 은 '현재값 유지'라 허용. shared/platforms/price_guard.
    if sale_price is not None:
        from shared.platforms.price_guard import assert_live_sale_price
        assert_live_sale_price(
            sale_price, context=f"smartstore edit_options origin={origin_product_no}")
    option_updates = option_updates or {}

    client = client or SmartStoreClient()

    # 1) 현재 product 조회
    get_path = f"/external/v2/products/origin-products/{origin_product_no}"
    try:
        current = client.request("GET", get_path)
    except SmartStoreAPIError as e:
        return EditResult(success=False, origin_product_no=origin_product_no,
                          error_code=e.code, error_message=f"GET 실패: {e.message}")

    body = copy.deepcopy(current) if isinstance(current, dict) else {}
    origin = body.get("originProduct") or {}
    if not origin:
        return EditResult(success=False, origin_product_no=origin_product_no,
                          error_code="NO_ORIGIN", error_message="originProduct missing")

    # 2) salePrice 변경
    if sale_price is not None:
        origin["salePrice"] = int(sale_price)

    # 2.5) 즉시할인 변경
    if immediate_discount is not None:
        cb = origin.get("customerBenefit") or {}
        idp = cb.get("immediateDiscountPolicy") or {}
        val = int(immediate_discount.get("value", 0))
        unit = immediate_discount.get("unitType", "WON")
        if val <= 0:
            cb.pop("immediateDiscountPolicy", None)
        else:
            idp["discountMethod"] = {"value": val, "unitType": unit}
            cb["immediateDiscountPolicy"] = idp
        origin["customerBenefit"] = cb

    # 3) optionCombinations 변경
    options_changed = 0
    detail = origin.get("detailAttribute") or {}
    opt_info = detail.get("optionInfo") or {}
    combinations = opt_info.get("optionCombinations") or []
    for c in combinations:
        oid = int(c.get("id") or 0)
        if oid in option_updates:
            upd = option_updates[oid]
            if "stockQuantity" in upd:
                c["stockQuantity"] = int(upd["stockQuantity"])
            if "price" in upd:
                c["price"] = int(upd["price"])
            options_changed += 1

    # 4) PUT
    put_path = get_path
    try:
        client.request("PUT", put_path, body=body)
    except SmartStoreRateLimitError:
        raise
    except SmartStoreAPIError as e:
        iis = e.payload.get("invalidInputs", []) if isinstance(e.payload, dict) else []
        return EditResult(
            success=False, origin_product_no=origin_product_no,
            error_code=e.code, error_message=e.message,
            invalid_inputs=iis,
        )

    return EditResult(
        success=True, origin_product_no=origin_product_no,
        options_changed=options_changed,
    )
