# -*- coding: utf-8 -*-
"""쿠팡 클레임(반품·취소·교환) 목록조회 — 발송관리 대조용.

공식 스펙(developers.coupangcorp.com, MCP 실측 2026-07-09):
  반품/취소: GET /v2/providers/openapi/apis/api/v4/vendors/{vid}/returnRequests
    ?searchType=timeFrame&createdAtFrom&createdAtTo(yyyy-MM-ddTHH:mm:ss·최대 7일)
    &status(RU/CC/PR/UC 필수)&maxPerPage&nextToken
    resp data[]{ receiptId, orderId, receiptType(RETURN/CANCEL), receiptStatus, createdAt,
      requesterName, reasonCodeText, returnItems[]{ sellerProductName(상품명), vendorItemName(옵션),
      cancelCount(취소수량), purchaseCount(주문수량) } }
  교환: GET /v2/providers/openapi/apis/api/v4/vendors/{vid}/exchangeRequests
    ?createdAtFrom&createdAtTo(최대 7일)&status(생략시 전체)&maxPerPage&nextToken
    resp data[]{ exchangeId, orderId, exchangeStatus, reasonCodeText,
      exchangeItemDtoV1s[]{ orderItemName/targetItemName(상품명), quantity(교환수량), orderItemUnitPrice } }
인증·rate limit 은 CoupangClient(HMAC). query 는 '문자열'(HMAC 서명 일치, orders.py 동일 패턴).

⚠️ query 를 dict 로 넘기면 서명 단계 lstrip 크래시 → 반드시 문자열.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterator, Optional

from shared.platforms.coupang.client import CoupangClient

_RETURN_STATUSES = ("RU", "CC", "PR", "UC")   # timeFrame 조회 필수(프로브 실측 유효값)
_MAX_WINDOW_DAYS = 7                            # 문서: 조회기간 7일 이하


def _vendor(client) -> str:
    from shared.platforms.coupang.orders import _vendor_id
    return (getattr(client, "_cfg", {}) or {}).get("vendor_id") or _vendor_id()


def _windows(since: datetime, until: datetime):
    cur = since
    step = timedelta(days=_MAX_WINDOW_DAYS)
    while cur < until:
        nxt = min(cur + step, until)
        yield cur, nxt
        cur = nxt


def _iso(d: datetime) -> str:
    # ★ 서버 프로브 실측(2026-07-13): 두 엔드포인트가 요구 포맷이 다르다.
    #   exchangeRequests → 'yyyy-MM-ddTHH:mm:ss'(초 필수). returnRequests → 'yyyy-MM-ddTHH:mm'(초 금지).
    #   맞는 포맷 아니면 HTTP 400 으로 전체 조회 실패 → 취소/반품/교환 통째 누락.
    return d.strftime("%Y-%m-%dT%H:%M:%S")


def _iso_min(d: datetime) -> str:
    """returnRequests 전용(초 없음). 초를 붙이면 400."""
    return d.strftime("%Y-%m-%dT%H:%M")


def iter_returns(since: datetime, until: datetime, *,
                 client: Optional[CoupangClient] = None) -> Iterator[dict]:
    """반품/취소 요청. status(RU/CC/PR/UC) 순회 + 7일 윈도우 + receiptId 중복제거."""
    client = client or CoupangClient()
    vid = _vendor(client)
    path = f"/v2/providers/openapi/apis/api/v4/vendors/{vid}/returnRequests"
    seen = set()
    for w_from, w_to in _windows(since, until):
        for st in _RETURN_STATUSES:
            token = None
            for _ in range(50):
                q = (f"searchType=timeFrame&createdAtFrom={_iso_min(w_from)}"
                     f"&createdAtTo={_iso_min(w_to)}&status={st}&maxPerPage=50")
                if token:
                    q += f"&nextToken={token}"
                resp = client.request("GET", path, query=q)
                for r in (resp.get("data") or []):
                    rid = r.get("receiptId")
                    if rid in seen:
                        continue
                    seen.add(rid)
                    yield r
                token = resp.get("nextToken")
                if not token:
                    break


def iter_exchanges(since: datetime, until: datetime, *,
                   client: Optional[CoupangClient] = None) -> Iterator[dict]:
    """교환 요청. status 생략(전체) + 7일 윈도우 + exchangeId 중복제거."""
    client = client or CoupangClient()
    vid = _vendor(client)
    path = f"/v2/providers/openapi/apis/api/v4/vendors/{vid}/exchangeRequests"
    seen = set()
    for w_from, w_to in _windows(since, until):
        token = None
        for _ in range(50):
            q = f"createdAtFrom={_iso(w_from)}&createdAtTo={_iso(w_to)}&maxPerPage=50"
            if token:
                q += f"&nextToken={token}"
            resp = client.request("GET", path, query=q)
            for r in (resp.get("data") or []):
                eid = r.get("exchangeId")
                if eid in seen:
                    continue
                seen.add(eid)
                yield r
            token = resp.get("nextToken")
            if not token:
                break


# ── 하위호환(capabilities.py 참조) ── 반품 목록 단순 wrapper + 승인(state-change) ──
def list_return_requests(client: Optional[CoupangClient] = None, **query) -> dict:
    """반품 요청 리스트(단순). capabilities 카탈로그·수동 조회용. 목록 순회는 iter_returns 사용."""
    client = client or CoupangClient()
    vid = _vendor(client)
    path = f"/v2/providers/openapi/apis/api/v4/vendors/{vid}/returnRequests"
    q = "&".join(f"{k}={v}" for k, v in query.items()) or None   # 문자열 query(서명 일치)
    return client.request("GET", path, query=q)


def approve_return_request(receipt_id: str, cancel_count: int = 1,
                           client: Optional[CoupangClient] = None) -> dict:
    """반품 요청 승인(state-change)."""
    client = client or CoupangClient()
    vid = _vendor(client)
    path = (f"/v2/providers/openapi/apis/api/v4/vendors/{vid}"
            f"/returnRequests/{receipt_id}/approval")
    body = {"vendorId": vid,
            "receiptId": int(receipt_id) if str(receipt_id).isdigit() else receipt_id,
            "cancelCount": int(cancel_count)}
    return client.request("POST", path, body=body)
