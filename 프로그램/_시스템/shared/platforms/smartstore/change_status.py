# -*- coding: utf-8 -*-
"""
스마트스토어 원상품 판매 상태 변경 (live API 검증 완료, 2026-04-22).

공식 엔드포인트:
    PUT /external/v1/products/origin-products/{originProductNo}/change-status

Body (live-verified):
    {"statusType": <enum>}

확정 enum (live round-trip 검증):
    - SALE        : 판매중
    - OUTOFSTOCK  : 품절 (단, 조합형 옵션 상품은 option_stock 로 stock=0 유도 필요)
    - SUSPENSION  : 판매중지

미확정 enum (docs JS 렌더로 값 미노출):
    - 판매종료 (CLOSE/ENDED 등 시도 실패) — 추후 UI 네트워크 관찰 필요

호출자 책임:
- 옵션 상품 품절은 option_stock.update_option_stock(stock_quantity=0) 사용
- 이 엔드포인트는 '원상품 전체' 상태 전환에 적합
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from shared.platforms.smartstore.client import (
    SmartStoreClient, SmartStoreAPIError, SmartStoreRateLimitError,
)

logger = logging.getLogger(__name__)


class SaleStatus(str, Enum):
    """판매 상태 enum (live-verified)."""
    SALE       = "SALE"
    OUTOFSTOCK = "OUTOFSTOCK"
    SUSPENSION = "SUSPENSION"


@dataclass
class StatusChangeResult:
    success: bool
    error_code: Optional[str] = None
    error_message: Optional[str] = None


def change_sale_status(
    origin_product_no: int,
    status: SaleStatus,
    client: Optional[SmartStoreClient] = None,
) -> StatusChangeResult:
    """원상품 판매 상태 변경.

    Args:
        origin_product_no: 원상품번호
        status: SaleStatus enum

    Returns:
        StatusChangeResult

    Raises:
        ValueError: 입력 검증 실패
        SmartStoreRateLimitError: 429 — 워커가 requeue 처리
    """
    if origin_product_no is None or int(origin_product_no) <= 0:
        raise ValueError(f"origin_product_no 양의 정수 (입력: {origin_product_no})")
    if not isinstance(status, SaleStatus):
        raise ValueError(f"status 는 SaleStatus enum (입력 타입: {type(status).__name__})")

    client = client or SmartStoreClient()
    path = client.path_for("change_sale_status", originProductNo=origin_product_no)
    body = {"statusType": status.value}

    try:
        client.request(method="PUT", path=path, body=body)
    except SmartStoreRateLimitError:
        raise
    except SmartStoreAPIError as e:
        logger.warning(
            "판매 상태 변경 실패 origin=%s status=%s code=%s msg=%s",
            origin_product_no, status.value, e.code, e.message,
        )
        return StatusChangeResult(success=False, error_code=e.code, error_message=e.message)

    return StatusChangeResult(success=True)


def mark_soldout(origin_product_no: int,
                 client: Optional[SmartStoreClient] = None) -> StatusChangeResult:
    """품절 처리 (주의: 조합형 옵션 상품은 option_stock.stock_quantity=0 로 대체)."""
    return change_sale_status(origin_product_no, SaleStatus.OUTOFSTOCK, client=client)


def mark_on_sale(origin_product_no: int,
                 client: Optional[SmartStoreClient] = None) -> StatusChangeResult:
    """판매 재개."""
    return change_sale_status(origin_product_no, SaleStatus.SALE, client=client)


def mark_suspension(origin_product_no: int,
                    client: Optional[SmartStoreClient] = None) -> StatusChangeResult:
    """판매 중지 (일시)."""
    return change_sale_status(origin_product_no, SaleStatus.SUSPENSION, client=client)
