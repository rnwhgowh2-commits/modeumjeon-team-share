# -*- coding: utf-8 -*-
"""11번가 셀러 Open API 주문조회 — 발주확인 내역(기간별 결제완료 목록조회).

근거(공개문서 openapi.11st.co.kr 개발가이드 > 주문 > 결제완료, 2026-07-07 실측):
  GET https://api.11st.co.kr/rest/ordservices/complete/{startTime}/{endTime}
  · startTime/endTime = "YYYYMMDDhhmm" (분 단위). 조회기간 최대 7일, 최대 3,000건.
  · 인증 = openapikey 헤더(Eleven11Client). 응답 = XML(euc-kr).
  · 응답 root <ns2:orders> 하위 <ns2:order> 반복(주문 상품라인 1개 = 1 요소).
    주요 필드: ordNo(주문번호)·ordDt(주문일시)·prdNm(상품명)·prdNo(상품번호)·
    slctPrdOptNm(선택옵션)·ordQty(수량)·selPrc(판매단가)·dlvCst/bmDlvCst(배송비/묶음배송비)·
    bndlDlvSeq·bndlDlvYN(묶음배송)·rcvrNm(수령자)·rcvrPrtblNo/rcvrTlphn(수령자 연락처)·
    rcvrBaseAddr+rcvrDtlsAddr(주소)·rcvrMailNo(우편)·ordNm/memID(구매자)·
    ordPrtblTel/ordTlphnNo(구매자 연락처)·ordDlvReqCont(배송요청).

이 엔드포인트는 '결제완료(발주확인 대상)' 목록이라 상태는 결제완료(=발송대기)로 본다.
"""
from __future__ import annotations

import datetime as _dt
import re as _re
import xml.etree.ElementTree as _ET

_PATH = "/rest/ordservices/complete/{s}/{e}"             # 결제완료(발송대기)
_PATH_DELIVERED = "/rest/ordservices/dlvcompleted/{s}/{e}"  # 배송완료
_PATH_COMPLETED = "/rest/ordservices/completed/{s}/{e}"   # 판매완료(구매확정)
_MAX_WINDOW_DAYS = 7        # 문서: 조회기간 최대 7일
# 참고: 배송중(/rest/ordservices/shipping)은 송장·주문번호만 반환(상품·주소 없음) → 행 미생성.


def _fmt(d: _dt.datetime) -> str:
    return d.strftime("%Y%m%d%H%M")


def _windows(since: _dt.datetime, until: _dt.datetime):
    cur = since
    step = _dt.timedelta(days=_MAX_WINDOW_DAYS)
    while cur < until:
        nxt = min(cur + step, until)
        yield cur, nxt
        cur = nxt


def _localname(tag: str) -> str:
    """'{ns}order' → 'order' (네임스페이스 제거)."""
    return tag.rsplit("}", 1)[-1]


def _parse(xml_text: str):
    """euc-kr 선언 포함 XML 문자열 파싱(선언 제거 후 str 파싱)."""
    if not xml_text:
        return None
    cleaned = _re.sub(r"<\?xml[^>]*\?>", "", xml_text, count=1).lstrip()
    if not cleaned:
        return None
    return _ET.fromstring(cleaned)


def _iter_path(path_tmpl: str, since: _dt.datetime, until: _dt.datetime, *, client):
    """경로 템플릿 하나로 7일 윈도우 분할 조회 + <order> 파싱 + (ordNo,ordPrdSeq) 중복제거.

    client.request(XML 텍스트) → 파싱. HTTP 오류는 client 가 예외로 표면화(추측·폴백 금지).
    """
    seen = set()
    for w_from, w_to in _windows(since, until):
        path = path_tmpl.format(s=_fmt(w_from), e=_fmt(w_to))
        xml_text = client.request("GET", path)
        root = _parse(xml_text)
        if root is None:
            continue
        for el in root.iter():
            if _localname(el.tag) != "order":
                continue
            od = {}
            for child in el:
                od[_localname(child.tag)] = (child.text or "").strip()
            key = (od.get("ordNo"), od.get("ordPrdSeq"), od.get("prdNo"))
            if key in seen:
                continue
            seen.add(key)
            yield od


def iter_orders(since: _dt.datetime, until: _dt.datetime, *, client):
    """결제완료(발주확인·발송대기) 주문 상품라인. GET /rest/ordservices/complete."""
    return _iter_path(_PATH, since, until, client=client)


def iter_delivered(since: _dt.datetime, until: _dt.datetime, *, client):
    """배송완료 주문 상품라인. GET /rest/ordservices/dlvcompleted.

    전체 필드(수령자·주소·단가 selPrc·옵션·송장 invcNo·dlvEndDt 배송완료일). 정산예정금액(stlPlnAmt)은
    없음(정산 전 단계) → 공란.
    """
    return _iter_path(_PATH_DELIVERED, since, until, client=client)


def iter_completed(since: _dt.datetime, until: _dt.datetime, *, client):
    """판매완료(구매확정) 주문 상품라인. GET /rest/ordservices/completed.

    구매확정 목록 — 수령자·주소·단가(selPrc)는 미제공(배송 완료·정산 단계라 미포함).
    ordNo·ordDt·prdNm·slctPrdOptNm·ordQty·dlvCst·ordAmt·ordPayAmt·pocnfrmDt(구매확정일) 등.
    """
    return _iter_path(_PATH_COMPLETED, since, until, client=client)
