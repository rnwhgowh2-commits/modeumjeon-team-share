# -*- coding: utf-8 -*-
"""쿠팡 고객문의 (online inquiries + call center inquiries) thin wrapper.

공식 엔드포인트 (developers.coupangcorp.com — 2026-04-23 확인):
  GET  /v2/providers/openapi/apis/api/v5/vendors/{vendorId}/onlineInquiries
  POST /v2/providers/openapi/apis/api/v4/vendors/{vendorId}/callCenterInquiries/{inquiryId}/replies

제약:
  - fetch_inquiries: inquiryStartAt ~ inquiryEndAt **최대 7일** 권장 (타임아웃 위험)
  - reply_inquiry: inquiryStatus=progress 이고 partnerTransferStatus=requestAnswer 일 때만 가능
  - request body 필드 일부 미확인 → 실 호출 실패 시 `discussion_queue` 에 이관
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


def fetch_online_inquiries(since: datetime, until: datetime,
                            client: Optional[CoupangClient] = None,
                            answered_type: str = "NOANSWER",
                            page_size: int = 10,
                            page_num: int = 1) -> dict:
    """온라인 고객문의 조회.

    answered_type: NOANSWER / ANSWERED / ALL
    """
    client = client or CoupangClient()
    vid = (getattr(client, "_cfg", {}) or {}).get("vendor_id") or _vendor_id()
    path = (f"/v2/providers/openapi/apis/api/v5/vendors/{vid}/onlineInquiries")
    # CoupangClient.request 는 query 를 '문자열'로 받아 HMAC 서명에 그대로 쓴다
    # (orders.py 동일 패턴). dict 를 넘기면 서명 단계에서 lstrip 크래시.
    q = (f"vendorId={vid}"
         f"&inquiryStartAt={since.strftime('%Y-%m-%d')}"
         f"&inquiryEndAt={until.strftime('%Y-%m-%d')}"
         f"&answeredType={answered_type}"
         f"&pageSize={page_size}"
         f"&pageNum={page_num}")
    return client.request("GET", path, query=q)


def reply_online_inquiry(inquiry_id: str, content: str,
                          vendor_user_id: Optional[str] = None,
                          client: Optional[CoupangClient] = None) -> dict:
    """콜센터 문의 답변 (POST).

    vendor_user_id: 답변자 ID (env COUPANG_VENDOR_USER_ID fallback).

    body 필드는 공식 docs 에서 일부만 확인. 실 호출 실패 시 content 명 교정 필요.
    """
    client = client or CoupangClient()
    vid = (getattr(client, "_cfg", {}) or {}).get("vendor_id") or _vendor_id()
    user = vendor_user_id or os.getenv("COUPANG_VENDOR_USER_ID", "")
    path = (f"/v2/providers/openapi/apis/api/v4/vendors/{vid}"
            f"/callCenterInquiries/{inquiry_id}/replies")
    body = {
        "vendorId":     vid,
        "inquiryId":    inquiry_id,
        "content":      content,
        "replyType":    "ANSWER",
        "parentAnswerId": 0,
        "vendorUserId": user,
    }
    return client.request("POST", path, body=body)


def fetch_call_center_inquiries(since: datetime, until: datetime,
                                 client: Optional[CoupangClient] = None,
                                 counseling_status: str = "NONE",
                                 page_size: int = 50,
                                 page_num: int = 1) -> dict:
    """고객센터 문의 조회 (GET). 고객센터 상담 경유 문의.

    partnerCounselingStatus: NONE(전체)/ANSWER(답변완료)/NO_ANSWER(미답변)/TRANSFER 등.
    ★실제 파라미터·응답 필드는 라이브 보정 대상. query 는 문자열(HMAC 서명).
    """
    client = client or CoupangClient()
    vid = (getattr(client, "_cfg", {}) or {}).get("vendor_id") or _vendor_id()
    path = (f"/v2/providers/openapi/apis/api/v4/vendors/{vid}/callCenterInquiries")
    q = (f"vendorId={vid}"
         f"&inquiryStartAt={since.strftime('%Y-%m-%d')}"
         f"&inquiryEndAt={until.strftime('%Y-%m-%d')}"
         f"&partnerCounselingStatus={counseling_status}"
         f"&pageSize={page_size}&pageNum={page_num}")
    return client.request("GET", path, query=q)
