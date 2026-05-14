# -*- coding: utf-8 -*-
"""
쿠팡 재고 변경 API 래퍼

공식 엔드포인트 (https://developers.coupangcorp.com/hc/ko/articles/360034156253):
    PUT /v2/providers/seller_api/apis/api/v1/marketplace/vendor-items/{vendorItemId}/quantities/{quantity}
    body 없음

역할:
- 옵션 단위(vendorItemId) 재고 변경
- 실패 시 False 반환 (예외 전파 X) → 이전값 유지는 호출자 책임

제약:
- quantity >= 0 (0 = 품절)
- vendor_item_id > 0
- 호출 전 validator.py 검증 통과 필수 (호출자 책임)
"""
from __future__ import annotations

import logging
from typing import Optional

from shared.platforms import COUPANG
from shared.platforms.coupang.client import CoupangClient, CoupangAPIError


logger = logging.getLogger(__name__)


def update_quantity(
    vendor_item_id: int,
    quantity: int,
    client: Optional[CoupangClient] = None,
) -> bool:
    """옵션 재고를 변경한다.

    Args:
        vendor_item_id: 쿠팡 옵션 ID (vendorItemId)
        quantity: 변경할 재고 수량 (0 이상)
        client: 주입받은 CoupangClient. None 이면 기본 생성.

    Returns:
        True  성공
        False API 실패 (이전값 유지 필요)

    Raises:
        ValueError: 입력 검증 실패
    """
    if not vendor_item_id or int(vendor_item_id) <= 0:
        raise ValueError("vendor_item_id 는 양의 정수여야 합니다")
    if quantity < 0:
        raise ValueError(f"quantity 는 0 이상이어야 합니다 (입력: {quantity})")

    path_tpl = COUPANG["paths"]["update_quantity"]
    path = path_tpl.format(vendorItemId=vendor_item_id, quantity=quantity)

    client = client or CoupangClient()
    try:
        resp = client.request(method="PUT", path=path)
    except CoupangAPIError as e:
        logger.warning(
            "재고 변경 실패 vendor_item_id=%s quantity=%s status=%s msg=%s",
            vendor_item_id, quantity, e.status_code, e.message,
        )
        return False

    return resp.get("code") == "SUCCESS"
