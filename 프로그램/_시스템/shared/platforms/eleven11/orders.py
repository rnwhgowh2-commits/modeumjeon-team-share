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
_PATH_PACKAGING = "/rest/ordservices/packaging/{s}/{e}"  # 배송준비중 전체(발주확인 완료), 기간조회
_PATH_DELIVERED = "/rest/ordservices/dlvcompleted/{s}/{e}"  # 배송완료
_PATH_COMPLETED = "/rest/ordservices/completed/{s}/{e}"   # 판매완료(구매확정)
_PATH_SHIPPING = "/rest/ordservices/shipping/{s}/{e}"    # 배송중(송장·주문번호만)
# 클레임 목록조회(공개문서 실측 2026-07-09) — 취소/반품/교환. 최대 30일이나 7일 윈도우로 분할.
_PATH_CANCEL = "/rest/claimservice/cancelorders/{s}/{e}"     # 취소요청 목록
_PATH_RETURN = "/rest/claimservice/returnorders/{s}/{e}"     # 반품요청 목록
_PATH_EXCHANGE = "/rest/claimservice/exchangeorders/{s}/{e}"  # 교환요청 목록
_MAX_WINDOW_DAYS = 7        # 문서: 조회기간 최대 7일


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


def iter_preparing(since: _dt.datetime, until: _dt.datetime, *, client):
    """배송준비중(발주확인 완료·발송 전) 전체 목록. GET /rest/ordservices/packaging.

    ★ todaydelivery/delaydelivery(오늘발송·기한경과)는 '발송해야 할' 것만 줘서 발송예정일이 미래인
    배송준비중(예약·주문제작)이 빠졌음. packaging 은 발주확인 완료 주문 '전체'를 기간조회로 준다
    (필드=결제완료와 동일). 서버 프로브로 today/delay 가 0 반환·개별조회는 301 배송준비중 확인 후 교체.
    """
    return _iter_path(_PATH_PACKAGING, since, until, client=client)


def iter_cancel(since: _dt.datetime, until: _dt.datetime, *, client):
    """취소요청 목록. GET /rest/claimservice/cancelorders. 필드: ordNo·ordPrdSeq·prdNo·
    slctPrdOptNm·ordCnQty(취소수량)·ordCnRsnCd/ordCnDtlsRsn(사유)·ordCnStatCd·createDt."""
    return _iter_path(_PATH_CANCEL, since, until, client=client)


def iter_return(since: _dt.datetime, until: _dt.datetime, *, client):
    """반품요청 목록. GET /rest/claimservice/returnorders. 필드: ordNo·ordPrdSeq·prdNo·
    optName·clmReqQty·clmReqRsn/clmReqCont(사유)·clmStat·ordNm·reqDt 등."""
    return _iter_path(_PATH_RETURN, since, until, client=client)


def iter_exchange(since: _dt.datetime, until: _dt.datetime, *, client):
    """교환요청 목록. GET /rest/claimservice/exchangeorders. 반품과 유사 클레임 필드."""
    return _iter_path(_PATH_EXCHANGE, since, until, client=client)


def iter_shipping(since: _dt.datetime, until: _dt.datetime, *, client):
    """배송중. GET /rest/ordservices/shipping/{s}/{e} (7일 윈도우).

    ⚠️ 이 엔드포인트는 ordNo·ordPrdSeq·invcNo(송장)·dlvEtprsCd(택배사)·sndEndDt(발송일)만 반환 —
    상품명·수령자·주소·단가 없음(문서 실측). 주문일(ordDt)도 없어 order_export 에서 ordNo 앞 8자리로 보정.
    """
    return _iter_path(_PATH_SHIPPING, since, until, client=client)
