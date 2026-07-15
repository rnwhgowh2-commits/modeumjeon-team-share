"""마켓별 「결제완료 → 배송준비중」 전환 요청 (발주확인/상품준비중 처리).

⚠️ 라이브 미검증 — 마켓별 실주문 1건으로 상태 전이를 확인한 뒤에만 신뢰한다.
   거짓 성공은 auto_confirm 의 되읽기 검증(전환 후 재조회)이 차단한다.
   식별자 없는 주문은 추측하지 않고 예외로 표면화(CLAUDE.md 🔒 추측 전송 금지).

마켓별 확신도(CONFIDENCE):
  · lotteon    — 코드검증: SellerDeliveryProgressStateInform apiNo=137, odPrgsStepCd=12(상품준비)
  · coupang    — 공식문서: PUT ordersheets/acknowledgement (ACCEPT→INSTRUCT)
  · smartstore — 공식문서: POST product-orders/confirm (발주확인)
  · eleven11   — 미배선: 발주확인 write API 미확정(read 로 complete→packaging 상태만 확인)
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

CONFIDENCE = {
    "lotteon": "코드검증(apiNo=137 문서판독)",
    "coupang": "공식문서(acknowledgement)",
    "smartstore": "공식문서(발주확인)",
    "eleven11": "미배선(발주확인 API 미확정)",
}


class ConfirmUnsupported(Exception):
    """그 마켓 전환이 아직 배선되지 않음 — 거짓 성공 대신 명시 실패."""


def confirm_targets(market: str, targets: list, client) -> None:
    """targets(결제완료 주문 dict, `_send_ids`·`오픈마켓주문번호` 포함)를 배송준비중으로 요청.

    실패는 예외로 던진다(호출부가 result='failed' 로 표면화). 이동 여부는 호출부가 되읽기로 확인.
    """
    if not targets:
        return

    if market == "coupang":
        from shared.platforms.coupang import orders as cp
        boxes = [(t.get("_send_ids") or {}).get("shipment_box_id") for t in targets]
        boxes = [b for b in boxes if b]
        if not boxes:
            raise ValueError("쿠팡: shipmentBoxId 없는 주문 — 전환 불가(추측 금지)")
        cp.acknowledge(boxes, client=client)

    elif market == "smartstore":
        from shared.platforms.smartstore import orders as ss
        pids = [str(t.get("오픈마켓주문번호") or "") for t in targets]
        pids = [p for p in pids if p]
        if not pids:
            raise ValueError("스마트스토어: productOrderId 없는 주문 — 전환 불가")
        ss.confirm_orders(pids, client=client)

    elif market == "lotteon":
        from shared.platforms.lotteon import shipping as lo
        for t in targets:
            ids = t.get("_send_ids") or {}
            missing = [k for k in ("od_no", "od_seq", "spd_no", "sitm_no", "qty")
                       if not ids.get(k)]
            if missing:
                raise ValueError(f"롯데온: 전환 식별자 없음({', '.join(missing)}) — 전환 불가")
            ok = lo.set_preparing(od_no=ids["od_no"], od_seq=ids["od_seq"],
                                  proc_seq=ids.get("proc_seq") or "1",
                                  spd_no=ids["spd_no"], sitm_no=ids["sitm_no"],
                                  qty=ids["qty"], client=client)
            if not ok:
                raise RuntimeError("롯데온 상품준비 처리 거부(returnCode)")

    elif market == "eleven11":
        # complete(결제완료) → packaging(배송준비중) 전이의 write(발주확인) API 가 아직 미확정.
        # 셀러 콘솔에서 실제 호출을 추출해 배선할 것(11st 는 MCP 차단 → 콘솔 유일통로).
        raise ConfirmUnsupported("11번가 발주확인(배송준비중 전환) API 미확정 — 확인 후 배선")

    else:
        raise ConfirmUnsupported(f"{market} 전환 미지원")
