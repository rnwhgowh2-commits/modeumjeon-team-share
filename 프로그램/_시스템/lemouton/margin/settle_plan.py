"""정산예정금액 탭 엔진 — 분류·지급이벤트·기간 버킷 집계 (순수 함수, DB 없음).

스펙: docs/superpowers/specs/2026-08-06-settle-plan-tab-design.md

■ 부류 상호배타 (스펙 §2 — 중복 원천 차단):
    excluded  = 클레임 행(_kind=change)·취소완료(zero_cancel)·송장 전 단계
    risk      = 반품·교환·취소 **진행 중** (예정액에서 빼고 별도 줄 — 돈 부풀리기 방지)
    paid      = 수령 확인(_settle_paid_date 있음 — ESM RemitDate·스스 settleCompleteDate)
    overdue   = 지급예정일 < 오늘인데 수령 확인 불가 (**조용히 빼지 않는다** — 별도 줄 상시)
    confirmed / unconfirmed = 미래 예정분 (본표). 상태 문자열로만 갈려 한 행은 한 곳에만.

■ 금액 = margin.sell_source._settlement_for(row) 그대로 (재계산 금지 — 마진계산기와
  같은 숫자를 보게 하는 단일 원천 규약을 이 탭도 따른다. 2026-07-23 「따로 논다」 사고 참조).

■ 지급예정일 = 실값(row.정산예정일 — 스윕이 저장) → 규칙 추정(settle_plan_rules) 순.
  추정 기준점(anchor)은 마켓 응답에 없는 값이라 **우리 관측 시각(status_at)** 근사 —
  그래서 항상 date_source='estimated' 배지가 붙는다(정직 표기).
  쿠팡 분할지급: 실값 두 날짜(settlementDate+finalSettlementDate)가 오면 실값으로,
  없으면 규칙(split_ratio·split_rest_days)으로 두 조각. 합=원금(반올림 유실 금지).
"""
from __future__ import annotations

import datetime as dt

from lemouton.margin.sell_source import _settlement_for

# 반품·교환·취소 "진행 중" — 완료(취소완료=excluded·반품완료 등 클레임 경로)와 구분.
_RISK_MARKERS = ("반품요청", "반품진행", "반품접수", "교환요청", "교환진행",
                 "취소요청", "취소접수", "취소철회대기", "미수취신고")
_CONFIRMED = "구매확정"
# 송장 입력 후 단계(스펙 2)번 부류의 근거 상태). 구매결정=ESM 표기.
_SHIPPED_MARKERS = ("배송중", "배송완료", "발송완료", "수취완료", "구매결정")


def _norm_date(s) -> str | None:
    """'2026-08-06'·'…T00:00:00'·'2026/08/06'·'20260806' → 'YYYY-MM-DD'.

    2000-01-01 이전은 센티널 → None. ESM 은 보류 사유를 1991-01-01 류 가짜 날짜로
    표현하고(SettleExceptName), 빈 값을 0001-01-01 로 내린다 — 날짜가 아니다.
    """
    t = str(s or "").strip().replace("/", "-")
    if not t:
        return None
    t = t[:10]
    if len(t) == 8 and t.isdigit():
        t = f"{t[:4]}-{t[4:6]}-{t[6:8]}"
    try:
        d = dt.date.fromisoformat(t)
    except ValueError:
        return None
    return t if d.year >= 2000 else None


def classify(line: dict, *, today: dt.date) -> str:
    """한 라인의 부류. 조건 순서가 상호배타를 보장한다(위에서 먼저 걸리면 끝)."""
    row = line["row"]
    if str(row.get("_kind") or "") == "change":
        return "excluded"
    st = str(row.get("주문상태") or "")
    if "취소완료" in st or str(row.get("_settle_source") or "") == "zero_cancel":
        return "excluded"
    if any(m in st for m in _RISK_MARKERS):
        return "risk"
    if _norm_date(row.get("_settle_paid_date")):
        return "paid"
    pdate = _norm_date(row.get("정산예정일"))
    if pdate and dt.date.fromisoformat(pdate) < today:
        # 잔여분(쿠팡 30%)이 미래에 남아 있으면 아직 「미래 예정」 — 조각별 과거/미래
        # 판정은 aggregate_payout 이 이벤트 단위로 다시 한다(1차분만 overdue 로).
        fdate = _norm_date(row.get("_settle_final_date"))
        if not (fdate and dt.date.fromisoformat(fdate) >= today):
            return "overdue"
    if _CONFIRMED in st:
        return "confirmed"
    if any(m in st for m in _SHIPPED_MARKERS):
        return "unconfirmed"
    return "excluded"      # 신규주문·발송대기 등 — 송장 전 단계는 스펙상 대상 아님


