# -*- coding: utf-8 -*-
"""11번가 정산금액(settlementList, 구매확정분) — 실정산액 조회.

근거(공개문서 openapi.11st.co.kr 개발가이드 > 정산, 2026-07-16 확인):
  GET https://api.11st.co.kr/rest/settlement/settlementList/{startTime}/{endTime}
  · startTime/endTime = "YYYYMMDD"(일 단위, orders.py 의 분단위 complete 등과 다름).
    조회기간 최대 31일.
  · 인증 = openapikey 헤더(Eleven11Client, orders.py 와 동일). 응답 = XML(euc-kr).
  · 응답 root <ns2:seStlDtlList> 하위에 정산 상세 라인이 반복(orders.py 의
    <ns2:orders>/<ns2:order> 와 동일한 얕은 구조 — root 의 직계 자식이 각 라인).
    주요 필드: ordNo(주문번호)·ordPrdSeq(주문순번)·stlAmt(정산금액=정산금액-공제)·
    selFee(수수료)·pocnfrmDt(구매확정일)·totalCount.

  이 목록은 '전일자 구매확정분'만 나온다(미정산 주문은 포함 안 됨). order_export.py 의
  stlPlnAmt(정산예정 추정치) 대신 이 실정산액이 있으면 최우선으로 덮어써 오차0 로 만든다
  (구매확정 전 주문은 이 API 에 없어 기존 stlPlnAmt/추정이 그대로 유지된다 — 폴백 아님).
"""
from __future__ import annotations

import datetime as _dt
from typing import Dict, Optional, Union

from xml.etree.ElementTree import Element

# orders.py 의 파싱 helper 그대로 재사용(euc-kr XML 선언 제거 + 네임스페이스 제거 로직 중복 금지).
from shared.platforms.eleven11.orders import _localname, _parse

_PATH = "/rest/settlement/settlementList/{s}/{e}"
_MAX_WINDOW_DAYS = 31        # 문서: 조회기간 최대 31일(orders.py 의 7일과 다름)


def _fmt(d: _dt.datetime) -> str:
    """YYYYMMDD(일 단위) — settlementList 전용 포맷(orders._fmt 는 분단위라 별도)."""
    return d.strftime("%Y%m%d")


def _windows(since: _dt.datetime, until: _dt.datetime):
    """[since, until] 을 31일 이하 구간으로 분할(orders._windows 와 동일 패턴)."""
    cur = since
    step = _dt.timedelta(days=_MAX_WINDOW_DAYS)
    while cur < until:
        nxt = min(cur + step, until)
        yield cur, nxt
        cur = nxt


def parse_settlement(xml_text_or_elem: Optional[Union[str, Element]]) -> Dict[tuple, int]:
    """{(ordNo, ordPrdSeq): 정산금액} — parse_settlement_details 의 정산금액만 뽑은 얇은 래퍼."""
    return {k: v["정산금액"] for k, v in
            parse_settlement_details(xml_text_or_elem).items()}


