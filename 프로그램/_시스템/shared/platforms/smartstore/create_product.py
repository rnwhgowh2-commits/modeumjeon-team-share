# -*- coding: utf-8 -*-
"""
스마트스토어 상품 등록 + 삭제 (live API 검증 완료, 2026-04-22).

공식 엔드포인트:
    POST   /external/v2/products                    (등록)
    DELETE /external/v2/products/origin-products/{originProductNo}  (삭제)

주의:
- 등록 요청 body 의 statusType 은 서버가 무시하고 항상 SALE 로 등록.
  draft 효과를 원하면 등록 직후 change_status.mark_suspension() 호출 필수.
- 이미지 URL 은 Naver CDN (shop-phinf.pstatic.net) 만 허용. 외부 URL 거부됨.
- SHOES 카테고리의 productInfoProvidedNotice 는 7개 필수 필드 + SHOES enum.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from shared.platforms.smartstore.client import (
    SmartStoreClient, SmartStoreAPIError, SmartStoreRateLimitError,
)

logger = logging.getLogger(__name__)


@dataclass
class ShoesNotice:
    """SHOES 카테고리 상품정보제공고시 (7 필수 필드)."""
    material: str
    color: str
    size: str
    manufacturer: str
    caution: str
    warranty_policy: str
    after_service_director: str

    def to_body(self) -> dict:
        return {
            "material": self.material,
            "color": self.color,
            "size": self.size,
            "manufacturer": self.manufacturer,
            "caution": self.caution,
            "warrantyPolicy": self.warranty_policy,
            "afterServiceDirector": self.after_service_director,
        }


@dataclass
class ProductRegistration:
    """상품 등록 요청 필수 필드 모음 (SHOES 카테고리 기준).

    다른 카테고리는 productInfoProvidedNotice 구조가 달라 현 dataclass 로 대응 어려움.
    필요 시 category-specific dataclass 추가.
    """
    leaf_category_id: str
    name: str
    sale_price: int
    stock_quantity: int
    image_url: str                       # Naver CDN URL 필수
    detail_content_html: str
    shoes_notice: ShoesNotice
    origin_area_code: str = "0200037"
    importer: str = ""
    minor_purchasable: bool = True
    after_service_phone: str = ""
    after_service_guide: str = ""

    def to_body(self) -> dict:
        return {
            "originProduct": {
                "statusType": "SUSPENSION",  # 서버는 무시하고 SALE 로 등록
                "leafCategoryId": str(self.leaf_category_id),
                "name": self.name,
                "salePrice": int(self.sale_price),
                "stockQuantity": int(self.stock_quantity),
                "images": {"representativeImage": {"url": self.image_url}},
                "detailContent": self.detail_content_html,
                "detailAttribute": {
                    "originAreaInfo": {
                        "originAreaCode": self.origin_area_code,
                        "importer": self.importer or "-",
                    },
                    "minorPurchasable": bool(self.minor_purchasable),
                    "afterServiceInfo": {
                        "afterServiceTelephoneNumber": self.after_service_phone or "02-0000-0000",
                        "afterServiceGuideContent": self.after_service_guide or "고객센터 문의",
                    },
                    "productInfoProvidedNotice": {
                        "productInfoProvidedNoticeType": "SHOES",
                        "shoes": self.shoes_notice.to_body(),
                    },
                },
            },
            "smartstoreChannelProduct": {
                "channelProductDisplayStatusType": "ON",
                "naverShoppingRegistration": True,
            },
        }


@dataclass
class CreateResult:
    success: bool
    origin_product_no: Optional[int] = None
    channel_product_no: Optional[int] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    invalid_inputs: List[dict] = field(default_factory=list)
    raw_response: dict = field(default_factory=dict)


def create_product(
    reg: ProductRegistration,
    client: Optional[SmartStoreClient] = None,
    auto_suspend: bool = True,
) -> CreateResult:
    """상품 등록 + (기본) 즉시 SUSPENSION 전환 (draft 효과).

    Args:
        reg: ProductRegistration 데이터
        client: SmartStoreClient
        auto_suspend: True 면 등록 직후 change_status.mark_suspension() 호출 (권장)

    Returns:
        CreateResult
    """
    # [안전 게이트 2026-06-13] 0/음수/비정상 판매가 라이브 등록(POST) 차단.
    from shared.platforms.price_guard import assert_live_sale_price
    assert_live_sale_price(reg.sale_price, context=f"smartstore create_product name={reg.name!r}")
    client = client or SmartStoreClient()
    path = client.path_for("create_product")
    body = reg.to_body()

    try:
        resp = client.request(method="POST", path=path, body=body)
    except SmartStoreRateLimitError:
        raise
    except SmartStoreAPIError as e:
        iis = e.payload.get("invalidInputs", []) if isinstance(e.payload, dict) else []
        return CreateResult(
            success=False,
            error_code=e.code,
            error_message=e.message,
            invalid_inputs=iis,
        )

    origin_no = resp.get("originProductNo")
    channel_no = resp.get("smartstoreChannelProductNo")

    if auto_suspend and origin_no:
        try:
            from shared.platforms.smartstore.change_status import mark_suspension
            sus = mark_suspension(int(origin_no), client=client)
            if not sus.success:
                logger.warning("자동 SUSPENSION 전환 실패: %s %s",
                               sus.error_code, sus.error_message)
        except Exception as e:
            logger.exception("자동 SUSPENSION 중 예외: %s", e)

    return CreateResult(
        success=True,
        origin_product_no=int(origin_no) if origin_no else None,
        channel_product_no=int(channel_no) if channel_no else None,
        raw_response=resp,
    )


def delete_origin_product(
    origin_product_no: int,
    client: Optional[SmartStoreClient] = None,
) -> bool:
    """원상품 영구 삭제 (복구 불가).

    사용 전 반드시 SUSPENSION 또는 OUTOFSTOCK 상태 확인 권장.

    Returns:
        True 성공, False 실패
    """
    if not origin_product_no or int(origin_product_no) <= 0:
        raise ValueError(f"origin_product_no 양의 정수 (입력: {origin_product_no})")

    client = client or SmartStoreClient()
    path = client.path_for("delete_origin_product", originProductNo=origin_product_no)

    try:
        resp = client.request(method="DELETE", path=path)
    except SmartStoreAPIError as e:
        logger.warning("상품 삭제 실패 origin=%s: %s %s",
                       origin_product_no, e.code, e.message)
        return False

    return bool(resp.get("data"))
