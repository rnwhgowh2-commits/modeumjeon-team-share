# -*- coding: utf-8 -*-
"""스마트스토어 (네이버 커머스) 주문·CS API thin wrapper.

공식 엔드포인트 (v2.76.0 기준, 2026-04-23 확인):
- 주문 목록:   GET  /v1/pay-order/seller/product-orders (startDate/endDate/searchType/pageSize/pageNumber)
- 주문 상세:   POST /v1/pay-order/seller/product-orders/query (productOrderIds[])
- 발송/송장:   POST /v1/pay-order/seller/product-orders/dispatch (productOrderIds[], shippingCompany, trackingNumber)
- 문의 목록:   GET  /v1/pay-user/inquiries (startDate/inquiryStatus/pageSize/pageNumber)
- 문의 답변:   POST /v1/pay-merchant/inquiries/{inquiryNo}/answer (answerContent)
- 클레임:      POST /v1/pay-order/seller/product-orders/{productOrderId}/claim/{type}/{action}

인증·rate limit·재시도 는 SmartStoreClient 가 처리. 이 모듈은 body/query 매핑만.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional
from urllib.parse import urlencode

from shared.platforms.smartstore.client import SmartStoreClient


def _q(params: dict) -> str:
    return urlencode({k: v for k, v in params.items() if v is not None})


def fetch_orders(since: datetime, until: datetime,
                  client: Optional[SmartStoreClient] = None,
                  search_type: str = "PAYED",
                  page_size: int = 100,
                  page_number: int = 1) -> dict:
    """기간별 주문 목록 조회.

    searchType 기본 PAYED (결제완료). DISPATCHED/DELIVERED 등도 가능.
    """
    client = client or SmartStoreClient()
    return client.request(
        method="GET",
        path="/external/v1/pay-order/seller/product-orders",
        query=_q({
            "startDate":  since.strftime("%Y-%m-%dT%H:%M:%S.000+09:00"),
            "endDate":    until.strftime("%Y-%m-%dT%H:%M:%S.000+09:00"),
            "searchType": search_type,
            "pageSize":   page_size,
            "pageNumber": page_number,
        }),
    )


def fetch_order_detail(product_order_ids: list[str],
                        client: Optional[SmartStoreClient] = None) -> dict:
    """주문 상세 조회 (최대 300개 한번에)."""
    if not product_order_ids:
        return {"data": []}
    client = client or SmartStoreClient()
    return client.request(
        method="POST",
        path="/external/v1/pay-order/seller/product-orders/query",
        body={"productOrderIds": product_order_ids[:300]},
    )


def send_tracking(product_order_ids: list[str], shipping_company: str,
                   tracking_number: str,
                   client: Optional[SmartStoreClient] = None,
                   shipping_date_ymd: Optional[str] = None) -> dict:
    """발송·송장 전송 (최대 30개 한번에, 동일 송장 번호 기준)."""
    client = client or SmartStoreClient()
    body = {
        "dispatchProductOrders": [{
            "productOrderId": pid,
            "shippingCompany": shipping_company,
            "trackingNumber":  tracking_number,
            "dispatchDate":    shipping_date_ymd
                               or datetime.now().strftime("%Y-%m-%dT%H:%M:%S.000+09:00"),
        } for pid in product_order_ids[:30]],
    }
    return client.request(
        method="POST",
        path="/external/v1/pay-order/seller/product-orders/dispatch",
        body=body,
    )


def fetch_inquiries(since: datetime,
                     client: Optional[SmartStoreClient] = None,
                     inquiry_status: str = "WAIT",
                     page_size: int = 100,
                     page_number: int = 1) -> dict:
    """고객 문의 조회. 기본 inquiryStatus=WAIT (답변 대기)."""
    client = client or SmartStoreClient()
    return client.request(
        method="GET",
        path="/external/v1/pay-user/inquiries",
        query=_q({
            "startDate":     since.strftime("%Y-%m-%dT%H:%M:%S.000+09:00"),
            "inquiryStatus": inquiry_status,
            "pageSize":      page_size,
            "pageNumber":    page_number,
        }),
    )


def reply_inquiry(inquiry_no: str, answer_content: str,
                   client: Optional[SmartStoreClient] = None) -> dict:
    """문의 답변 등록."""
    client = client or SmartStoreClient()
    return client.request(
        method="POST",
        path=f"/external/v1/pay-merchant/inquiries/{inquiry_no}/answer",
        body={"answerContent": answer_content},
    )


def handle_claim(product_order_id: str,
                  claim_type: Literal["cancel", "return", "exchange"],
                  action: Literal["request", "approve", "reject", "withdraw"],
                  reason_code: str = "",
                  reason_text: str = "",
                  client: Optional[SmartStoreClient] = None) -> dict:
    """취소/반품/교환 claim 처리.

    path: /v1/pay-order/seller/product-orders/{productOrderId}/claim/{type}/{action}
    """
    client = client or SmartStoreClient()
    body = {}
    if reason_code:
        body["requestReasonCode"] = reason_code
    if reason_text:
        body["requestReasonText"] = reason_text
    return client.request(
        method="POST",
        path=(f"/external/v1/pay-order/seller/product-orders/"
              f"{product_order_id}/claim/{claim_type}/{action}"),
        body=body,
    )
