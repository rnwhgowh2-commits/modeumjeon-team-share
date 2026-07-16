# -*- coding: utf-8 -*-
"""스마트스토어 (네이버 커머스) 주문·CS API thin wrapper.

공식 엔드포인트 (API 센터 실측 + 2026-07-07 실계정 검증):
- 주문 목록:   GET  /v1/pay-order/seller/product-orders/last-changed-statuses
               (lastChangedFrom REQUIRED · lastChangedTo · lastChangedType · limitCount · moreSequence)
               ※ 조회 기준=변경 일시. 300개 초과 시 data.more(moreFrom·moreSequence)로 이어받기.
- 주문 상세:   POST /v1/pay-order/seller/product-orders/query (productOrderIds[] 최대 300)
- 발송/송장:   POST /v1/pay-order/seller/product-orders/dispatch (productOrderIds[], shippingCompany, trackingNumber)
- 고객문의:    GET  /v1/pay-user/inquiries (startSearchDate/endSearchDate yyyy-MM-dd·page·size·answered)
- 상품Q&A:     GET  /v1/contents/qnas (fromDate/toDate ISO ...Z·page·size≤100·answered)
- 문의 답변:   POST /v1/pay-merchant/inquiries/{inquiryNo}/answer (answerComment)
- 클레임:      POST /v1/pay-order/seller/product-orders/{productOrderId}/claim/{type}/{action}

인증·rate limit·재시도 는 SmartStoreClient 가 처리. 이 모듈은 body/query 매핑만.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional
from urllib.parse import urlencode

from shared.platforms.smartstore.client import SmartStoreClient, SmartStoreRateLimitError

logger = logging.getLogger(__name__)

# 주문 조회(margin·주문내역) 경로의 429 재시도 — 워커 requeue 경로와 달리 여기선 즉시
# 재시도해야 마켓이 통째 빠지지 않는다(스스=앱 단위 rate limit, 다계정 순차조회 시 흔함).
_ORDER_QUERY_429_RETRIES = 5


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
    query = _q({
        "lastChangedFrom": _iso(last_changed_from),
        "lastChangedTo":   _iso(last_changed_to) if last_changed_to else None,
        "lastChangedType": last_changed_type,
        "limitCount":      limit_count,
        "moreSequence":    more_sequence,
    })
    # 429(rate limit) 재시도 — client.request 는 워커 requeue 를 위해 429 를 즉시 raise 한다.
    #   주문 조회 경로엔 requeue 가 없으므로(=마켓이 통째 markets_failed 로 빠짐), 여기서
    #   retry_after 만큼 쉬고 재시도한다. client.request 가 429 마다 limiter 를 halve 하므로
    #   재시도할수록 호출 간격이 벌어져 회복된다. GW.QUOTA_LIMIT(판매자 일일 할당량 소진)은
    #   짧은 대기로 안 풀리므로 재시도 없이 즉시 전파(무의미한 지연 방지).
    last_exc: Optional[SmartStoreRateLimitError] = None
    for attempt in range(_ORDER_QUERY_429_RETRIES + 1):
        try:
            return client.request(
                method="GET",
                path="/external/v1/pay-order/seller/product-orders/last-changed-statuses",
                query=query,
            )
        except SmartStoreRateLimitError as e:
            last_exc = e
            if getattr(e, "is_quota", False) or attempt >= _ORDER_QUERY_429_RETRIES:
                raise
            wait = min(max(int(getattr(e, "retry_after_sec", 5) or 5), 2), 15)
            logger.warning(
                "[smartstore] 주문조회 429 rate limit — %ds 대기 후 재시도 (%d/%d)",
                wait, attempt + 1, _ORDER_QUERY_429_RETRIES,
            )
            time.sleep(wait)
    assert last_exc is not None
    raise last_exc


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


def confirm_orders(product_order_ids: list[str],
                    client: Optional[SmartStoreClient] = None) -> dict:
    """발주확인 — 결제완료(PAYED) → 배송준비(발주확인). 최대 다건.

    공식: POST /external/v1/pay-order/seller/product-orders/confirm,
          body {"productOrderIds":[...]}.
    ⚠️ 라이브 미검증 — 실주문 1건으로 상태 전이 확인 후 신뢰.
    """
    import json as _json
    client = client or SmartStoreClient()
    ids = [str(p) for p in product_order_ids if p]
    if not ids:
        raise ValueError("스마트스토어 발주확인: productOrderId 없음 — 추측 전송 금지")
    resp = client.request(
        method="POST",
        path="/external/v1/pay-order/seller/product-orders/confirm",
        body={"productOrderIds": ids},
    )
    # 네이버는 HTTP 200 에 개별 결과를 담는다(거짓성공 금지). 확정 목록 = successProductOrderInfos.
    #  ★발주확인은 productOrderStatus(=결제완료/PAYED)를 바꾸지 않는다 → 상태 되읽기 대신
    #    이 응답의 확정 목록이 유일한 검증 신호다. '이미 발주확인'(104443)은 멱등 성공.
    data = (resp or {}).get("data") or resp or {}
    confirmed = {str(x.get("productOrderId")) for x in (data.get("successProductOrderInfos") or [])
                 if x.get("productOrderId")}
    real_fails = []
    for f in (data.get("failProductOrderInfos") or []):
        if str(f.get("code")) == "104443":        # 이미 발주확인 된 주문 = 이미 원하는 상태
            confirmed.add(str(f.get("productOrderId")))
        else:
            real_fails.append(f)
    missing = [p for p in ids if p not in confirmed]
    if real_fails or missing:
        raise RuntimeError(
            "스마트스토어 발주확인 실패: " + _json.dumps(real_fails[:2], ensure_ascii=False)
            + (" 누락=" + _json.dumps(missing[:3], ensure_ascii=False) if missing else "")
            + " 원응답=" + _json.dumps(resp, ensure_ascii=False)[:400])
    return confirmed   # 확정된 productOrderId 집합(= 오픈마켓주문번호)


def send_tracking(product_order_ids: list[str], delivery_company_code: str,
                   tracking_number: str,
                   client: Optional[SmartStoreClient] = None,
                   shipping_date_ymd: Optional[str] = None) -> dict:
    """발송·송장 전송 (최대 30개 한번에, 같은 송장번호 = 합포장).

    body 필드 = deliveryMethod + deliveryCompanyCode + trackingNumber.
    (기존에 shippingCompany 로 보내던 것은 필드명 오류 — 실전송 이력이 없어 드러나지 않았다.)
    delivery_company_code 는 **네이버 코드**(로젠=LOGEN). 쿠팡 코드(로젠=KGB)와 다르니 섞지 말 것.
    ⚠️ 라이브 미검증 — 실계정 1건 전송으로 최종 확인.
    """
    client = client or SmartStoreClient()
    body = {
        "dispatchProductOrders": [{
            "productOrderId": pid,
            "deliveryMethod": "DELIVERY",
            "deliveryCompanyCode": delivery_company_code,
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


def _iso_z(d) -> str:
    """datetime → 네이버 date-time(UTC, ...Z). tz-aware면 UTC로 변환, naive면 그대로."""
    if isinstance(d, str):
        return d
    if d.tzinfo is not None:
        d = d.astimezone(timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def fetch_inquiries(since: datetime, until: Optional[datetime] = None,
                     client: Optional[SmartStoreClient] = None,
                     answered: Optional[bool] = None,
                     page_size: int = 200,
                     page_number: int = 1) -> dict:
    """고객 문의(주문·고객문의) 조회. GET /external/v1/pay-user/inquiries.

    ★API 센터 실측(2026-07-16): 기간=startSearchDate/endSearchDate (yyyy-MM-dd, 필수),
    페이지=page(1~)/size(10~200), answered(true/false) 생략=전체.
    이전 startDate/inquiryStatus/pageSize 파라미터명은 HTTP 400 원인이었다.
    응답 top-level ``content[]`` (고객 문의 내용 구조체) + totalPages·last.
    """
    client = client or SmartStoreClient()
    until = until or (since + timedelta(days=7))
    params = {
        "startSearchDate": since.strftime("%Y-%m-%d"),
        "endSearchDate":   until.strftime("%Y-%m-%d"),
        "page":            page_number,
        "size":            min(max(page_size, 10), 200),
    }
    if answered is not None:
        params["answered"] = "true" if answered else "false"
    return client.request(
        method="GET",
        path="/external/v1/pay-user/inquiries",
        query=_q(params),
    )


def fetch_product_qnas(from_dt: datetime, to_dt: Optional[datetime] = None,
                        client: Optional[SmartStoreClient] = None,
                        answered: Optional[bool] = None,
                        page_size: int = 100,
                        page_number: int = 1) -> dict:
    """상품 문의(상품Q&A) 목록 조회. GET /external/v1/contents/qnas.

    ★API 센터 실측(2026-07-16): 기간=fromDate/toDate (ISO date-time ...Z, 필수),
    page(1~)/size(≤100), answered(true/false) 생략=전체.
    응답 top-level ``contents[]`` (상품 문의 내용 구조체) + totalPages·last.
    """
    client = client or SmartStoreClient()
    to_dt = to_dt or (from_dt + timedelta(days=7))
    params = {
        "fromDate": _iso_z(from_dt),
        "toDate":   _iso_z(to_dt),
        "page":     page_number,
        "size":     min(page_size, 100),
    }
    if answered is not None:
        params["answered"] = "true" if answered else "false"
    return client.request(
        method="GET",
        path="/external/v1/contents/qnas",
        query=_q(params),
    )


def reply_inquiry(inquiry_no: str, answer_content: str,
                   client: Optional[SmartStoreClient] = None) -> dict:
    """고객 문의 답변 등록. POST /external/v1/pay-merchant/inquiries/{inquiryNo}/answer.

    ★Body 는 ``answerComment`` (API 센터 실측). answerContent 아님.
    """
    client = client or SmartStoreClient()
    return client.request(
        method="POST",
        path=f"/external/v1/pay-merchant/inquiries/{inquiry_no}/answer",
        body={"answerComment": answer_content},
    )


def reply_product_qna(question_id: str, comment_content: str,
                       client: Optional[SmartStoreClient] = None) -> dict:
    """상품 문의(상품Q&A) 답변 등록/수정. PUT /external/v1/contents/qnas/{questionId}.

    ★고객문의(pay-merchant answer)와 별개 엔드포인트 — body 는 ``commentContent``.
    전송 열 때 문의형태(상품문의=이 함수 / 주문고객문의=reply_inquiry)로 분기한다.
    """
    client = client or SmartStoreClient()
    return client.request(
        method="PUT",
        path=f"/external/v1/contents/qnas/{question_id}",
        body={"commentContent": comment_content},
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
