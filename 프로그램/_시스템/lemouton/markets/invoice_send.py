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


# 스마트스토어(네이버) 택배사 코드 — **라이브 실측**(2026-07-10).
#   기존 "로젠택배: LOGEN" 은 오픈소스 구현 2건을 근거로 삼은 추측이었고 **틀렸다**.
#   실측: 판매자센터에 「로젠택배」로 표시되는 주문의 delivery.deliveryCompany 값이 KGB
#   (로젠의 옛 상호가 KGB택배). 쿠팡과 우연히 같은 코드일 뿐 체계가 같다는 뜻은 아니다.
#
#   최근 7일 주문에서 관측된 코드: KGB(84) · CJGLS(8) · HANJIN(1) · HYUNDAI(1) · JMNP(1).
#   네이버는 코드표 API 를 주지 않는다(후보 3경로 모두 404) — 이름↔코드 근거는 주문 단위 교차확인뿐.
#   ⚠️ **관측된 코드 ≠ 확정된 이름.** 11번가와 같은 기준(실계정 1:1 대조)을 적용해,
#      대조한 로젠만 싣는다. CJGLS·HANJIN·HYUNDAI·JMNP 는 코드가 보였을 뿐 어느 택배사인지
#      대조하지 못했고, 옛 매핑의 LOTTE·EPOST 는 관측조차 되지 않았다.
#      확정 방법: 그 택배사로 1건 발송한 뒤 그 주문의 delivery.deliveryCompany 를 읽는다.
_SMARTSTORE_COURIER: dict[str, str] = {
    "로젠택배": "KGB",        # 판매자센터 화면 「로젠택배」 ↔ API KGB 1:1 대조 완료
}


# 이미 송장이 붙어 배송이 진행된 주문 — 다른 번호로 덮어쓰면 고객 배송조회가 오염된다.
_ALREADY_SHIPPED_STATES = {"배송중", "배송완료", "구매확정", "발송완료"}


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


def _verify_smartstore(resp, order_no: str) -> Optional[str]:
    """네이버 dispatch 응답 검증. 실패 사유 문자열, 성공이면 None.

    ★ 네이버는 HTTP 200 을 주면서 본문에 개별 실패를 담는다. 2xx 만 보고 성공을 반환하면
      마켓에 반영되지 않은 송장이 화면에 「✓ 전송」으로 뜬다(2026-07-10 실제 발생).
    """
    data = (resp or {}).get("data") or resp or {}
    fails = data.get("failProductOrderInfos") or []
    for f in fails:
        if str(f.get("productOrderId")) == order_no:
            return f"스마트스토어 거부: {f.get('code') or ''} {f.get('message') or ''}".strip()
    if fails:
        return f"스마트스토어 거부: {fails[0]}"

    ok = [str(x) for x in (data.get("successProductOrderIds") or [])]
    if order_no in ok:
        return None
    if ok:
        return "스마트스토어 성공 목록에 이 주문이 없음 — 등록되지 않았다"
    return "스마트스토어 응답에서 성공을 확인하지 못함 — 전송 여부 확인 불가"


def _verify_coupang(resp, order_no: str) -> Optional[str]:
    """쿠팡 invoices 응답 검증. 쿠팡도 HTTP 200 본문에 code/succeed 로 실패를 담는다."""
    payload = resp or {}
    code = str(payload.get("code", ""))
    if code and code not in ("200", "SUCCESS"):
        return f"쿠팡 거부: {code} {payload.get('message') or ''}".strip()

    data = payload.get("data")
    items = data if isinstance(data, list) else ([data] if isinstance(data, dict) else [])
    for it in items:
        if isinstance(it, dict) and it.get("succeed") is False:
            return f"쿠팡 거부: {it.get('resultMessage') or it}"

    if not code:
        return "쿠팡 응답에서 성공을 확인하지 못함 — 전송 여부 확인 불가"
    return None


