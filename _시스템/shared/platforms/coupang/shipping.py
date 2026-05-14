# -*- coding: utf-8 -*-
"""
쿠팡 출고지·반품지 조회 래퍼 (읽기 전용)

상품 생성 전 필수 마스터 데이터:
- outboundShippingPlaceCode (출고지 코드, Number)
- returnCenterCode (반품지 센터코드, String)
- deliveryCompanyCode (택배사 코드)

공식 엔드포인트:
- 출고지: GET /v2/providers/marketplace_openapi/apis/api/v2/vendor/shipping-place/outbound
- 반품지: GET /v2/providers/openapi/apis/api/v5/vendors/{vendorId}/returnShippingCenters
"""
from __future__ import annotations

import logging
from typing import List, Optional

from shared.platforms import COUPANG
from shared.platforms.coupang.client import CoupangClient, CoupangAPIError


logger = logging.getLogger(__name__)


def list_outbound_places(
    client: Optional[CoupangClient] = None,
    page_size: int = 50,
) -> List[dict]:
    """등록된 출고지 목록 조회.

    Returns:
        [{outboundShippingPlaceCode, shippingPlaceName, placeAddresses, usable, ...}]
    """
    client = client or CoupangClient()
    path = COUPANG["paths"]["outbound_places"]
    query = f"pageNum=1&pageSize={page_size}"

    try:
        resp = client.request(method="GET", path=path, query=query)
    except CoupangAPIError as e:
        logger.warning("출고지 조회 실패: %s", e)
        return []

    return list(resp.get("content") or [])


def list_return_centers(
    client: Optional[CoupangClient] = None,
    page_size: int = 50,
) -> List[dict]:
    """등록된 반품지 목록 조회.

    Returns:
        [{returnCenterCode, shippingPlaceName, deliverCode, placeAddresses, usable, ...}]
    """
    client = client or CoupangClient()
    vendor_id = COUPANG["vendor_id"]
    path = COUPANG["paths"]["return_centers"].format(vendorId=vendor_id)
    query = f"pageNum=1&pageSize={page_size}"

    try:
        resp = client.request(method="GET", path=path, query=query)
    except CoupangAPIError as e:
        logger.warning("반품지 조회 실패: %s", e)
        return []

    data = resp.get("data") or {}
    return list(data.get("content") or [])


# 쿠팡 공식 택배사 코드 (자주 쓰는 것만)
# 전체 목록: https://developers.coupangcorp.com/hc/ko/articles/360034156033
DELIVERY_COMPANY_CODES = {
    "CJ대한통운": "CJGLS",
    "한진택배":   "HANJIN",
    "롯데택배":   "LOTTE",
    "우체국택배": "EPOST",
    "로젠택배":   "KGB",
    "대신택배":   "DAESIN",
    "경동택배":   "KDEXP",
    "건영택배":   "KUNYOUNG",
    "합동택배":   "HDEXP",
    "일양로지스": "ILYANG",
    "천일택배":   "CHUNIL",
}
