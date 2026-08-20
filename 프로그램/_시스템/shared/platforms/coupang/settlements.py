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

import datetime as _dt
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


def _ymd(v) -> Optional[str]:
    """'2026-07-20'·'20260720' → 'YYYY-MM-DD'. 값 없음·형식 불명은 None(폴백 금지)."""
    t = str(v or "").strip()[:10]
    if len(t) == 8 and t.isdigit():
        t = f"{t[:4]}-{t[4:6]}-{t[6:8]}"
    if len(t) != 10 or t[4] != "-" or t[7] != "-":
        return None
    try:
        _dt.date.fromisoformat(t)
    except ValueError:
        return None
    return t


def fetch_settlement_histories(year_month: str,
                               client: Optional[CoupangClient] = None) -> list:
    """지급내역조회 — 매출인식월(YYYY-MM)의 정산 **회차** 목록.

    🔴 왜 이 API 인가(2026-08-06 라이브 실측) — revenue-history 의 `settlementDate` 는
       실제로 안 온다(1,820행 중 0건). 「받을 날이 지났는데 입금됐는지 모르는 돈」이
       쿠팡만 6,158만 쌓인 원인이다. 이 API 는 회차마다 status 를 준다:
         DONE = 지급 완료(그 회차에 속한 주문은 **이미 받은 것**)
         SUBJECT = 지급 예정
    ★ 주문 단위가 아니라 **회차 단위**다 — 조인은 매출인식일 구간으로 한다
      (match_by_recognition_date 참조).
    ★ 주정산은 70%(WEEKLY) + 30%(RESERVE) 두 회차라 같은 구간에 둘 다 나올 수 있다.

    🔴 [2026-08-06 Wing 화면 실측] **finalAmount 하나만 보면 안 된다.**
       세소 6월: 우리 계산 11,131,180 ≈ 정산대상액 11,081,786(0.44% 차, 우리가 맞았다)인데
       통장 입금(finalAmount)은 300,756 뿐이었다. 861만은 **빠른정산으로 7/14 미리 인출**해
       회차에서 공제된 것. 그래서 대조 상대는 `settlementTargetAmount`,
       선인출액은 `deductionAmount` 에서 역산한다.

    Returns [{"type","status","settlementDate","from","to","finalAmount",
              "targetAmount","settlementAmount","deductionAmount",
              "fastWithdrawn","항등식맞음"}] —
    날짜가 없는 회차는 담지 않는다(조인 근거가 없으므로).
    """
    client = client or CoupangClient()
    path = COUPANG["paths"]["settlement_histories"]
    vendor_id = (getattr(client, "_cfg", {}) or {}).get("vendor_id") or _vendor_id()
    query = f"vendorId={vendor_id}&revenueRecognitionYearMonth={year_month}"
    resp = client.request(method="GET", path=path, query=query)
    # 🔴 [2026-08-06 라이브 실측] 응답이 **배열 그대로** 온다(8계정 전부
    #   AttributeError: 'list' object has no attribute 'get' 로 드러남).
    #   문서 예시는 {"data":[…]} 처럼 보이지만 실제는 다르다 → 두 모양 다 받는다.
    rows = resp if isinstance(resp, list) else ((resp or {}).get("data") or [])
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        f, t = _ymd(r.get("revenueRecognitionDateFrom")), _ymd(r.get("revenueRecognitionDateTo"))
        sd = _ymd(r.get("settlementDate"))
        if not (f and t and sd):
            continue                      # 구간·지급일 없으면 조인 불가 — 버린다
        rec = {"type": str(r.get("settlementType") or ""),
               "status": str(r.get("status") or ""),
               "settlementDate": sd, "from": f, "to": t,
               "finalAmount": r.get("finalAmount"),
               "targetAmount": _int_or_none(r.get("settlementTargetAmount")),
               "settlementAmount": _int_or_none(r.get("settlementAmount")),
               "deductionAmount": _int_or_none(r.get("deductionAmount"))}
        rec["fastWithdrawn"] = fast_withdrawn(r)
        rec["항등식맞음"] = _identity_holds(r)
        out.append(rec)
    return out


def _int_or_none(v):
    """금액 필드 → int. 없으면 **None**(0 으로 지어내면 「0원 지급」과 구분이 안 된다)."""
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


#: 공제금액(F) 안에서 **이름이 붙어 있는** 항목들. 나머지가 빠른정산 계좌인출액이다.
#  (Wing 「정산 현황」 상세의 공제금액 소계 구성 — 2026-08-06 화면 실측으로 확인)
_NAMED_DEDUCTIONS = ("sellerServiceFee", "dedicatedDeliveryAmount", "debtOfLastWeek",
                     "couranteeFee", "sellerDiscountCoupon")


def fast_withdrawn(raw: dict) -> int:
    """빠른정산(셀러월렛) 계좌인출액 — 공제금액에서 이름 붙은 항목을 뺀 나머지.

    🔴 이 돈은 **이미 사장님 통장에 들어간 돈**이다. 주문별 정산액에는 그대로 남아 있어
       빼지 않으면 「앞으로 받을 돈」이 그만큼 부풀어 보인다(세소 6월 291만).
       쿠팡이 전용 필드를 안 주므로 역산한다. 음수는 0 으로 눕힌다(모르면 0).
    """
    ded = _int_or_none((raw or {}).get("deductionAmount")) or 0
    named = sum(_int_or_none((raw or {}).get(k)) or 0 for k in _NAMED_DEDUCTIONS)
    return max(0, ded - named)


def _identity_holds(raw: dict) -> bool:
    """지급액 + 보류액 − 공제액 = 최종지급액 인지 검산.

    어긋나면 우리가 필드를 잘못 읽고 있다는 뜻 — 조용히 넘기지 말고 표면화한다.
    """
    d = _int_or_none((raw or {}).get("settlementAmount"))
    e = _int_or_none((raw or {}).get("pendingReleasedAmount")) or 0
    f = _int_or_none((raw or {}).get("deductionAmount"))
    final = _int_or_none((raw or {}).get("finalAmount"))
    if d is None or f is None or final is None:
        return False
    return d + e - f == final


def match_by_recognition_date(histories: list, recognition_date) -> dict:
    """주문의 매출인식일이 속한 회차들에서 (받은 날, 앞으로 받을 날)을 뽑는다.

    · paid_date  = DONE 회차 중 **가장 늦은** 지급일(부분 지급이면 마지막 입금일)
    · expect_date= SUBJECT 회차 중 **가장 빠른** 지급예정일(다음에 들어올 날)
    둘 다 없으면 None — 「지급 안 됨」으로 단정하지 않는다(폴백 금지).
    """
    d = _ymd(recognition_date)
    if not d:
        return {"paid_date": None, "expect_date": None}
    paid, expect = [], []
    for h in histories or []:
        if not (h["from"] <= d <= h["to"]):
            continue
        (paid if h["status"] == "DONE" else expect).append(h["settlementDate"])
    return {"paid_date": max(paid) if paid else None,
            "expect_date": min(expect) if expect else None}


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
