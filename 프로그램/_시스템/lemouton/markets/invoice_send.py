# -*- coding: utf-8 -*-
"""송장(운송장) 전송 — 마켓 라우팅 · 택배사 코드 · 드라이런 게이트.

「주문 내역」에서 고른 주문에 운송장번호를 실제 마켓으로 전송한다.

안전 원칙(CLAUDE.md):
  · **드라이런 기본** — live=True 일 때만 마켓 API 를 실제로 호출한다.
  · **추측 금지** — 택배사 코드가 마켓마다 달라, 확보하지 못한 마켓은 보내지 않고 명시 실패.
  · **거짓 성공 금지** — 전송 함수가 없는 마켓(옥션·G마켓)은 조용히 성공시키지 않는다.
  · **식별자 추측 금지** — 쿠팡은 shipmentBoxId 가 없으면 보내지 않는다(주문 행의 _send_ids).

마켓별 전송 방식:
  · 쿠팡      = send_tracking(shipmentBoxId, orderSheetId, 택배사코드, 운송장번호)
  · 스마트스토어 = send_tracking([productOrderId], 택배사코드, 운송장번호)
                  ※ 「오픈마켓주문번호」가 곧 productOrderId 라 그대로 쓴다.
  · 롯데온     = 배송상태 통보(odNo·odSeq·spdNo·sitmNo·slQty + 발송완료 13)
  · 11번가     = reqdelivery(배송번호 dlvNo 단위). 택배사 코드는 실측 대조한 것만.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# 실제 전송 함수를 가진 마켓만. 나머지는 명시 실패.
#   11번가는 전송 경로(reqdelivery)는 구현됐지만 택배사 코드표가 비어 있어 실제로는 막힌다.
SUPPORTED_SEND = {"coupang", "smartstore", "lotteon", "eleven11"}


class CourierCodeUnknown(ValueError):
    """그 마켓의 택배사 코드를 확보하지 못함 — 추측해서 보내지 않는다."""


# 스마트스토어(네이버) 택배사 코드.
#   ⚠️ 쿠팡과 코드 체계가 **다르다** — 로젠택배: 쿠팡=KGB / 네이버=LOGEN. 섞으면 엉뚱한 택배사로 등록.
#   근거: 네이버 dispatch 를 실제 호출하는 독립 구현 2건이 동일 매핑 사용(2026-07-10 확인).
#   공식 문서(로그인 게이트)로 재확인 전까지 '라이브 미검증' — 없는 이름은 추측하지 않고 실패.
_SMARTSTORE_COURIER: dict[str, str] = {
    "로젠택배": "LOGEN",
    "CJ대한통운": "CJGLS",
    "한진택배": "HANJIN",
    "롯데택배": "LOTTE",
    "우체국택배": "EPOST",
}


# 11번가 택배사 코드(dlvEtprsCd) — **실계정 발송 이력으로 대조한 것만** 넣는다.
#   오픈소스 구현들이 서로 다른 체계를 주장했다(로젠: 5자리 "00002" vs 2자리 "05").
#   2026-07-10 실측으로 5자리 체계 확정 + 아래 두 값은 셀러오피스 배송관리 화면의 택배사
#   이름과 송장번호로 1:1 대조(로젠 92816272404→00002 / 롯데 317651308380→00012).
#   나머지(CJ 00034·한진 00011 등)는 공개 출처 값만 있고 대조를 못 해 넣지 않는다 —
#   틀린 코드로 보내면 고객 배송조회에 엉뚱한 택배사가 뜬다(조용한 오표기).
#   추가 확인: /orders/diag/eleven11-couriers?invoice=<송장번호>
_ELEVEN11_COURIER: dict[str, str] = {
    "로젠택배": "00002",
    "롯데택배": "00012",
}


def resolve_courier_code(market: str, courier_name: str) -> str:
    """마켓별 택배사 코드. 근거 없는 값은 만들지 않고 CourierCodeUnknown.

    ⚠️ 같은 택배사라도 마켓마다 코드가 다르다 —
       로젠택배: 쿠팡 KGB · 네이버 LOGEN · 롯데온 0005.
    """
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
    if market == "lotteon":
        from shared.platforms.lotteon.shipping import DELIVERY_COMPANY_CODES
        code = DELIVERY_COMPANY_CODES.get(courier_name)
        if not code:
            raise CourierCodeUnknown(f"롯데온 택배사 코드 없음: {courier_name}")
        return code
    if market == "eleven11":
        code = _ELEVEN11_COURIER.get(courier_name)
        if not code:
            raise CourierCodeUnknown(
                f"11번가 택배사 코드 미검증: {courier_name} — 실계정 발송 이력으로 대조 후 전송")
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

    ids = send_ids or {}
    if market == "coupang":
        if not ids.get("shipment_box_id") or not ids.get("order_sheet_id"):
            return SendResult(market, order_no, False,
                              error="쿠팡 전송 식별자(shipment_box_id) 없음 — 추측 전송 금지")
    if market == "lotteon":
        missing = [k for k in ("od_no", "od_seq", "spd_no", "sitm_no", "qty") if not ids.get(k)]
        if missing:
            return SendResult(market, order_no, False,
                              error=f"롯데온 전송 식별자 없음({', '.join(missing)}) — 추측 전송 금지")
    if market == "eleven11" and not ids.get("dlv_no"):
        return SendResult(market, order_no, False,
                          error="11번가 전송 식별자(배송번호 dlvNo) 없음 — 주문번호로 대체 불가")

    if not live:                                   # 드라이런 게이트 — 여기서 끝
        return SendResult(market, order_no, True, dry_run=True)

    try:
        if market == "coupang":
            from shared.platforms.coupang import orders as cp
            cp.send_tracking(ids["shipment_box_id"], ids["order_sheet_id"],
                             code, str(invoice_no), client=client)
        elif market == "lotteon":
            from shared.platforms.lotteon import shipping as lo
            ok = lo.send_tracking(od_no=ids["od_no"], od_seq=ids["od_seq"],
                                  proc_seq=ids.get("proc_seq") or "1",
                                  spd_no=ids["spd_no"], sitm_no=ids["sitm_no"],
                                  qty=ids["qty"], delivery_company_code=code,
                                  invoice_number=str(invoice_no), client=client)
            if not ok:
                return SendResult(market, order_no, False, error="롯데온 발송처리 거부(returnCode)")
        elif market == "eleven11":
            from shared.platforms.eleven11 import shipping as el
            el.send_tracking(dlv_no=ids["dlv_no"], invoice_number=str(invoice_no),
                             delivery_company_code=code, client=client)
        else:                                      # smartstore
            from shared.platforms.smartstore import orders as ss
            ss.send_tracking([order_no], code, str(invoice_no), client=client)
    except Exception as e:                         # noqa: BLE001 — 실패는 표면화(조용한 성공 금지)
        return SendResult(market, order_no, False, error=str(e))

    return SendResult(market, order_no, True)
