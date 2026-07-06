# -*- coding: utf-8 -*-
"""쿠팡 주문·송장 API 래퍼 (공식 엔드포인트 기반 thin wrapper).

공식 엔드포인트 (2026-04-23 확인):
- 주문 조회:   GET  /v4/vendors/{vendorId}/ordersheets?createdAtFrom=...&createdAtTo=...
- 주문 상세:   GET  /v4/vendors/{vendorId}/ordersheets/{orderSheetId}
- 송장 전송:   POST /v4/vendors/{vendorId}/orders/{shipmentBoxId}/ordersheets/invoices (배송처리)

Rate limit 및 인증은 CoupangClient 가 처리. 이 모듈은 body/query 매핑만.
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Optional

from shared.platforms.coupang.client import CoupangClient


_VENDOR_ID_ENV = "COUPANG_VENDOR_ID"


def _vendor_id() -> str:
    vid = os.getenv(_VENDOR_ID_ENV, "")
    if not vid:
        raise ValueError(f"{_VENDOR_ID_ENV} 미설정")
    return vid


def fetch_orders(since: datetime, until: datetime,
                  client: Optional[CoupangClient] = None,
                  status: Optional[str] = None,
                  max_per_page: int = 50,
                  next_token: Optional[str] = None) -> dict:
    """발주서 목록 조회(일단위 페이징). 생성일 기준. status 필수(공식).

    공식 스펙(developers.coupangcorp.com, GET_ORDERSHEET, 2026-07-07 실측): v5.
    status ∈ ACCEPT/INSTRUCT/DEPARTURE/DELIVERING/FINAL_DELIVERY/NONE_TRACKING.
    페이징: 응답 nextToken 을 다음 요청 next_token 으로. 최대 31일.

    Returns: {"code","message","data":[...발주서...],"nextToken":"..."}
    """
    vid = _vendor_id()
    client = client or CoupangClient()
    path = f"/v2/providers/openapi/apis/api/v5/vendors/{vid}/ordersheets"
    params = {
        "createdAtFrom": since.strftime("%Y-%m-%dT%H:%M:%S"),
        "createdAtTo":   until.strftime("%Y-%m-%dT%H:%M:%S"),
        "maxPerPage":    max_per_page,
    }
    if status:
        params["status"] = status
    if next_token:
        params["nextToken"] = next_token
    return client.request("GET", path, query=params)


def fetch_order_detail(order_sheet_id: str,
                       client: Optional[CoupangClient] = None) -> dict:
    """주문 상세 조회."""
    vid = _vendor_id()
    client = client or CoupangClient()
    path = f"/v2/providers/openapi/apis/api/v4/vendors/{vid}/ordersheets/{order_sheet_id}"
    return client.request("GET", path)


def send_tracking(shipment_box_id: str, order_sheet_id: str,
                   delivery_company_code: str, invoice_number: str,
                   client: Optional[CoupangClient] = None) -> dict:
    """송장 전송 (배송처리).

    Args:
        shipment_box_id: 묶음배송 번호 (쿠팡 고유)
        order_sheet_id:  주문 id
        delivery_company_code: 택배사 코드 (예: CJGLS)
        invoice_number:  운송장 번호
    """
    vid = _vendor_id()
    client = client or CoupangClient()
    path = (f"/v2/providers/openapi/apis/api/v4/vendors/{vid}"
            f"/orders/{shipment_box_id}/ordersheets/invoices")
    body = {
        "vendorId": vid,
        "orderSheetId": order_sheet_id,
        "deliveryCompanyCode": delivery_company_code,
        "invoiceNumber": invoice_number,
    }
    return client.request("POST", path, body=body)
