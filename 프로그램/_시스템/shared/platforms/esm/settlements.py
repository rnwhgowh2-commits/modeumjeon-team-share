# -*- coding: utf-8 -*-
"""ESM 2.0(옥션·G마켓) 판매대금 정산조회 — getsettleorder.

근거(공개문서 etapi.gmarket.com/41, 2026-07-07 실측):
  POST /account/v1/settle/getsettleorder
  요청: SiteType(A/G)·SrchType(D1~D10 기준일)·SrchStartDate/SrchEndDate("YYYY-MM-DD")
        ·ContrNo(선택)·PageNo·PageRowCnt
  응답: {ResultCode, TotalCount, Data:[{ContrNo, SettlementPrice(정산액), SellOrderPrice(판매액),
        TotCommission(수수료), RemitDate, Kind(1:원거래 2:환불·부호반전)}]}

주문(OrderNo) ↔ 정산(ContrNo) 조인용 맵을 만든다. 환불(Kind=2)은 응답이 이미 부호 반전이라
그대로 합산. 미정산 주문은 맵에 없음 → 정산예정금액 공란(폴백 금지, CLAUDE.md).
"""
from __future__ import annotations

import datetime as _dt

_SITE = {"auction": "A", "gmarket": "G"}
_MAX_WINDOW_DAYS = 31
_PAGE_ROWS = 500


def _fmt(d: _dt.datetime) -> str:
    return d.strftime("%Y-%m-%d")


def _windows(since: _dt.datetime, until: _dt.datetime):
    cur = since
    step = _dt.timedelta(days=_MAX_WINDOW_DAYS)
    while cur < until:
        nxt = min(cur + step, until)
        yield cur, nxt
        cur = nxt


def settle_price_map(market: str, since: _dt.datetime, until: _dt.datetime, *,
                     client, srch_type: str = "D1", page_rows: int = _PAGE_ROWS) -> dict:
    """{str(ContrNo): 정산액 합계(int)} — 주문번호별 SettlementPrice 합.

    srch_type = 정산 조회 기준일(D1~D10). 주문일 기준 조회와 완전 일치 안 할 수 있어(정산 시차)
    라이브에서 튜닝. 값 파싱 실패 행은 건너뜀(0 대체 금지).
    """
    site = _SITE.get(market)
    if site is None:
        raise ValueError(f"ESM 마켓 아님: {market}")
    out: dict = {}
    for w_from, w_to in _windows(since, until):
        page = 1
        while True:
            body = {
                "SiteType": site,
                "SrchType": srch_type,
                "SrchStartDate": _fmt(w_from),
                "SrchEndDate": _fmt(w_to),
                "PageNo": page,
                "PageRowCnt": page_rows,
            }
            resp = client.request_settlement(body) or {}
            if resp.get("ResultCode") not in (0, None):
                raise RuntimeError(f"ESM 정산조회 실패 ResultCode={resp.get('ResultCode')} "
                                   f"{resp.get('Message') or ''}")
            data = resp.get("Data") or []
            if not data:
                break
            for row in data:
                cn = row.get("ContrNo")
                if cn is None:
                    continue
                try:
                    amt = int(round(float(row.get("SettlementPrice"))))
                except (TypeError, ValueError):
                    continue                      # 값 없음 → 스킵(0 대체 금지)
                key = str(cn)
                out[key] = out.get(key, 0) + amt
            total = resp.get("TotalCount") or 0
            if page * page_rows >= total or len(data) < page_rows:
                break
            page += 1
    return out
