# -*- coding: utf-8 -*-
"""쿠팡 취소·반품·교환 thin wrapper (state-based model).

쿠팡은 별도 claim API 가 아니라 **상태 변경 API** 를 쓰는 구조.

공식 엔드포인트 (확인 범위, 2026-04-23):
  반품 요청 리스트:  GET  /v2/providers/openapi/apis/api/v4/vendors/{vendorId}/returnRequests
  반품 승인:         POST /v2/providers/openapi/apis/api/v4/vendors/{vendorId}/returnRequests/{receiptId}/approval

취소(cancellation) / 교환(exchange) 전용 경로는 공식 docs 에서 일부만 확인 → discussion_queue 이관.
"""
from __future__ import annotations

import os
from typing import Optional

from shared.platforms.coupang.client import CoupangClient


_VENDOR_ID_ENV = "COUPANG_VENDOR_ID"


def _vendor_id() -> str:
    vid = os.getenv(_VENDOR_ID_ENV, "")
    if not vid:
        raise ValueError(f"{_VENDOR_ID_ENV} 미설정")
    return vid


def list_return_requests(client: Optional[CoupangClient] = None,
                          **query) -> dict:
    """반품 요청 리스트."""
    vid = _vendor_id()
    client = client or CoupangClient()
    path = f"/v2/providers/openapi/apis/api/v4/vendors/{vid}/returnRequests"
    params = {"vendorId": vid, **query}
    return client.request("GET", path, query=params)


def approve_return_request(receipt_id: str, cancel_count: int = 1,
                             client: Optional[CoupangClient] = None) -> dict:
    """반품 요청 승인 (state-change)."""
    vid = _vendor_id()
    client = client or CoupangClient()
    path = (f"/v2/providers/openapi/apis/api/v4/vendors/{vid}"
            f"/returnRequests/{receipt_id}/approval")
    body = {
        "vendorId":    vid,
        "receiptId":   int(receipt_id) if str(receipt_id).isdigit()
                       else receipt_id,
        "cancelCount": int(cancel_count),
    }
    return client.request("POST", path, body=body)
