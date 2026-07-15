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
    "eleven11": "콘솔추출(reqpackaging 발주처리)",
}


class ConfirmUnsupported(Exception):
    """그 마켓 전환이 아직 배선되지 않음 — 거짓 성공 대신 명시 실패."""


def confirm_targets(market: str, targets: list, client):
    """targets(결제완료 주문 dict, `_send_ids`·`오픈마켓주문번호` 포함)를 배송준비중으로 요청.

    실패는 예외로 던진다(호출부가 result='failed' 로 표면화).
    반환: 확정된 오픈마켓주문번호 집합(마켓 API 가 개별 결과를 줄 때) 또는 None.
      · None → 호출부가 '상태 되읽기'로 이동을 검증(쿠팡·롯데온: 상태가 바뀜).
      · 집합 → 그 API 응답이 유일한 검증 신호(스스: 발주확인이 상태를 안 바꿔 되읽기 불가).
    """
    if not targets:
        return None

    if market == "coupang":
        from shared.platforms.coupang import orders as cp
        boxes = [(t.get("_send_ids") or {}).get("shipment_box_id") for t in targets]
        boxes = [b for b in boxes if b]
        if not boxes:
            raise ValueError("쿠팡: shipmentBoxId 없는 주문 — 전환 불가(추측 금지)")
        cp.acknowledge(boxes, client=client)
        return None   # 상태 ACCEPT→INSTRUCT 로 바뀜 → 되읽기로 검증

    elif market == "smartstore":
        from shared.platforms.smartstore import orders as ss
        pids = [str(t.get("오픈마켓주문번호") or "") for t in targets]
        pids = [p for p in pids if p]
        if not pids:
            raise ValueError("스마트스토어: productOrderId 없는 주문 — 전환 불가")
        return ss.confirm_orders(pids, client=client)   # 확정 집합(상태 안 바뀜 → 이게 검증)

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
        from shared.platforms.eleven11 import shipping as el
        for t in targets:
            ids = t.get("_send_ids") or {}
            missing = [k for k in ("ord_no", "dlv_no") if not ids.get(k)]
            if missing:
                raise ValueError(f"11번가: 발주처리 식별자 없음({', '.join(missing)}) — 전환 불가")
            el.set_packaging(ord_no=ids["ord_no"], ord_prd_seq=ids.get("ord_prd_seq"),
                             dlv_no=ids["dlv_no"], client=client)
        return None   # 상태 발송대기→배송준비중 바뀜 → 되읽기로 검증

    else:
        raise ConfirmUnsupported(f"{market} 전환 미지원")
