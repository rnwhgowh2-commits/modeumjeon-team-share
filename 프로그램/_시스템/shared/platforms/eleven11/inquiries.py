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

_MAX_WINDOW_DAYS = 7

_PATH_PRODUCT_QNA = "/rest/prodqnaservices/prodqnalist/{s}/{e}/{status}"


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


def _windows(since: _dt.datetime, until: _dt.datetime):
    cur = since
    step = _dt.timedelta(days=_MAX_WINDOW_DAYS)
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