def _estimated_payout(line: dict, rules: dict) -> str | None:
    """규칙 추정 지급예정일. anchor=관측시각(status_at) 근사 — 없으면 None(날조 금지)."""
    at = line.get("status_at")
    if at is None:
        return None
    anchor = at.date() if isinstance(at, dt.datetime) else at
    market = line["market"]
    m = (rules.get("markets") or {}).get(market) or {}
    fast = line.get("account") in ((rules.get("fast_accounts") or {}).get(market) or [])
    st = str(line["row"].get("주문상태") or "")
    if fast:
        # 빠른정산 = 발송(집화) 기준 선지급. 관측시각 ≈ 발송 이후이므로 anchor 그대로.
        return (anchor + dt.timedelta(days=int(m.get("fast_cycle_days") or 1))).isoformat()
    days = int(m.get("cycle_days") or 0)
    if _CONFIRMED not in st:
        days += int(m.get("auto_confirm_days") or 0)
        if "배송중" in st or "발송완료" in st:
            days += int(m.get("transit_days") or 0)
    return (anchor + dt.timedelta(days=days)).isoformat()


def payout_events(line: dict, rules: dict, *, today: dt.date) -> list[dict]:
    """한 라인의 지급 이벤트(0~2개). 쿠팡 분할지급은 두 조각, 합=원금(유실 금지)."""
    row = line["row"]
    amount, _src = _settlement_for(row)
    if not amount:
        return []
    market = line["market"]
    m = (rules.get("markets") or {}).get(market) or {}
    real = _norm_date(row.get("정산예정일"))
    final = _norm_date(row.get("_settle_final_date"))
    if real:
        if final and final != real:
            first = round(amount * float(m.get("split_ratio") or 1.0))
            return [{"date": real, "amount": first, "date_source": "real"},
                    {"date": final, "amount": amount - first, "date_source": "real"}]
        return [{"date": real, "amount": amount, "date_source": "real"}]
    est = _estimated_payout(line, rules)
    if est is None:
        return [{"date": None, "amount": amount, "date_source": None}]
    ratio = float(m.get("split_ratio") or 1.0)
    if ratio < 1.0:
        first = round(amount * ratio)
        rest_d = (dt.date.fromisoformat(est)
                  + dt.timedelta(days=int(m.get("split_rest_days") or 0))).isoformat()
        return [{"date": est, "amount": first, "date_source": "estimated"},
                {"date": rest_d, "amount": amount - first, "date_source": "estimated"}]
    return [{"date": est, "amount": amount, "date_source": "estimated"}]


def bucket_key(date_str: str, unit: str) -> str:
    d = dt.date.fromisoformat(date_str[:10])
    if unit == "week":
        return (d - dt.timedelta(days=d.weekday())).isoformat()   # 월요일 시작
    if unit == "month":
        return date_str[:7]
    return d.isoformat()