def parse_settlement_details(xml_text_or_elem: Optional[Union[str, Element]]) -> Dict[tuple, dict]:
    """settlementList XML → {(ordNo, ordPrdSeq): {"정산금액": int, "옵션추가금": int?}}.

    ★키는 (주문번호, 주문순번) 라인 단위다. ordNo 로만 합산하면 다상품 주문(같은 ordNo,
    여러 ordPrdSeq)의 합계가 그 주문의 모든 행에 브로드캐스트돼 N배 계상된다(라이브 실 XML에
    다ordPrdSeq 주문 확인). 주문 행도 (오픈마켓주문번호, _send_ids.ord_prd_seq)로 매칭한다.
    같은 (ordNo,ordPrdSeq) 가 여러 번이면 합산. ordNo/stlAmt 없는 라인은 스킵(0 대체 금지).
    ★optAmt(옵션가) — 주문 목록 API 엔 이 필드가 없어(데이터코드지도 전수조사 2026-07-21)
      옵션추가금의 유일한 소스다. 없는 라인은 키 자체를 안 만든다(0 대체 금지).
    """
    if xml_text_or_elem is None:
        return {}
    root = _parse(xml_text_or_elem) if isinstance(xml_text_or_elem, str) else xml_text_or_elem
    if root is None:
        return {}

    result: Dict[tuple, dict] = {}
    # root.iter() = 전체 트리 재귀(orders.py:76 <order> 파싱과 동일 견고성). 평면 `for el in root`
    # 는 실 응답이 <Response><seStlDtlList><seStlDtl>… 처럼 래퍼로 한 겹 감싸면 래퍼를 라인으로
    # 잘못 읽어 조용히 {} 를 반환한다(라이브 스모크 전엔 실 구조 미확인). iter() 는 중첩·네임스페이스
    # 무관하게 실제 라인 요소(ordNo+stlAmt 보유)만 아래 가드로 골라내 그 실패모드를 제거.
    for el in root.iter():
        entry = {}
        for child in el:
            entry[_localname(child.tag)] = (child.text or "").strip()
        ordno = entry.get("ordNo")
        stl = entry.get("stlAmt")
        if not ordno or stl in (None, "", "null"):
            continue
        # ★정산금액 = selPrcAmt − deductAmt(판매/배송금액 − 공제). stlAmt 는 상품 라인엔 순액이지만
        #  배송비 라인엔 서비스이용료(deductAmt=dlvAddFee)를 안 뺀 총액이라 배송비만 과다계상된다
        #  (라이브 실검증: 배송비 stlAmt 4000 vs 판매자오피스 실정산 3788=4000−212). selPrcAmt/
        #  deductAmt 로 계산하면 상품(73200−8168=65032)·배송비(4000−212=3788) 모두 오차0.
        sp, dd = entry.get("selPrcAmt"), entry.get("deductAmt")
        try:
            if sp not in (None, "", "null") and dd not in (None, "", "null"):
                amt = round(float(sp)) - round(float(dd))
            else:
                amt = round(float(stl))
        except (TypeError, ValueError):
            continue
        key = (ordno, entry.get("ordPrdSeq") or "")
        ent = result.setdefault(key, {"정산금액": 0})
        ent["정산금액"] += amt
        opt = entry.get("optAmt")
        if opt not in (None, "", "null"):
            try:
                ent["옵션추가금"] = ent.get("옵션추가금", 0) + round(float(opt))
            except (TypeError, ValueError):
                pass                          # 값 형식 불명 → 옵션추가금 미기록(0 대체 금지)
    return result


def settlement_map(since: _dt.datetime, until: _dt.datetime, *, client) -> Dict[tuple, int]:
    """[since, until] 구간의 정산금액을 31일 윈도우로 분할 조회 후 (ordNo, ordPrdSeq)별 병합.

    반환 키 = (주문번호, 주문순번) 라인 단위(다상품 주문 over-count 방지 — parse_settlement 참조).
    client.request(XML 텍스트) → 파싱(orders.iter_orders 와 동일 계약). HTTP 오류는 client 가
    예외로 표면화 — 호출부(order_export.eleven11_order_rows)가 try/except 로 감싸 실패 시 기존
    stlPlnAmt/추정을 유지한다(추측 폴백 금지).
    """
    return {k: v["정산금액"] for k, v in
            settlement_detail_map(since, until, client=client).items()}


def settlement_detail_map(since: _dt.datetime, until: _dt.datetime, *,
                          client) -> Dict[tuple, dict]:
    """settlement_map 과 같되 {"정산금액", "옵션추가금"?} dict 를 돌려준다(옵션가 포함)."""
    merged: Dict[tuple, dict] = {}
    for w_from, w_to in _windows(since, until):
        path = _PATH.format(s=_fmt(w_from), e=_fmt(w_to))
        xml_text = client.request("GET", path)
        for key, ent in parse_settlement_details(xml_text).items():
            m = merged.setdefault(key, {"정산금액": 0})
            m["정산금액"] += ent["정산금액"]
            if "옵션추가금" in ent:
                m["옵션추가금"] = m.get("옵션추가금", 0) + ent["옵션추가금"]
    return merged
