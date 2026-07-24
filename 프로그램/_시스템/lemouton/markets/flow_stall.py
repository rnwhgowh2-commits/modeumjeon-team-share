# -*- coding: utf-8 -*-
"""배송흐름 감시 — 송장을 넣었는데 배송이 안 움직이는 주문.

## 왜 필요한가

사장님 정의(2026-07-24): **송장번호를 넣은 주문 중 24시간이 지나도 배송 흐름에
변화가 없는 건.** 택배사가 접수를 안 했거나, 송장이 잘못 들어갔거나, 마켓에
전송이 실패한 경우다. 그대로 두면 고객이 먼저 알아챈다.

## 기존 것과 무엇이 다른가

`lemouton/delivery/service.find_flow_stalled` 는 같은 판정을 하지만 **더망고
엑셀로 올린 주문(MangoOrder)** 만 본다. 엑셀을 안 올리면 아무것도 안 보인다.
이 모듈은 **적재분(market_order_lines)** 을 보므로 엑셀과 무관하게 늘 돌아간다.

## 정직성 규칙

- **기준시각이 없으면 판정하지 않는다.** '언제부터 멈췄는지' 모르는데 멈췄다고
  하면 거짓 경보다. 대신 그 건수를 `unknown` 으로 **함께 돌려준다** — 화면이
  숨기지 않고 "판정 못 한 N건"으로 보여줄 수 있게(조용한 실패 금지).
- 기준시각 = **마켓이 준 발송처리일**만 쓴다. 우리가 처음 본 시각(원장
  captured_at)은 조회할 때마다 갱신돼 '처음'이 아니다 — 쓰면 경과가 늘 0에
  가까워져 아무것도 안 잡힌다.
- 발송처리일을 주는 마켓 = 스마트스토어(sendDate) · 롯데온(dvTrcStatDttm) ·
  11번가(sndEndDt/dlvEndDt). 쿠팡·옥션·G마켓은 안 준다 → `unknown` 으로 샌다.
"""
from __future__ import annotations

import datetime as _dt

from lemouton.markets.invoice_ledger import _ONCE_SHIPPED_STATES
from lemouton.markets.order_export import _SHIPPED_STATES, is_invoice_no

KST = _dt.timezone(_dt.timedelta(hours=9))

#  감시 대상에서 빼는 상태 — 「아직 고객에게 가는 중」이 아닌 것들.
#   · _SHIPPED_STATES : 배송중·배송완료·구매확정 … 이미 흐름이 시작됨
#   · _ONCE_SHIPPED_STATES : 반품·교환·취소·회수 … 배송이 아니라 되돌아오는 중이거나 끝남
#  ★ 클레임을 안 빼면 「반품완료」가 며칠째 배송이 안 움직인다고 잡힌다
#    (2026-07-24 라이브 실측: 15건 전부 반품완료 12 + 회수지시 3 = 전부 거짓 경보).
_NOT_WATCHED = _SHIPPED_STATES | _ONCE_SHIPPED_STATES

# 화면 표기값 — 번호가 아니다.
_SENTINELS = {"", "확인 불가", "송장미입력"}


def _real_invoice(v) -> str:
    s = str(v or "").strip()
    return s if s and s not in _SENTINELS and is_invoice_no(s) else ""


def _parse_dt(v):
    """마켓이 준 발송처리일 → datetime(KST). 못 읽으면 None(지어내지 않는다)."""
    s = str(v or "").strip()
    if not s:
        return None
    s = s.replace("T", " ").replace("Z", "")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
                "%Y%m%d%H%M%S", "%Y%m%d%H%M", "%Y%m%d"):
        try:
            d = _dt.datetime.strptime(s[:len(fmt) + 2].strip(), fmt)
            return d.replace(tzinfo=KST) if d.tzinfo is None else d
        except ValueError:
            continue
    try:                                        # '2026-07-20 13:42:47+09:00' 같은 꼴
        d = _dt.datetime.fromisoformat(s)
        return d.replace(tzinfo=KST) if d.tzinfo is None else d
    except ValueError:
        return None


def judge(row: dict, now: _dt.datetime, hours: int = 24) -> tuple[str, float]:
    """한 행 판정 → (판정, 경과시간).

    판정: 'stalled'(멈춤) · 'moving'(흐름 시작됨·되돌아오는 중·끝남)
          · 'no_invoice'(송장 없음) · 'unknown'(기준시각 없음 — 판정 못 함)
    """
    if not _real_invoice(row.get("송장입력")):
        return "no_invoice", 0.0
    if str(row.get("주문상태") or "").strip() in _NOT_WATCHED:
        return "moving", 0.0                    # 이미 흐름 시작·클레임·종료 → 감시 대상 아님
    base = _parse_dt(row.get("발송처리일"))
    if base is None:
        return "unknown", 0.0
    elapsed = (now - base).total_seconds() / 3600.0
    return ("stalled" if elapsed > hours else "moving"), elapsed


def find_stalled(*, hours: int = 24, days: int = 21, now=None,
                 session=None) -> dict:
    """저장분에서 배송흐름이 멈춘 주문을 찾는다 — 엑셀 없이.

    Returns {hours, days, count, unknown, rows:[{...행..., _stall_hours}]}
    """
    from lemouton.markets import order_store as _store

    now = now or _dt.datetime.now(KST)
    since = (now - _dt.timedelta(days=days)).strftime("%Y-%m-%d")
    until = now.strftime("%Y-%m-%d")
    rows = _store.load(since=since, until=until, include_claims=False,
                       session=session)
    out, unknown = [], 0
    for r in rows:
        verdict, elapsed = judge(r, now, hours)
        if verdict == "unknown":
            unknown += 1
        elif verdict == "stalled":
            d = dict(r)
            d["_stall_hours"] = round(elapsed, 1)
            out.append(d)
    out.sort(key=lambda x: -x["_stall_hours"])
    per: dict = {}
    for d in out:
        m = str(d.get("판매처") or "?")
        per[m] = per.get(m, 0) + 1
    return {"hours": hours, "days": days, "count": len(out),
            "unknown": unknown, "per_market": per, "rows": out}
