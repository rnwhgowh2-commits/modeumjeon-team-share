# -*- coding: utf-8 -*-
"""롯데온 발송처리(배송상태 통보) — 송장 전송.

근거: 롯데ON API 센터 「배송상태 통보」 apiNo=137 공식 문서·요청 샘플 직접 판독(2026-07-10).
  POST /v1/openapi/delivery/v1/SellerDeliveryProgressStateInform
  body {"deliveryProgressStateList":[{
      dvRtrvDvsCd:"DV",            # 배송(회수 아님)
      odNo, odSeq, procSeq,        # 주문번호·주문순번(단품별)·처리순번
      odPrgsStepCd:"13",           # 발송완료  (12 상품준비 / 14 배송완료)
      dvTrcStatDttm:"yyyymmddhhmmss",
      invcNbr, dvCoCd, invcNo,     # 송장개수·택배사코드·송장번호 (13일 때 필수)
      spdNo, sitmNo, slQty}]}      # 상품번호·단품번호·수량 (필수)
  성공 = returnCode "0000"

⚠️ 택배사코드(dvCoCd)는 롯데온 전용이다 — 로젠택배: 롯데온 0005 / 쿠팡 KGB / 네이버 LOGEN.
   섞어 쓰면 엉뚱한 택배사로 등록된다.
⚠️ 라이브 미검증 — 실계정 1건 전송으로 최종 확인.

주의(문서): 발송완료 처리 전 「발송가능여부」 사전 체크 권장. 이미 취소된 주문이면 실패 처리된다.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

_PATH = "/v1/openapi/delivery/v1/SellerDeliveryProgressStateInform"
_STEP_SHIPPED = "13"          # 발송완료
_TYPE_DELIVERY = "DV"         # 배송(회수=RTRV)

# 롯데온 택배사코드(dvCoCd) — 공식 문서 「8. 택배사코드」에서 확인한 것만.
DELIVERY_COMPANY_CODES = {
    "롯데택배": "0001",
    "CJ대한통운": "0002",
    "우체국택배": "0004",
    "로젠택배": "0005",
    "한진택배": "0006",
    "건영택배": "0023",
    "경동택배": "0024",
    "대신택배": "0028",
    "일양로지스": "0041",
    "천일택배": "0043",
    "합동택배": "0049",
}


def send_tracking(*, od_no: str, od_seq, proc_seq, spd_no: str, sitm_no: str,
                  qty, delivery_company_code: str, invoice_number: str,
                  client=None, occurred_at: Optional[datetime] = None) -> bool:
    """단품 1건을 '발송완료(13)'로 통보하며 운송장번호를 등록. 성공 True / 실패 False.

    값은 모두 문자열로 보낸다(공식 요청 샘플이 문자열). invcNbr=1 (송장 1개).
    """
    if not str(invoice_number or "").strip():
        raise ValueError("운송장번호가 비어 있습니다.")
    if not str(delivery_company_code or "").strip():
        raise ValueError("롯데온 택배사코드(dvCoCd)가 비어 있습니다.")

    from shared.platforms.lotteon.client import LotteonClient
    client = client or LotteonClient()

    when = (occurred_at or datetime.now()).strftime("%Y%m%d%H%M%S")
    item = {
        "dvRtrvDvsCd": _TYPE_DELIVERY,
        "odNo": str(od_no),
        "odSeq": str(od_seq),
        "procSeq": str(proc_seq or "1"),
        "orglProcSeq": "",
        "clmNo": "",
        "odPrgsStepCd": _STEP_SHIPPED,
        "dvTrcStatDttm": when,
        "invcNbr": "1",
        "dvCoCd": str(delivery_company_code),
        "invcNo": str(invoice_number),
        "spdNo": str(spd_no),
        "spdNm": "",
        "sitmNo": str(sitm_no),
        "itmNm": "",
        "itmSlPrc": "",
        "slQty": str(qty),
    }
    try:
        resp = client.request(method="POST", path=_PATH,
                              body={"deliveryProgressStateList": [item]})
    except Exception as e:  # noqa: BLE001 — 실패는 표면화(조용한 성공 금지)
        logger.warning("[lotteon] 발송처리 실패 odNo=%s: %s", od_no, e)
        return False

    rc = str((resp or {}).get("returnCode"))
    if rc not in ("0000", "SUCCESS"):
        logger.warning("[lotteon] 발송처리 거부 odNo=%s returnCode=%s %s",
                       od_no, rc, (resp or {}).get("message") or "")
        return False
    return True
