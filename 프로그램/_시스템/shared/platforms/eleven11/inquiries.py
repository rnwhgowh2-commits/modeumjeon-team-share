# -*- coding: utf-8 -*-
"""11번가 문의 조회 (셀러 Open API, XML) thin wrapper.

공식 문서(셀러 콘솔 실측, 2026-07-16):
- 상품 QnA 목록:  GET /rest/prodqnaservices/prodqnalist/{startTime}/{endTime}/{answerStatus}
                  · startTime/endTime = YYYYMMDD (조회 최대 7일)
                  · answerStatus = 00(전체)/01(답변완료)/02(미답변)
                  · 응답 root <ns2:productQnas> 하위 <ns2:productQna> 반복.

인증·재시도·euc-kr 은 Eleven11Client 가 처리. 이 모듈은 경로·XML 파싱만.
★긴급문의·11톡은 스펙 확보 후 추가(현재 상품 QnA만).
"""
from __future__ import annotations

import datetime as _dt
import re as _re
import xml.etree.ElementTree as _ET
from xml.sax.saxutils import escape as _xml_escape

_MAX_WINDOW_DAYS = 7

_PATH_PRODUCT_QNA = "/rest/prodqnaservices/prodqnalist/{s}/{e}/{status}"
_PATH_PRODUCT_QNA_ANSWER = "/rest/prodqnaservices/prodqnaanswer/{brd}/{prd}"
_PATH_ALIMI = "/rest/alimi/getalimilist/{s}/{e}"   # 처리상태·주문번호 선택 → 전체는 2세그먼트


def _ymd(d: _dt.datetime) -> str:
    return d.strftime("%Y%m%d")


def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse(xml_text: str):
    if not xml_text:
        return None
    cleaned = _re.sub(r"<\?xml[^>]*\?>", "", xml_text, count=1).lstrip()
    if not cleaned:
        return None
    return _ET.fromstring(cleaned)


def _windows(since: _dt.datetime, until: _dt.datetime, days: int = _MAX_WINDOW_DAYS):
    cur = since
    step = _dt.timedelta(days=days)
    if until <= since:
        yield since, until
        return
    while cur < until:
        nxt = min(cur + step, until)
        yield cur, nxt
        cur = nxt


def iter_product_qna(since: _dt.datetime, until: _dt.datetime, *, client,
                     answer_status: str = "00"):
    """상품 QnA 목록. GET /rest/prodqnaservices/prodqnalist/{s}/{e}/{status}.

    answer_status: 00(전체)/01(답변완료)/02(미답변). 7일 윈도우 분할 + brdInfoNo 중복제거.
    yield = <productQna> 자식 필드 dict(answerYn·brdInfoSbjct·brdInfoCont·answerCont·
    prdNm·memNM·qnaDtlsCdNm·createDt·brdInfoNo·brdInfoClfNo·ordNoDe 등).
    """
    seen = set()
    for w_from, w_to in _windows(since, until):
        path = _PATH_PRODUCT_QNA.format(s=_ymd(w_from), e=_ymd(w_to), status=answer_status)
        xml_text = client.request("GET", path)
        root = _parse(xml_text)
        if root is None:
            continue
        for el in root.iter():
            if _localname(el.tag) != "productQna":
                continue
            row = {}
            for child in el:
                row[_localname(child.tag)] = (child.text or "").strip()
            key = row.get("brdInfoNo")
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            yield row


def iter_emergency(since: _dt.datetime, until: _dt.datetime, *, client):
    """긴급알리미 조회(긴급문의·긴급알림톡). GET /rest/alimi/getalimilist/{s}/{e}.

    처리상태·주문번호 경로 세그먼트는 선택 → 전체는 생략(2세그먼트). 최대 30일 윈도우.
    ★답변 처리 API는 2024/02/14 중지 → 조회 전용.
    응답 root <ns2:alimi> 하위 <ns2:alimListInfo> 반복. result_code=0 은 '결과 없음'(에러 아님).
    yield = alimListInfo 필드 dict(emerNtceSeq·emerNtceClfNm1(긴급문의/긴급알림톡)·
    emerNtceSubject·emerCtnt·prdNm·memNm·emerNtceCrntCd·emerReplyCtnt(답변) 등).
    """
    seen = set()
    for w_from, w_to in _windows(since, until, days=30):
        path = _PATH_ALIMI.format(s=_ymd(w_from), e=_ymd(w_to))
        xml_text = client.request("GET", path)
        root = _parse(xml_text)
        if root is None:
            continue
        for el in root.iter():
            if _localname(el.tag) != "alimListInfo":
                continue
            row = {}
            for child in el:
                ln = _localname(child.tag)
                if ln == "emerReplyList":   # 답변 리스트(중첩) → 합쳐서 담기
                    reps = [(_r.text or "").strip() for _r in child.iter()
                            if _localname(_r.tag) == "emerReplyCtnt"]
                    row["emerReplyCtnt"] = " / ".join([r for r in reps if r])
                else:
                    row[ln] = (child.text or "").strip()
            key = row.get("emerNtceSeq")
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            yield row


def answer_product_qna(brd_info_no: str, prd_no: str, answer_cont: str, *, client) -> dict:
    """상품 QnA 답변 등록/수정. PUT /rest/prodqnaservices/prodqnaanswer/{brdInfoNo}/{prdNo}.

    ★답변 완료 시 문의자에게 이메일 자동 발송(고객 대면 발신) → 전송 게이트(LIVE OFF) 필수.
    body = <ProductQna><answerCont>...</answerCont></ProductQna> (XML euc-kr).
    응답 <ClientMessage> resultCode=200 성공. 반환=파싱 dict.
    """
    path = _PATH_PRODUCT_QNA_ANSWER.format(brd=brd_info_no, prd=prd_no)
    body = ('<?xml version="1.0" encoding="euc-kr"?>'
            f"<ProductQna><answerCont>{_xml_escape(answer_cont or '')}</answerCont></ProductQna>")
    xml_text = client.request("PUT", path, body=body)
    root = _parse(xml_text)
    out = {}
    if root is not None:
        for child in root:
            out[_localname(child.tag)] = (child.text or "").strip()
    return out
