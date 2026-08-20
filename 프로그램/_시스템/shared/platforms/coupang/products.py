# -*- coding: utf-8 -*-
"""
쿠팡 상품 생성/조회 API 래퍼

책임:
- POST seller-products — 상품 등록 페이로드를 받아 호출, sellerProductId 반환
- GET  seller-products/{id} — 등록 후 상세 조회 (vendorItemId 수집용)

주의:
- 검증·페이로드 빌드는 builder.py 에서 담당
- validator.py 통과 후에만 호출하는 것이 원칙
"""
from __future__ import annotations

import logging
from typing import Optional

from shared.platforms import COUPANG
from shared.platforms.coupang.client import CoupangClient, CoupangAPIError


logger = logging.getLogger(__name__)


class ProductCreationError(Exception):
    """상품 생성 실패."""
    def __init__(self, message: str, payload: Optional[dict] = None):
        super().__init__(message)
        self.message = message
        self.payload = payload or {}


def create_product(
    payload: dict,
    client: Optional[CoupangClient] = None,
) -> int:
    """상품 생성 API 호출.

    Returns:
        등록된 sellerProductId (성공 시)

    Raises:
        ProductCreationError: 등록 실패 (에러 상세는 rc.payload 에 포함)
    """
    client = client or CoupangClient()
    path = COUPANG["paths"]["create_product"]

    try:
        resp = client.request(method="POST", path=path, body=payload)
    except CoupangAPIError as e:
        raise ProductCreationError(
            f"HTTP {e.status_code}: {e.message}",
            payload=e.payload,
        ) from e

    code = resp.get("code")
    data = resp.get("data")
    if code == "SUCCESS" and isinstance(data, int):
        return data

    # 쿠팡은 errorItems 로 실패 원인 상세 제공
    raise ProductCreationError(
        message=f"code={code} msg={resp.get('message') or ''} details={resp.get('details') or ''}",
        payload=resp,
    )


def get_product(
    seller_product_id: int,
    client: Optional[CoupangClient] = None,
) -> dict:
    """등록된 상품 상세 조회 (items[] 에 vendorItemId 포함)."""
    client = client or CoupangClient()
    path = COUPANG["paths"]["get_product"].format(sellerProductId=seller_product_id)
    resp = client.request(method="GET", path=path)
    return resp.get("data") or {}


def extract_display_category_code(detail) -> Optional[str]:
    """[2026-07-23 M3 Task 6] 상품 상세(get_product 반환)에서 전시 카테고리 코드를 꺼낸다.

    등록할 때 우리가 고른 `displayCategoryCode` 가 상세 응답에 그대로 실려 온다 — 이미
    받아오면서 버리던 값이라 **읽기만** 추가한다(get_product 의 반환 계약은 그대로 dict).
    맵핑 회수(observed_map)가 '추측이 아닌 실적'의 근거로 쓴다.

    없거나 0(=코드 아님)이면 None — 0/빈 문자열로 날조하지 않는다.
    """
    if not isinstance(detail, dict):
        return None
    code = detail.get("displayCategoryCode")
    if code in (None, "", 0, "0"):
        return None
    return str(code).strip() or None


def extract_vendor_items(detail: dict) -> list[dict]:
    """상품 상세의 items[] 에서 marketplaceItemData.vendorItemId 추출.

    Returns:
        [{"item_name": ..., "vendor_item_id": ..., "seller_product_item_id": ...,
          "sale_price": ..., "max_buy_count": ..., "color": ..., "size": ...}]
    """
    result = []
    for item in detail.get("items") or []:
        mp = item.get("marketplaceItemData") or {}
        # 실 GET 응답은 vendorItemId/salePrice 가 item 최상위. 구버전(mp 중첩) 폴백.
        vid = item.get("vendorItemId") or mp.get("vendorItemId")
        if not vid:
            continue
        price_data = mp.get("priceData") or {}
        sale = item.get("salePrice")
        if sale is None:
            sale = price_data.get("salePrice")

        # attributes 에서 색상·사이즈 추출
        color, size = "", ""
        for attr in item.get("attributes") or []:
            type_name = (attr.get("attributeTypeName") or "").strip()
            value = (attr.get("attributeValueName") or "").strip()
            if not value:
                continue
            if "색상" in type_name and not color:
                color = value
            elif "사이즈" in type_name and not size:
                size = value

        result.append({
            "item_name": item.get("itemName"),
            "vendor_item_id": vid,
            "seller_product_item_id": item.get("sellerProductItemId") or mp.get("sellerProductItemId"),
            "sale_price": sale,
            "max_buy_count": item.get("maximumBuyCount") or mp.get("maximumBuyCount"),
            "color": color,
            "size":  size,
        })
    return result
