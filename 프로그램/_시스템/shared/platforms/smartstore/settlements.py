# -*- coding: utf-8 -*-
"""스마트스토어(네이버 커머스) 건별 정산 내역 조회 — 정산 예정 금액.

공식 엔드포인트 (API 센터 실측 2026-07-06, operationId=find-settle-by-case-pay-settle):
  GET /external/v1/pay-settle/settle/case
      ?pageNumber=&pageSize=&searchDate=&periodType=&orderId=&productOrderId=
       &settleType=&settleDecisionType=

Response:
  elements[] : settleExpectAmount(정산 예정 금액·REQUIRED), productOrderId, orderId,
               productName, purchaserName, paySettleAmount(정산 기준 금액),
               benefitSettleAmount, totalPayCommissionAmount, productOrderType,
               settleType, settleExpectDate, ...
  pagination : page, size, totalPages, totalElements

periodType (조회 기간 기준):
  SETTLE_CASEBYCASE_SETTLE_SCHEDULE_DATE  정산 예정일 (기본)
  SETTLE_CASEBYCASE_SETTLE_BASIS_DATE     정산 기준일
  SETTLE_CASEBYCASE_SETTLE_COMPLETE_DATE  정산 완료일
  SETTLE_CASEBYCASE_PAY_DATE              결제일
  SETTLE_CASEBYCASE_TAXRETURN_BASIS_DATE  세금 신고 기준일

인증·rate limit·재시도 는 SmartStoreClient 담당. 이 모듈은 query/파싱만.
쿠팡 settlements.py 와 동형(페이지 조회 → 자동 페이징 → 집계).
"""
from __future__ import annotations

from typing import Iterator, Optional
from urllib.parse import urlencode

from shared.platforms.smartstore.client import SmartStoreClient

_PATH = "/external/v1/pay-settle/settle/case"
_DEFAULT_PERIOD = "SETTLE_CASEBYCASE_SETTLE_SCHEDULE_DATE"  # 정산 예정일 기준


def _q(params: dict) -> str:
    return urlencode({k: v for k, v in params.items() if v not in (None, "")})


def fetch_settle_by_case_page(page_number: int,
                              page_size: int = 1000,
                              search_date: Optional[str] = None,
                              period_type: Optional[str] = None,
                              order_id: Optional[str] = None,
                              product_order_id: Optional[str] = None,
                              settle_type: Optional[str] = None,
                              settle_decision_type: Optional[str] = None,
                              client: Optional[SmartStoreClient] = None) -> dict:
    """건별 정산 내역 1페이지 조회 (raw 응답).

    pageNumber>=1, pageSize<=1000 (공식 제약).
    """
    client = client or SmartStoreClient()
    return client.request(
        method="GET",
        path=_PATH,
        query=_q({
            "pageNumber":        page_number,
            "pageSize":          page_size,
            "searchDate":        search_date,
            "periodType":        period_type,
            "orderId":           order_id,
            "productOrderId":    product_order_id,
            "settleType":        settle_type,
            "settleDecisionType": settle_decision_type,
        }),
    )


def iter_settle_by_case(search_date: Optional[str] = None,
                        period_type: str = _DEFAULT_PERIOD,
                        page_size: int = 1000,
                        client: Optional[SmartStoreClient] = None,
                        **filters) -> Iterator[dict]:
    """모든 페이지를 순회하며 elements 레코드를 yield (기본 기준=정산 예정일)."""
    client = client or SmartStoreClient()
    page = 1
    while True:
        resp = fetch_settle_by_case_page(
            page_number=page, page_size=page_size,
            search_date=search_date, period_type=period_type,
            client=client, **filters)
        elements = resp.get("elements") or []
        for el in elements:
            yield el
        pg = resp.get("pagination") or {}
        total_pages = pg.get("totalPages") or 0
        if not elements or page >= total_pages:
            break
        page += 1


def settle_expect_by_product_order(search_date: Optional[str] = None,
                                   period_type: str = _DEFAULT_PERIOD,
                                   client: Optional[SmartStoreClient] = None,
                                   **filters) -> dict:
    """상품주문번호(productOrderId) → 정산 예정 금액 합계.

    한 상품주문에 상품/배송비/기타비용 등 여러 행(productOrderType)이 올 수 있어
    settleExpectAmount 를 합산한다.
    폴백·추측 금지(CLAUDE.md): settleExpectAmount 또는 productOrderId 없는 행은
    건너뛴다(가짜 0 대입 X → 값 없으면 그 주문은 키 자체가 없음).
    """
    acc: dict[str, float] = {}
    for el in iter_settle_by_case(search_date=search_date, period_type=period_type,
                                  client=client, **filters):
        poid = el.get("productOrderId")
        amt = el.get("settleExpectAmount")
        if poid is None or amt is None:
            continue
        acc[poid] = acc.get(poid, 0) + amt
    return acc


def settle_expect_maps(search_date: Optional[str] = None,
                       period_type: str = _DEFAULT_PERIOD,
                       client: Optional[SmartStoreClient] = None,
                       **filters) -> tuple:
    """(상품정산 by productOrderId, 배송비정산 by orderId) 두 맵 반환.

    네이버 정산은 productOrderType 별 별도 행: 상품(PROD_ORDER)은 상품주문번호로,
    배송비(DELIVERY)는 배송비번호가 달라 orderId 로 집계해야 주문에 붙일 수 있다.
    (환불 등은 상품주문번호로 상계.) 폴백 금지: 금액 없는 행 스킵.
    """
    prod: dict = {}
    deliv: dict = {}
    for el in iter_settle_by_case(search_date=search_date, period_type=period_type,
                                  client=client, **filters):
        amt = el.get("settleExpectAmount")
        if amt is None:
            continue
        if el.get("productOrderType") == "DELIVERY":
            oid = el.get("orderId")
            if oid is not None:
                deliv[oid] = deliv.get(oid, 0) + amt
        else:
            poid = el.get("productOrderId")
            if poid is not None:
                prod[poid] = prod.get(poid, 0) + amt
    return prod, deliv
