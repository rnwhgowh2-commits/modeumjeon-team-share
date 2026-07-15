# -*- coding: utf-8 -*-
"""11번가 발송처리(송장 등록) — GET /rest/ordservices/reqdelivery.

근거: 11번가 셀러 REST 는 로그인 게이트라 공식문서 직독 불가 → **독립 구현 3건 교차 확인**(2026-07-10).
  · ctrlv290/Dyflux `_CLASS/API_11st.php` — 공식문서 URL 스펙을 주석으로 옮겨 적음
        /reqdelivery/[sendDt]/[dlvMthdCd]/[dlvEtprsCd]/[invcNo]/[dlvNo]/[partDlvYn]/[ordNo]/[ordPrdSeq]
  · sbk0674-web/samba-wave `proxy/elevenst.py` — 운영 중(에러코드 의미가 주석에 기록됨)
  · yoolk/elevenstreet `api/order.rb`
  세그먼트 순서는 3건 모두 일치. sendDt 형식은 2건이 YYYYMMDDhhmm(나머지 1건은 이상값).

전체발송(부분발송 아님)은 배송번호(dlvNo) 단위 5-세그먼트 형태로 충분하다 —
운영 중인 구현이 쓰는 형태를 따른다. 뒤 3개(partDlvYn·ordNo·ordPrdSeq)는 부분발송용.

결과 판정(⚠️ 거짓 성공 금지):
  · result_code "0"                → 성공
  · "-3308" 합포장으로 이미 발송   → 목표상태 도달 → 성공
  · "-3309" 이미 배송완료          → 목표상태 도달 → 성공
  · "-3313" 발송처리할 목록 없음   → **실패**. 송장이 등록되지 않는데 성공으로 치면
                                     택배사·송장 빈칸인 채 「전송완료」로 표시된다.
  · 그 외                          → 실패(코드·메시지 표면화)

⚠️ 택배사코드(dlvEtprsCd)는 이 모듈에 두지 않는다 — 출처마다 값이 달라(로젠: 00002 vs 05)
   확정 전까지 lemouton.markets.invoice_send 가 전송을 막는다.
⚠️ 라이브 미검증.
"""
from __future__ import annotations

import logging
import re as _re
import xml.etree.ElementTree as _ET
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

_PATH = "/rest/ordservices/reqdelivery/{send_dt}/{mthd}/{corp}/{invc}/{dlv_no}"
_PATH_PACKAGING = "/rest/ordservices/reqpackaging/{ord_no}/{ord_prd_seq}/{add_yn}/{add_no}/{dlv_no}"
_METHOD_PARCEL = "01"                 # 배송방식: 01=택배 (03=직접 04=퀵 05=배송없음)

# 목표상태(발송됨)에 이미 도달한 코드 — 재전송·합포장에서 정상적으로 나온다.
_ALREADY_SHIPPED = {"-3308", "-3309"}


class Eleven11ShipError(RuntimeError):
    """11번가 발송처리 거부. 송장이 등록되지 않았다."""


def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _result(xml_text: str) -> tuple[str, str]:
    """응답 XML → (result_code, result_text). 파싱 실패는 예외로 표면화."""
    cleaned = _re.sub(r"<\?xml[^>]*\?>", "", xml_text or "", count=1).strip()
    if not cleaned:
        raise Eleven11ShipError("발송처리 응답이 비어 있음")
    try:
        root = _ET.fromstring(cleaned)
    except _ET.ParseError as e:
        raise Eleven11ShipError(f"발송처리 응답 XML 파싱 실패: {cleaned[:200]}") from e

    found = {_localname(el.tag): (el.text or "").strip() for el in root.iter()}
    return found.get("result_code", ""), found.get("result_text", "")


def send_tracking(*, dlv_no: str, invoice_number: str, delivery_company_code: str,
                  client=None, occurred_at: Optional[datetime] = None,
                  delivery_method_code: str = _METHOD_PARCEL) -> bool:
    """배송번호 1건에 송장 등록. 성공하면 True, 거부되면 Eleven11ShipError.

    Args:
        dlv_no: 배송번호(주문조회 응답의 dlvNo). 주문번호로 대체 불가.
        invoice_number: 운송장번호
        delivery_company_code: 11번가 택배사코드(dlvEtprsCd)
        occurred_at: 발송일시(미지정 시 현재). YYYYMMDDhhmm 으로 보낸다.
    """
    if not str(dlv_no or "").strip():
        raise ValueError("배송번호(dlvNo) 없음 — 발송처리 불가")
    if not str(invoice_number or "").strip():
        raise ValueError("운송장번호 없음")
    if not str(delivery_company_code or "").strip():
        raise ValueError("택배사 코드 없음")

    if client is None:
        from shared.platforms.eleven11.client import Eleven11Client
        client = Eleven11Client()

    when = (occurred_at or datetime.now()).strftime("%Y%m%d%H%M")
    path = _PATH.format(send_dt=when, mthd=delivery_method_code,
                        corp=str(delivery_company_code), invc=str(invoice_number),
                        dlv_no=str(dlv_no))

    code, text = _result(client.request("GET", path))
    if code == "0":
        return True
    if code in _ALREADY_SHIPPED:
        logger.info("[11번가] 발송처리: 이미 처리됨(%s) dlvNo=%s — 성공 처리", code, dlv_no)
        return True
    raise Eleven11ShipError(f"11번가 발송처리 거부 ({code}): {text}")


def set_packaging(*, ord_no: str, ord_prd_seq: str, dlv_no: str,
                  add_prd_yn: str = "N", add_prd_no: str = "null", client=None) -> bool:
    """발주처리 — 발송대기(결제완료) → 배송준비중(packaging). 성공 True / 거부 Eleven11ShipError.

    공식(셀러 OPEN API CENTER 「주문 > 발주처리」, 2026-07-15 콘솔 추출):
      GET /rest/ordservices/reqpackaging/{ordNo}/{ordPrdSeq}/{addPrdYn}/{addPrdNo}/{dlvNo}
      성공 = result_code "0" ("전체 1건이 정상적으로 발주처리가 되었습니다").
      추가구성상품 없으면 addPrdYn=N, addPrdNo=null(리터럴 문자열).
    ⚠️ 라이브 미검증 — 실주문 1건으로 확인 후 신뢰(auto_confirm 되읽기 검증 병행).
    """
    if not str(ord_no or "").strip():
        raise ValueError("11번가 발주처리: 주문번호(ordNo) 없음 — 전환 불가")
    if not str(dlv_no or "").strip():
        raise ValueError("11번가 발주처리: 배송번호(dlvNo) 없음 — 전환 불가")
    if client is None:
        from shared.platforms.eleven11.client import Eleven11Client
        client = Eleven11Client()
    path = _PATH_PACKAGING.format(ord_no=str(ord_no), ord_prd_seq=str(ord_prd_seq or ""),
                                  add_yn=(add_prd_yn or "N"), add_no=(add_prd_no or "null"),
                                  dlv_no=str(dlv_no))
    code, text = _result(client.request("GET", path))
    if code == "0":
        return True
    raise Eleven11ShipError(f"11번가 발주처리 거부 ({code}): {text}")
