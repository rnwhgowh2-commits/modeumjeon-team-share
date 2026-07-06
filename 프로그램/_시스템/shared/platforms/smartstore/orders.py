# -*- coding: utf-8 -*-
"""스마트스토어 (네이버 커머스) 주문·CS API thin wrapper.

공식 엔드포인트 (API 센터 실측 + 2026-07-07 실계정 검증):
- 주문 목록:   GET  /v1/pay-order/seller/product-orders/last-changed-statuses
               (lastChangedFrom REQUIRED · lastChangedTo · lastChangedType · limitCount · moreSequence)
               ※ 조회 기준=변경 일시. 300개 초과 시 data.more(moreFrom·moreSequence)로 이어받기.
- 주문 상세:   POST /v1/pay-order/seller/product-orders/query (productOrderIds[] 최대 300)
- 발송/송장:   POST /v1/pay-order/seller/product-orders/dispatch (productOrderIds[], shippingCompany, trackingNumber)
- 문의 목록:   GET  /v1/pay-user/inquiries (startDate/inquiryStatus/pageSize/pageNumber)
- 문의 답변:   POST /v1/pay-merchant/inquiries/{inquiryNo}/answer (answerContent)
- 클레임:      POST /v1/pay-order/seller/product-orders/{productOrderId}/claim/{type}/{action}

인증·rate limit·재시도 는 SmartStoreClient 가 처리. 이 모듈은 body/query 매핑만.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal, Optional
from urllib.parse import urlencode

from shared.platforms.smartstore.client import SmartStoreClient


def _q(params: dict) -> str:
    return urlencode({k: v for k, v in params.items() if v is not None})


def _iso(d) -> str:
    """datetime → 네이버 date-time(+09:00). 이미 문자열이면(more.moreFrom) 그대로."""
    return d if isinstance(d, str) else d.strftime("%Y-%m-%dT%H:%M:%S.000+09:00")


def fetch_orders(last_changed_from, last_changed_to=None,
                  client: Optional[SmartStoreClient] = None,
                  last_changed_type: Optional[str] = None,
                  limit_count: int = 300,
                  more_sequence: Optional[str] = None) -> dict:
    """변경 상품 주문 내역 조회 — 한 페이지(raw).

    조회 기준 = 변경 일시. ``lastChangedFrom`` 은 필수(REQUIRED). ``lastChangedTo``
    생략 시 lastChangedFrom 으로부터 24시간. 응답 ``data.lastChangeStatuses[]``
    (productOrderId·productOrderStatus·lastChangedType 등) + 300개 초과 시
    ``data.more`` (moreFrom·moreSequence) 로 이어받는다.

    엔드포인트: GET /external/v1/pay-order/seller/product-orders/last-changed-statuses
    (API 센터 실측 + 2026-07-07 실계정 검증 — 최근 7일 33건 조회 성공).
    """
    client = client or SmartStoreClient()
    return client.request(
        method="GET",
        path="/external/v1/pay-order/seller/product-orders/last-changed-statuses",
        query=_q({
            "lastChangedFrom": _iso(last_changed_from),
            "lastChangedTo":   _iso(last_changed_to) if last_changed_to else None,
            "lastChangedType": last_changed_type,
            "limitCount":      limit_count,
            "moreSequence":    more_sequence,
        }),
    )


def iter_changed_product_order_ids(since: datetime, until: datetime,
                                   client: Optional[SmartStoreClient] = None,
                                   last_changed_type: Optional[str] = None,
                                   window_hours: int = 24) -> list:
    """[since, until] 사이 변경된 상품주문번호 목록(중복 제거, 입력 순서 유지).

    네이버 권장대로 24시간 윈도우로 끊고, 각 윈도우에서 300개 초과분은
    ``data.more`` (moreFrom·moreSequence) 로 이어받는다. 폴백·추측 없음.
    """
    client = client or SmartStoreClient()
    seen: dict = {}
    win_start = since
    while win_start < until:
        win_end = min(win_start + timedelta(hours=window_hours), until)
        frm, more_seq = win_start, None
        for _ in range(50):  # more 페이징 안전 상한
            resp = fetch_orders(frm, win_end, client=client,
                                last_changed_type=last_changed_type,
                                more_sequence=more_seq)
            data = resp.get("data") or {}
            for row in (data.get("lastChangeStatuses") or []):
                poid = row.get("productOrderId")
                if poid:
                    seen[poid] = None
            more = data.get("more") or {}
            if more.get("moreFrom"):
                frm, more_seq = more["moreFrom"], more.get("moreSequence")
            else:
                break
        win_start = win_end
    return list(seen.keys())


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