def aggregate_payout(lines: list, rules: dict, *, unit: str,
                     today: dt.date) -> dict:
    """지급예정일 축 집계 — 본표(미래 확정/미확정) + 별도 줄(overdue·risk·paid).

    🔴 기한경과·위험을 조용히 빼지 않는다(스펙 재검토 구멍①·②) — kpi·extras 로 항상 노출.
    total_uncollected = 미래예정 + 기한경과 (위험은 정산 안 될 가능성이 커 합산 제외·별도).
    """
    kpi = {"confirmed_future": 0, "unconfirmed_future": 0, "overdue": 0,
           "risk": 0, "paid": 0, "total_uncollected": 0}
    counts = {"real_dates": 0, "estimated_dates": 0, "undated": 0}
    buckets: dict = {}
    extras = {"overdue": {}, "risk": {}}     # {market: {account: amt}}

    def _acc(d, market, account, amt):
        mk = d.setdefault(market, {})
        mk[account] = mk.get(account, 0) + amt

    for ln in lines:
        cat = classify(ln, today=today)
        if cat == "excluded":
            continue
        amount, _src = _settlement_for(ln["row"])
        if not amount:
            continue
        market, account = ln["market"], ln.get("account") or ""
        if cat == "paid":
            kpi["paid"] += amount
            continue
        if cat == "risk":
            kpi["risk"] += amount
            _acc(extras["risk"], market, account, amount)
            continue
        if cat == "overdue":
            kpi["overdue"] += amount
            _acc(extras["overdue"], market, account, amount)
            continue
        for ev in payout_events(ln, rules, today=today):
            if ev["date_source"] == "real":
                counts["real_dates"] += 1
            elif ev["date_source"] == "estimated":
                counts["estimated_dates"] += 1
            else:
                counts["undated"] += 1
            # 이벤트 단위 과거/미래 — 쿠팡 1차분(70%)만 지났으면 그 조각만 기한경과.
            if ev["date"] is None or dt.date.fromisoformat(ev["date"]) < today:
                kpi["overdue"] += ev["amount"]
                _acc(extras["overdue"], market, account, ev["amount"])
                continue
            kpi[f"{cat}_future"] += ev["amount"]
            b = buckets.setdefault(bucket_key(ev["date"], unit),
                                   {"markets": {}, "total": 0})
            slot = b["markets"].setdefault(market, {"confirmed": 0, "unconfirmed": 0,
                                                    "accounts": {}})
            slot[cat] += ev["amount"]
            a = slot["accounts"].setdefault(account, {"confirmed": 0, "unconfirmed": 0})
            a[cat] += ev["amount"]
            b["total"] += ev["amount"]
    kpi["total_uncollected"] = (kpi["confirmed_future"] + kpi["unconfirmed_future"]
                                + kpi["overdue"])
    return {"kpi": kpi, "meta": counts, "extras": extras,
            "buckets": [{"key": k, **v} for k, v in sorted(buckets.items())]}


def aggregate_by_order_date(lines: list, *, unit: str = "day",
                            d_from: str = "", d_to: str = "") -> dict:
    """주문일 축 — 클레임(취소완료·반품완료·클레임 행·위험 진행분) 제외
    매출액 + 정산예정금 합계.

    매출액 = 실결제금액, 없으면 상품금액+배송비 대체 — 대체 건수를 meta 로 표기한다
    (조용한 대체 금지, 스펙 재검토 구멍⑤).
    """
    from lemouton.markets.order_export import _to_int
    buckets: dict = {}
    substituted = 0
    for ln in lines:
        row = ln["row"]
        if str(row.get("_kind") or "") == "change":
            continue
        st = str(row.get("주문상태") or "")
        if "취소완료" in st or "반품완료" in st or any(m in st for m in _RISK_MARKERS):
            continue
        od = str(row.get("주문일") or "")[:10]
        if not od or (d_from and od < d_from) or (d_to and od > d_to):
            continue
        rev = _to_int(row.get("실결제금액"))
        if not rev:
            p = _to_int(row.get("상품금액"), 0) or 0
            s = _to_int(row.get("배송비"), 0) or 0
            rev = p + s
            if rev:
                substituted += 1
        settle, _src = _settlement_for(row)
        b = buckets.setdefault(bucket_key(od, unit),
                               {"revenue": 0, "settle": 0, "markets": {}})
        b["revenue"] += rev or 0
        b["settle"] += settle or 0
        mk = b["markets"].setdefault(ln["market"], {"revenue": 0, "settle": 0})
        mk["revenue"] += rev or 0
        mk["settle"] += settle or 0
    return {"meta": {"revenue_substituted": substituted},
            "buckets": [{"key": k, **v} for k, v in sorted(buckets.items())]}
