# -*- coding: utf-8 -*-
"""ESM 2.0(옥션·G마켓) 주문조회 — RequestOrders.

근거(공개문서 etapi.gmarket.com/67, 2026-07-07 실측):
  POST /shipping/v1/Order/RequestOrders
  요청: siteType(1:옥션,2:G마켓)·orderStatus(1:결제완료 2:배송준비중 3:배송중 4:배송완료
        5:구매결정완료)·requestDateType(1:주문일)·requestDateFrom/To("YYYY-MM-DD hh:mm",31일 제한)
        ·pageIndex·pageSize
  응답: {ResultCode:0, Message, Data:{TotalCount, RequestOrders:[...]}}

기간이 31일 초과면 31일 윈도우로 분할, orderStatus 별로 순회(발송관리=미발송+진행 전체),
OrderNo 로 중복 제거. 5초/1회 rate limit 은 client 가 담당.
"""
from __future__ import annotations

import datetime as _dt

_SITE_TYPE = {"auction": 1, "gmarket": 2}
# 최근 주문 전체(주문상태 열 의미 유지) — 결제완료~구매결정완료.
_DEFAULT_STATUSES = (1, 2, 3, 4, 5)
_MAX_WINDOW_DAYS = 31
_PAGE_SIZE = 100


def _fmt(d: _dt.datetime) -> str:
    return d.strftime("%Y-%m-%d %H:%M")


def _windows(since: _dt.datetime, until: _dt.datetime):
    """[since, until] 을 ≤31일 구간들로 분할."""
    cur = since
    step = _dt.timedelta(days=_MAX_WINDOW_DAYS)
    while cur < until:
        nxt = min(cur + step, until)
        yield cur, nxt
        cur = nxt


def iter_orders(market: str, since: _dt.datetime, until: _dt.datetime, *,
                client, statuses=_DEFAULT_STATUSES, page_size: int = _PAGE_SIZE):
    """옥션/G마켓 주문(dict) 제너레이터. OrderNo 중복 제거."""
    site_type = _SITE_TYPE.get(market)
    if site_type is None:
        raise ValueError(f"ESM 마켓 아님: {market} (auction|gmarket)")

    seen = set()
    for w_from, w_to in _windows(since, until):
        for status in statuses:
            page = 1
            while True:
                body = {
                    "siteType": site_type,
                    "orderStatus": int(status),
                    "requestDateType": 1,               # 주문일 기준
                    "requestDateFrom": _fmt(w_from),
                    "requestDateTo": _fmt(w_to),
                    "pageIndex": page,
                    "pageSize": page_size,
                }
                resp = client.request_orders(body) or {}
                if resp.get("ResultCode") not in (0, None):
                    # 오류코드는 사유와 함께 전파(추측·무시 금지)
                    raise RuntimeError(f"ESM 주문조회 실패 ResultCode={resp.get('ResultCode')} "
                                       f"{resp.get('Message') or ''}")
                data = resp.get("Data") or {}
                orders = data.get("RequestOrders") or []
                if not orders:
                    break
                for od in orders:
                    key = od.get("OrderNo")
                    if key in seen:
                        continue
                    seen.add(key)
                    yield od
                total = data.get("TotalCount") or 0
                if page * page_size >= total or len(orders) < page_size:
                    break
                page += 1
