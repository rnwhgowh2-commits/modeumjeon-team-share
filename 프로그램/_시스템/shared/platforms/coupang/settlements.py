# -*- coding: utf-8 -*-
"""
쿠팡 매출내역 조회 — 건별 정산 예정 금액

공식 엔드포인트:
  GET /v2/providers/openapi/apis/api/v1/revenue-history
      ?vendorId=&recognitionDateFrom=YYYY-MM-DD&recognitionDateTo=YYYY-MM-DD
      &token=&maxPerPage=50

제한:
- 최대 31일 범위, recognitionDateTo 는 전일까지만
- 페이징: hasNext / nextToken

Response:
data[].orderId, saleType, saleDate, recognitionDate, settlementDate
data[].items[] : vendorItemId, vendorItemName, salePrice, quantity,
                 saleAmount, serviceFee, serviceFeeVat, settlementAmount, ...

책임:
- 단건 페이지 조회 (fetch_revenue_page)
- 자동 페이징 (iter_revenue_items) — 주문→옵션 평탄화
- 옵션 단위 집계 (aggregate_by_vendor_item) — SALE-REFUND 차감
"""
from __future__ import annotations

from collections import defaultdict
from typing import Iterable, Iterator, Optional

from shared.platforms import COUPANG
from shared.platforms.coupang.client import CoupangClient
from shared.platforms.coupang.orders import _vendor_id


def fetch_revenue_page(
    recognition_from: str,
    recognition_to: str,
    token: str = "",
    max_per_page: int = 50,
    client: Optional[CoupangClient] = None,
) -> dict:
    """매출내역 1페이지 조회 (raw 응답)."""
    client = client or CoupangClient()
    path = COUPANG["paths"]["revenue_history"]
    # 계정 클라이언트(config 주입 vendor_id) 우선 — UI 저장 키는 COUPANG_MAIN_* 접두라 전역
    # COUPANG["vendor_id"] 는 비어있어 멀티계정 revenue-history 가 400(vendorId null)→정산 전멸
    # →estimated 조용히 폴백(오차 발생)했다. orders.py 와 동일하게 계정 vendor_id 우선 사용.
    vendor_id = (getattr(client, "_cfg", {}) or {}).get("vendor_id") or _vendor_id()
    query = (
        f"vendorId={vendor_id}"
        f"&recognitionDateFrom={recognition_from}"
        f"&recognitionDateTo={recognition_to}"
        f"&token={token}"
        f"&maxPerPage={max_per_page}"
    )
    return client.request(method="GET", path=path, query=query)


def iter_revenue_items(
    recognition_from: str,
    recognition_to: str,
    max_per_page: int = 50,
    client: Optional[CoupangClient] = None,
) -> Iterator[dict]:
    """모든 페이지를 순회하며 (order_level 필드 전파된) 옵션 단위 레코드를 yield."""
    token = ""
    while True:
        resp = fetch_revenue_page(
            recognition_from=recognition_from,
            recognition_to=recognition_to,
            token=token,
            max_per_page=max_per_page,
            client=client,
        )
        for order in (resp.get("data") or []):
            order_fields = {
                "orderId":         order.get("orderId"),
                "saleType":        order.get("saleType"),
                "saleDate":        order.get("saleDate"),
                "recognitionDate": order.get("recognitionDate"),
                "settlementDate":  order.get("settlementDate"),
            }
            for item in (order.get("items") or []):
                rec = dict(order_fields)
                rec.update(item)
                yield rec

        if not resp.get("hasNext"):
            break
        token = resp.get("nextToken") or ""
        if not token:
            break


def aggregate_by_vendor_item(
    recognition_from: str,
    recognition_to: str,
    client: Optional[CoupangClient] = None,
) -> dict[int, dict]:
    """vendorItemId 별로 정산 예정 금액을 집계.

    REFUND 건은 음수로 차감.

    Returns:
        { vendor_item_id: {
              net_settlement:   순 정산 금액,
              gross_settlement: SALE 총액,
              total_refund:     REFUND 총액,
              total_quantity:   순수량 (SALE - REFUND),
              sale_count, refund_count,
              last_name:        마지막 옵션명,
        }, ... }
    """
    agg: dict[int, dict] = defaultdict(lambda: {
        "net_settlement":    0,
        "gross_settlement":  0,
        "total_refund":      0,
        "total_sale_amount": 0,  # 수수료 계산 기준액
        "total_fee":         0,  # 서비스 이용료 합
        "total_fee_vat":     0,
        "total_quantity":    0,
        "sale_count":        0,
        "refund_count":      0,
        "last_name":         "",
        "last_fee_ratio":    None,  # 마지막으로 본 serviceFeeRatio
    })

    for it in iter_revenue_items(
        recognition_from=recognition_from,
        recognition_to=recognition_to,
        client=client,
    ):
        vid = it.get("vendorItemId")
        if not vid:
            continue
        amt = int(it.get("settlementAmount") or 0)
        qty = int(it.get("quantity") or 0)
        sale_amt = int(it.get("saleAmount") or 0)
        fee = int(it.get("serviceFee") or 0)
        fee_vat = int(it.get("serviceFeeVat") or 0)
        ratio = it.get("serviceFeeRatio")
        bucket = agg[vid]
        bucket["last_name"] = it.get("vendorItemName") or bucket["last_name"]
        if ratio is not None:
            bucket["last_fee_ratio"] = float(ratio)

        if it.get("saleType") == "REFUND":
            bucket["net_settlement"]  -= amt
            bucket["total_refund"]    += amt
            bucket["total_sale_amount"] -= sale_amt
            bucket["total_fee"]       -= fee
            bucket["total_fee_vat"]   -= fee_vat
            bucket["total_quantity"]  -= qty
            bucket["refund_count"]    += 1
        else:
            bucket["net_settlement"]   += amt
            bucket["gross_settlement"] += amt
            bucket["total_sale_amount"] += sale_amt
            bucket["total_fee"]        += fee
            bucket["total_fee_vat"]    += fee_vat
            bucket["total_quantity"]   += qty
            bucket["sale_count"]       += 1

    # 실효 수수료율 계산 (VAT 포함 기준): (fee + fee_vat) / sale_amount
    for vid, b in agg.items():
        if b["total_sale_amount"]:
            b["effective_fee_rate"] = (b["total_fee"] + b["total_fee_vat"]) / b["total_sale_amount"]
        else:
            b["effective_fee_rate"] = None

    return dict(agg)