def read_registered_invoice(*, market: str, order_no, send_ids: Optional[dict] = None,
                            client=None) -> Optional[str]:
    """전송 직후 마켓에 **실제 등록된** 송장번호를 되읽는다. 못 읽으면 None.

    화면의 「✓ 전송」 숫자를 입력값이 아니라 이 값으로 표시하기 위한 것 — 숫자 자체가
    '마켓에 등록됨'의 증거가 되게 한다(2026-07-10 오입력 사고 재발 방지).

    ⚠️ None 은 '전송 실패'가 아니라 '아직 확인 불가'다(전파 지연 등). 전송의 성공/실패는
       send_invoice 의 응답검증이 이미 판정했다. 못 읽었다고 입력값을 마켓값인 척 쓰지 않는다.
    """
    order_no = str(order_no)
    ids = send_ids or {}
    try:
        if market == "smartstore":
            from shared.platforms.smartstore import orders as ss
            r = ss.fetch_order_detail([order_no], client=client)
            for it in (r or {}).get("data") or []:
                po = it.get("productOrder") or {}
                if str(po.get("productOrderId")) == order_no:
                    return (it.get("delivery") or {}).get("trackingNumber") or None

        elif market == "coupang":
            from shared.platforms.coupang import orders as cp
            osid = ids.get("order_sheet_id")
            if not osid:
                return None
            r = cp.fetch_order_detail(str(osid), client=client)
            data = (r or {}).get("data")
            boxes = data if isinstance(data, list) else ([data] if isinstance(data, dict) else [])
            for box in boxes:
                if box.get("invoiceNumber"):
                    return str(box["invoiceNumber"])
                for it in (box.get("orderItems") or []):
                    if it.get("invoiceNumber"):
                        return str(it["invoiceNumber"])

        elif market == "lotteon":
            from shared.platforms.lotteon import orders as lo
            import datetime as _dt
            until = _dt.datetime.now()
            since = until - _dt.timedelta(days=3)
            odno = str(ids.get("od_no") or order_no)
            odseq = str(ids.get("od_seq") or "")
            best, best_dttm = None, ""
            for it in lo.iter_progress_states(since, until, client=client):
                if str(it.get("odNo")) != odno:
                    continue
                if odseq and str(it.get("odSeq")) != odseq:
                    continue
                dttm = str(it.get("dvTrcStatDttm") or "")
                if it.get("invcNo") and dttm >= best_dttm:
                    best, best_dttm = str(it.get("invcNo")), dttm
            return best

        elif market == "eleven11":
            from shared.platforms.eleven11 import orders as el
            import datetime as _dt
            until = _dt.datetime.now()
            since = until - _dt.timedelta(days=3)
            dlv = str(ids.get("dlv_no") or "")
            # 송장 등록 직후 상태 = 배송중(iter_shipping). 배송완료는 폴백.
            for iter_fn in (el.iter_shipping, el.iter_delivered):
                for od in iter_fn(since, until, client=client):
                    hit = (dlv and str(od.get("dlvNo")) == dlv) or str(od.get("ordNo")) == order_no
                    if hit and od.get("invcNo"):
                        return str(od.get("invcNo"))
    except Exception:   # noqa: BLE001 — 되읽기 실패는 '확인 불가'(None), 전송 판정과 무관
        return None
    return None


def send_invoice(*, market: str, order_no, courier_name: str, invoice_no,
                 send_ids: Optional[dict] = None, client=None,
                 live: bool = False, order_status: Optional[str] = None) -> SendResult:
    """운송장번호 1건 전송. 기본은 드라이런(외부 호출 없음).

    Args:
        market: 마켓 슬러그
        order_no: 「오픈마켓주문번호」 (스스는 곧 productOrderId)
        courier_name: 화면에서 고른 택배사 이름 (예: "로젠택배")
        invoice_no: 운송장번호
        send_ids: 마켓별 전송 식별자 (쿠팡: shipment_box_id·order_sheet_id)
        client: 계정별 마켓 클라이언트 (없으면 각 플랫폼 기본)
        live: True 일 때만 실제 전송
        order_status: 화면의 「주문상태」. 이미 발송된 주문이면 덮어쓰지 않는다.
    """
    order_no = str(order_no)

    if market not in SUPPORTED_SEND:
        return SendResult(market, order_no, False,
                          error=f"{market} 는 송장 전송 미지원 (전송 함수 없음)")

    if order_status and str(order_status).strip() in _ALREADY_SHIPPED_STATES:
        return SendResult(market, order_no, False,
                          error=f"이미 발송된 주문({order_status}) — 송장 덮어쓰기 금지")

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
            resp = cp.send_tracking(ids["shipment_box_id"], ids["order_sheet_id"],
                                    code, str(invoice_no), client=client)
            reason = _verify_coupang(resp, order_no)
            if reason:
                return SendResult(market, order_no, False, error=reason)
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
            resp = ss.send_tracking([order_no], code, str(invoice_no), client=client)
            reason = _verify_smartstore(resp, order_no)
            if reason:
                return SendResult(market, order_no, False, error=reason)
    except Exception as e:                         # noqa: BLE001 — 실패는 표면화(조용한 성공 금지)
        return SendResult(market, order_no, False, error=str(e))

    return SendResult(market, order_no, True)
