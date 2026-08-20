# -*- coding: utf-8 -*-
"""쿠팡 로켓그로스(RG) 주문 조회 — 정산예정금액에 통째로 빠져 있던 매출.

🔴 왜 필요한가 (2026-08-06 사장님 지적 + 실측)
   로켓그로스 주문은 **별도 창구**로만 온다:
     GET /v2/providers/rg_open_api/apis/api/v1/vendors/{vendorId}/rg/orders
   그런데 우리 수집 코드는 이 창구를 **아예 부르지 않았다**(grep 0건). 그래서
   주문내역에도, 정산예정금액에도 로켓그로스 매출이 한 건도 없었다.

★ 이 API 는 **판매가·수량만** 준다 — 정산액(수수료 뗀 뒤)은 없다.
  정산이 마켓플레이스와 같이 revenue-history 에 잡히는지는 **라이브 실측**으로 확인한다
  (진단 창구 /orders/diag/coupang-rg). 확인 전까지 정산액을 지어내지 않는다.
★ 조회창 최대 30일(paidDateFrom~To, yyyymmdd) · 페이징 nextToken.
★ 응답 모양은 두 가지를 다 받는다 — 같은 쿠팡의 지급내역조회가 문서와 달리
  **배열 그대로** 왔던 전례(2026-08-06, 8계정 전멸)를 겪었다.
"""
from __future__ import annotations

import datetime as _dt
from typing import Optional

from shared.platforms import COUPANG
from shared.platforms.coupang.client import CoupangClient
from shared.platforms.coupang.orders import _vendor_id

_MAX_WINDOW_DAYS = 30      # 마켓 제약 — 넘기면 창을 쪼갠다


def _ymd(d: _dt.date) -> str:
    return d.strftime("%Y%m%d")


def _windows(since: str, until: str):
    """[since, until] → 30일 이하 창 목록. 넓게 물어 조용히 0건 되는 것을 막는다."""
    a = _dt.date.fromisoformat(since)
    b = _dt.date.fromisoformat(until)
    cur = a
    while cur <= b:
        nxt = min(cur + _dt.timedelta(days=_MAX_WINDOW_DAYS - 1), b)
        yield cur, nxt
        cur = nxt + _dt.timedelta(days=1)


def _paid_date(v) -> Optional[str]:
    """paidAt → 'YYYY-MM-DD'. ISO 문자열과 ms 타임스탬프를 모두 받는다(지도 원문 두 예시)."""
    s = str(v or "").strip()
    if not s:
        return None
    if s.isdigit() and len(s) >= 12:          # ms 타임스탬프
        try:
            return _dt.datetime.fromtimestamp(int(s) / 1000).strftime("%Y-%m-%d")
        except (ValueError, OSError):
            return None
    t = s[:10]
    try:
        _dt.date.fromisoformat(t)
    except ValueError:
        return None
    return t


def _to_int(v):
    try:
        return int(round(float(str(v).replace(",", ""))))
    except (TypeError, ValueError):
        return None


def fetch_rg_orders(since: str, until: str, *,
                    client: Optional[CoupangClient] = None) -> list:
    """로켓그로스 주문 → **옵션 단위** 행 목록.

    Returns [{주문번호, 옵션ID, 상품명, 수량, 단가, 상품금액, 주문일}] —
    값이 없는 항목(옵션ID·수량·단가 결손)은 담지 않는다(폴백·날조 금지).
    """
    client = client or CoupangClient()
    vendor_id = (getattr(client, "_cfg", {}) or {}).get("vendor_id") or _vendor_id()
    path = COUPANG["paths"]["rg_orders"].format(vendorId=vendor_id)
    out = []
    for w0, w1 in _windows(since, until):
        token = ""
        for _ in range(200):                  # 페이징 안전 상한
            query = (f"vendorId={vendor_id}&paidDateFrom={_ymd(w0)}"
                     f"&paidDateTo={_ymd(w1)}&nextToken={token}")
            resp = client.request(method="GET", path=path, query=query)
            rows = resp if isinstance(resp, list) else ((resp or {}).get("data") or [])
            for od in rows:
                if not isinstance(od, dict):
                    continue
                oid = str(od.get("orderId") or "").strip()
                pdate = _paid_date(od.get("paidAt"))
                if not oid:
                    continue
                for it in (od.get("orderItems") or []):
                    if not isinstance(it, dict):
                        continue
                    vid = str(it.get("vendorItemId") or "").strip()
                    qty = _to_int(it.get("salesQuantity"))
                    # 🔴 [2026-08-06 라이브 실측] 단가 필드는 문서의 salesPrice 가 아니라
                    #   **unitSalesPrice** 로 온다(세소 50건이 통째로 안 읽혔다).
                    #   마켓이 되돌릴 수도 있으니 두 이름을 다 받는다.
                    unit = _to_int(it.get("unitSalesPrice"))
                    if unit is None:
                        unit = _to_int(it.get("salesPrice"))
                    if not vid or qty is None or unit is None:
                        continue              # 조인 키·금액 없음 — 지어내지 않는다
                    out.append({
                        "주문번호": oid,
                        "옵션ID": vid,
                        "상품명": str(it.get("productName") or ""),
                        "수량": qty,
                        "단가": unit,
                        "상품금액": unit * qty,
                        "주문일": pdate or "",
                    })
            nxt = "" if isinstance(resp, list) else str((resp or {}).get("nextToken") or "")
            if not nxt:
                break
            token = nxt
    return out
