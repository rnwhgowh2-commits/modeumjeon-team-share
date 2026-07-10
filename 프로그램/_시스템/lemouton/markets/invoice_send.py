# -*- coding: utf-8 -*-
"""송장(운송장) 전송 — 마켓 라우팅 · 택배사 코드 · 드라이런 게이트.

「주문 내역」에서 고른 주문에 운송장번호를 실제 마켓으로 전송한다.

안전 원칙(CLAUDE.md):
  · **드라이런 기본** — live=True 일 때만 마켓 API 를 실제로 호출한다.
  · **추측 금지** — 택배사 코드가 마켓마다 달라, 확보하지 못한 마켓은 보내지 않고 명시 실패.
  · **거짓 성공 금지** — 전송 함수가 없는 마켓(롯데온·11번가·옥션·G마켓)은 조용히 성공시키지 않는다.
  · **식별자 추측 금지** — 쿠팡은 shipmentBoxId 가 없으면 보내지 않는다(주문 행의 _send_ids).

마켓별 전송 방식:
  · 쿠팡      = send_tracking(shipmentBoxId, orderSheetId, 택배사코드, 운송장번호)
  · 스마트스토어 = send_tracking([productOrderId], 택배사코드, 운송장번호)
                  ※ 「오픈마켓주문번호」가 곧 productOrderId 라 그대로 쓴다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# 실제 전송 함수를 가진 마켓만. 나머지는 명시 실패.
SUPPORTED_SEND = {"coupang", "smartstore"}


class CourierCodeUnknown(ValueError):
    """그 마켓의 택배사 코드를 확보하지 못함 — 추측해서 보내지 않는다."""


# 스마트스토어 택배사 코드: 실제 코드값 **미확보**.
#   쿠팡과 코드 체계가 달라(쿠팡 로젠=KGB) 그대로 쓰면 엉뚱한 택배사로 등록된다.
#   실제 값 확인(네이버 커머스 택배사 코드) 후 채운다. 그전까지 스스 전송은 명시 실패.
_SMARTSTORE_COURIER: dict[str, str] = {}


def resolve_courier_code(market: str, courier_name: str) -> str:
    """마켓별 택배사 코드. 근거 없는 값은 만들지 않고 CourierCodeUnknown."""
    if market == "coupang":
        from shared.platforms.coupang.shipping import DELIVERY_COMPANY_CODES
        code = DELIVERY_COMPANY_CODES.get(courier_name)
        if not code:
            raise CourierCodeUnknown(f"쿠팡 택배사 코드 없음: {courier_name}")
        return code
    if market == "smartstore":
        code = _SMARTSTORE_COURIER.get(courier_name)
        if not code:
            raise CourierCodeUnknown(
                f"스마트스토어 택배사 코드 미확보: {courier_name} — 실제 코드 확인 후 전송")
        return code
    raise CourierCodeUnknown(f"{market} 택배사 코드표 없음")


@dataclass
class SendResult:
    """송장 전송 1건 결과. dry_run=True 면 실제로 보내지 않았다."""
    market: str
    order_no: str
    success: bool
    dry_run: bool = False
    error: Optional[str] = None


def send_invoice(*, market: str, order_no, courier_name: str, invoice_no,
                 send_ids: Optional[dict] = None, client=None,
                 live: bool = False) -> SendResult:
    """운송장번호 1건 전송. 기본은 드라이런(외부 호출 없음).

    Args:
        market: 마켓 슬러그
        order_no: 「오픈마켓주문번호」 (스스는 곧 productOrderId)
        courier_name: 화면에서 고른 택배사 이름 (예: "로젠택배")
        invoice_no: 운송장번호
        send_ids: 마켓별 전송 식별자 (쿠팡: shipment_box_id·order_sheet_id)
        client: 계정별 마켓 클라이언트 (없으면 각 플랫폼 기본)
        live: True 일 때만 실제 전송
    """
    order_no = str(order_no)

    if market not in SUPPORTED_SEND:
        return SendResult(market, order_no, False,
                          error=f"{market} 는 송장 전송 미지원 (전송 함수 없음)")

    try:
        code = resolve_courier_code(market, courier_name)
    except CourierCodeUnknown as e:
        return SendResult(market, order_no, False, error=str(e))

    if not str(invoice_no or "").strip():
        return SendResult(market, order_no, False, error="운송장번호 없음")

    sb = os_ = None
    if market == "coupang":
        sb = (send_ids or {}).get("shipment_box_id")
        os_ = (send_ids or {}).get("order_sheet_id")
        if not sb or not os_:
            return SendResult(market, order_no, False,
                              error="쿠팡 전송 식별자(shipment_box_id) 없음 — 추측 전송 금지")

    if not live:                                   # 드라이런 게이트 — 여기서 끝
        return SendResult(market, order_no, True, dry_run=True)

    try:
        if market == "coupang":
            from shared.platforms.coupang import orders as cp
            cp.send_tracking(sb, os_, code, str(invoice_no), client=client)
        else:                                      # smartstore
            from shared.platforms.smartstore import orders as ss
            ss.send_tracking([order_no], code, str(invoice_no), client=client)
    except Exception as e:                         # noqa: BLE001 — 실패는 표면화(조용한 성공 금지)
        return SendResult(market, order_no, False, error=str(e))

    return SendResult(market, order_no, True)
