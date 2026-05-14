# -*- coding: utf-8 -*-
"""
쿠팡 카테고리 API 래퍼

제공:
- predict(): 상품명/브랜드/속성 기반으로 displayCategoryCode 자동 추천
- get_meta(): 카테고리별 필수 속성·고시정보 템플릿 조회

공식:
- POST /v2/providers/openapi/apis/api/v1/categorization/predict
- GET  /v2/providers/openapi/apis/api/v1/categorization/meta-data/display-categories/{code}
"""
from __future__ import annotations

import logging
from typing import Optional

from shared.platforms import COUPANG
from shared.platforms.coupang.client import CoupangClient, CoupangAPIError


logger = logging.getLogger(__name__)


def predict(
    product_name: str,
    brand: Optional[str] = None,
    product_description: Optional[str] = None,
    attributes: Optional[dict] = None,
    seller_sku_code: Optional[str] = None,
    client: Optional[CoupangClient] = None,
) -> Optional[int]:
    """상품 정보로 쿠팡 카테고리 코드 추천.

    Returns:
        displayCategoryCode (int) 또는 None
    """
    client = client or CoupangClient()
    path = COUPANG["paths"]["category_predict"]
    body = {
        "productName": product_name,
        "productDescription": product_description or "",
        "brand": brand or "",
        "attributes": attributes or {},
        "sellerSkuCode": seller_sku_code or "",
    }

    try:
        resp = client.request(method="POST", path=path, body=body)
    except CoupangAPIError as e:
        logger.warning("카테고리 추천 실패: %s", e)
        return None

    data = resp.get("data") or {}
    if data.get("autoCategorizationPredictionResultType") != "SUCCESS":
        logger.info("카테고리 추천 비성공: %s", data.get("comment"))
        return None

    cid = data.get("predictedCategoryId")
    try:
        return int(cid) if cid else None
    except (ValueError, TypeError):
        return None


def get_meta(display_category_code: int, client: Optional[CoupangClient] = None) -> dict:
    """카테고리 메타정보 조회 — 필수 속성·고시정보·인증·구비서류 템플릿.

    Returns: 전체 data dict (attributes, noticeCategories, certifications 등)
    """
    client = client or CoupangClient()
    path = COUPANG["paths"]["category_meta"].format(
        displayCategoryCode=display_category_code,
    )
    try:
        resp = client.request(method="GET", path=path)
    except CoupangAPIError as e:
        logger.warning("카테고리 메타 조회 실패: %s", e)
        return {}
    return resp.get("data") or {}
