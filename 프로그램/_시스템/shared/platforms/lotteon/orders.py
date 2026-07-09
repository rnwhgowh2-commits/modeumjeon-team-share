# -*- coding: utf-8 -*-
"""롯데온 출고/회수지시(주문정보) 조회 — 발송관리용 주문 수집.

공식 스펙(API 센터 실측 2026-07-07, apiNo=209):
  POST /v1/openapi/delivery/v1/SellerDeliveryOrdersSearch
  body: srchStrtDt/srchEndDt(yyyymmddhhmmss·출고회수지시 생성일시) 또는 odNo,
        odPrgsStepCd(11:출고지시/23:회수지시), odTypCd(10주문/30교환/40반품/50AS),
        ifCplYN(연동완료여부·빈값=신규주문), trGrpCd/trNo(Bearer 인증과 함께).
  ⚠️ 조회기간 1일 초과 불가(returnCode 2003) → 하루씩 윈도우.
  응답: data.deliveryOrderList[] (spdNm·sitmNm·odQty·slPrc·dvpCustNm·dvpStnmZipAddr·
        dvpMphnNo·dvMsg·odrNm·mphnNo·actualAmt·odCmptDttm ...).

인증·rate limit·재시도 는 LotteonClient(Bearer openapikey). 이 모듈은 body/파싱만.
스마트스토어 orders.py 와 동형(단일 조회 → 자동 윈도우 iter).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterator, Optional

from shared.platforms import LOTTEON as _CFG
from shared.platforms.lotteon.client import LotteonClient

_PATH = "/v1/openapi/delivery/v1/SellerDeliveryOrdersSearch"
_FMT = "%Y%m%d%H%M%S"   # yyyymmddhhmmss


def fetch_delivery_orders(srch_start: str, srch_end: str,
                          if_cpl_yn: str = "",
                          od_prgs_step_cd: Optional[str] = None,
                          od_typ_cd: Optional[str] = None,
                          tr_no: Optional[str] = None,
                          tr_grp_cd: Optional[str] = None,
                          lrtr_no: Optional[str] = None,
                          client: Optional[LotteonClient] = None) -> dict:
    """출고/회수지시 1구간(≤1일) 조회 (raw 응답).

    srch_start/srch_end = yyyymmddhhmmss. ifCplYN 빈값 = 미연동 신규주문.
    """
    client = client or LotteonClient()
    body = {
        "trGrpCd": tr_grp_cd if tr_grp_cd is not None else _CFG.get("tr_grp_cd", "SR"),
        "trNo": tr_no if tr_no is not None else _CFG.get("tr_no", ""),
        "lrtrNo": lrtr_no if lrtr_no is not None else _CFG.get("lrtr_no", ""),
        "srchStrtDt": srch_start,
        "srchEndDt": srch_end,
        "ifCplYN": if_cpl_yn,
    }
    if od_prgs_step_cd:
        body["odPrgsStepCd"] = od_prgs_step_cd
    if od_typ_cd:
        body["odTypCd"] = od_typ_cd
    return client.request(method="POST", path=_PATH, body=body)


def _orders_of(resp: dict) -> list:
    data = resp.get("data") if isinstance(resp, dict) else None
    if isinstance(data, dict):
        return data.get("deliveryOrderList") or []
    return []


def iter_delivery_orders(since: datetime, until: datetime,
                         if_cpl_yn: str = "",
                         client: Optional[LotteonClient] = None,
                         **filters) -> Iterator[dict]:
    """[since, until] 사이 출고/회수지시 주문을 하루 단위로 순회하며 yield.

    롯데온 제약(조회기간 1일 초과 불가)에 맞춰 24h 윈도우로 끊는다.
    """
    client = client or LotteonClient()
    win_start = since
    while win_start < until:
        win_end = min(win_start + timedelta(days=1), until)
        resp = fetch_delivery_orders(
            srch_start=win_start.strftime(_FMT),
            # 종료는 구간 끝 직전초(1일 초과 방지)
            srch_end=(win_end - timedelta(seconds=1)).strftime(_FMT),
            if_cpl_yn=if_cpl_yn, client=client, **filters)
        for od in _orders_of(resp):
            yield od
        win_start = win_end


# ── 주문진행단계 조회(apiNo=140 SellerDeliveryProgressStateSearch) ──
#  209(출고/회수지시)는 주문 '수집'용이라 단계가 11(출고지시)에 고정. 140은 '수집 완료된
#  주문의 실시간 주문진행단계'(odPrgsStepCd 11~27) 조회용(공식문서 권장 용법). 209로 모은
#  주문의 현재 단계(발송완료/배송완료/수취완료/취소완료/반품완료 등)를 채우는 데 쓴다.
#  검색일 기준 = 배송지시생성일시(209와 동일) → 같은 [since,until] 창으로 조인. 1일 초과 불가.
_PATH_PROGRESS = "/v1/openapi/delivery/v1/SellerDeliveryProgressStateSearch"


def fetch_progress_states(srch_start: str, srch_end: str,
                          od_no: Optional[str] = None,
                          tr_no: Optional[str] = None,
                          tr_grp_cd: Optional[str] = None,
                          lrtr_no: Optional[str] = None,
                          client: Optional[LotteonClient] = None) -> dict:
    """주문진행단계 1구간(≤1일) 조회 (raw 응답).

    srch_start/srch_end = yyyymmddhhmmss(배송지시생성일시). odNo 지정 시 단건 조회.
    """
    client = client or LotteonClient()
    body = {
        "trGrpCd": tr_grp_cd if tr_grp_cd is not None else _CFG.get("tr_grp_cd", "SR"),
        "trNo": tr_no if tr_no is not None else _CFG.get("tr_no", ""),
        "lrtrNo": lrtr_no if lrtr_no is not None else _CFG.get("lrtr_no", ""),
        "srchStrtDt": srch_start,
        "srchEndDt": srch_end,
        "odNo": od_no or "",
    }
    return client.request(method="POST", path=_PATH_PROGRESS, body=body)


def _progress_of(resp: dict) -> list:
    data = resp.get("data") if isinstance(resp, dict) else None
    if isinstance(data, dict):
        return data.get("deliveryProgressStateList") or []
    return []


def iter_progress_states(since: datetime, until: datetime,
                         client: Optional[LotteonClient] = None,
                         **filters) -> Iterator[dict]:
    """[since, until] 배송지시생성일시 기준 주문진행단계를 하루 단위로 순회하며 yield.

    각 항목: odNo·odSeq·procSeq·odPrgsStepCd(11~27)·dvTrcStatDttm(배송상태발생일시) 등.
    """
    client = client or LotteonClient()
    win_start = since
    while win_start < until:
        win_end = min(win_start + timedelta(days=1), until)
        resp = fetch_progress_states(
            srch_start=win_start.strftime(_FMT),
            srch_end=(win_end - timedelta(seconds=1)).strftime(_FMT),
            client=client, **filters)
        for it in _progress_of(resp):
            yield it
        win_start = win_end
