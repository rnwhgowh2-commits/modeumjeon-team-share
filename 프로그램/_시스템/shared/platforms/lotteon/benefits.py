# -*- coding: utf-8 -*-
"""롯데온 셀러 주문혜택 조회(245) — 주문별 셀러/롯데부담 할인.

GET /v1/openapi/order/v1/getSROrderList (srchStrtDttm/srchEndDttm yyyymmddHHMMSS, 1일 제한).
응답 data.orderItems[].fvrList[]: odFvrDvsCd(DC 할인/GF·SV 증정·적립)·prEntpShrAmt(업체=셀러 분담)·
  prSfcoShrAmt(자사=롯데 분담). 정산엔 '할인(DC)'만 필요.
  셀러부담=Σ prEntpShrAmt(DC), 롯데부담=Σ prSfcoShrAmt(DC). 폴백·추측 없음.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from shared.platforms.lotteon.client import LotteonClient

_PATH = "/v1/openapi/order/v1/getSROrderList"


def _num(v) -> int:
    try:
        return int(float(v or 0))
    except (TypeError, ValueError):
        return 0


def parse_benefit_map(resp: dict) -> dict:
    """응답 → {odNo: {seller_discount, platform_discount}}. DC(할인)만 합산."""
    out: dict = {}
    data = (resp or {}).get("data") or {}
    for od in (data.get("orderItems") or []):
        od_no = str(od.get("odNo") or "")
        if not od_no:
            continue
        cur = out.setdefault(od_no, {"seller_discount": 0, "platform_discount": 0})
        for f in (od.get("fvrList") or []):
            if f.get("odFvrDvsCd") != "DC":
                continue
            cur["seller_discount"] += _num(f.get("prEntpShrAmt"))
            cur["platform_discount"] += _num(f.get("prSfcoShrAmt"))
    return out


def benefit_map(since: datetime, until: datetime, *, client: Optional[LotteonClient] = None) -> dict:
    """[since, until] 주문의 할인맵 {odNo:{seller_discount, platform_discount}}. 1일 윈도우 분할."""
    client = client or LotteonClient()
    out: dict = {}
    win = since
    while win < until:
        end = min(win + timedelta(days=1), until)
        body = {"srchStrtDttm": win.strftime("%Y%m%d%H%M%S"),
                "srchEndDttm": (end - timedelta(seconds=1)).strftime("%Y%m%d%H%M%S")}
        resp = client.request(method="GET", path=_PATH, body=body)
        for k, v in parse_benefit_map(resp).items():
            cur = out.setdefault(k, {"seller_discount": 0, "platform_discount": 0})
            cur["seller_discount"] += v["seller_discount"]
            cur["platform_discount"] += v["platform_discount"]
        win = end
    return out
