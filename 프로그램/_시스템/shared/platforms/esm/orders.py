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
# 조회기간 상한은 마켓마다 다르다(공식문서 etapi.gmarket.com/67).
#   G마켓 "31일 이하의 범위만 조회할 수 있습니다" / 옥션 180일 이하.
# 둘 다 31일로 쪼개면 옥션은 호출이 6배가 되고, 주문조회는 5초/1회(계정별) 제한이라
# 그대로 대기 시간이 된다(180일 조회 기준 150초 → 25초).
_MAX_WINDOW_DAYS = {"auction": 180, "gmarket": 31}
_MAX_WINDOW_DAYS_DEFAULT = 31   # 모르는 마켓은 좁은 쪽(상한 초과 호출은 마켓이 거부)
_PAGE_SIZE = 100


def _fmt(d: _dt.datetime) -> str:
    return d.strftime("%Y-%m-%d %H:%M")


def _windows(since: _dt.datetime, until: _dt.datetime, market: str = ""):
    """[since, until] 을 그 마켓의 조회기간 상한 이하 구간들로 분할(빈틈·겹침 없음)."""
    step = _dt.timedelta(days=_MAX_WINDOW_DAYS.get(market, _MAX_WINDOW_DAYS_DEFAULT))
    cur = since
    while cur < until:
        nxt = min(cur + step, until)
        yield cur, nxt
        cur = nxt


def fetch_by_order_no(market: str, order_no, *, client):
    """주문번호 1건 상세 조회(orderStatus=0). 없으면 None.

    왜 필요한가 — 클레임 조회(취소·반품·교환)는 **주문번호와 상태만** 준다.
    상품명·판매가·수량이 응답에 아예 없어서, 그것만으로는 주문내역 행을 만들 수 없다.
    다행히 공식문서가 길을 열어둔다: "주문조회는 5초당 1회 호출 가능합니다.
    **단, 주문번호로 조회하는 경우 제한 없습니다**"(etapi.gmarket.com/67).
    → 클레임에서 얻은 주문번호로 여기서 상세를 채운다(호출 제한 없음).
    """
    site_type = _SITE_TYPE.get(market)
    if site_type is None:
        raise ValueError(f"ESM 마켓 아님: {market} (auction|gmarket)")
    body = {"siteType": site_type, "orderStatus": 0, "orderNo": int(order_no)}
    resp = client.post((client._cfg.get("paths") or {}).get("orders"), body) or {}
    if resp.get("ResultCode") not in (0, "0", None, "success", "Success"):
        # 취소된 지 오래된 주문은 조회가 안 될 수 있다 — 실패는 조용히 삼키지 말고 None.
        return None
    data = resp.get("Data") or {}
    rows = (data.get("RequestOrders") or []) if isinstance(data, dict) else (data or [])
    return rows[0] if rows else None


def iter_orders(market: str, since: _dt.datetime, until: _dt.datetime, *,
                client, statuses=_DEFAULT_STATUSES, page_size: int = _PAGE_SIZE):
    """옥션/G마켓 주문(dict) 제너레이터. OrderNo 중복 제거."""
    site_type = _SITE_TYPE.get(market)
    if site_type is None:
        raise ValueError(f"ESM 마켓 아님: {market} (auction|gmarket)")

    seen = set()
    for w_from, w_to in _windows(since, until, market):
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
