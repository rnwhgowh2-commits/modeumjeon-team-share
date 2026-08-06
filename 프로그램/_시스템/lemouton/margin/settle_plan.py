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

# 예정일이 이만큼 넘게 지났으면 「이미 받았을 것(확인 불가)」로 본다(규칙표에서 조정).
#  🔴 왜 필요한가 — 지급 완료를 알려주는 마켓이 사실상 없다(2026-08-06 라이브 실측:
#    ESM 은 SettleExpectDate·RemitDate 가 전 기준일에서 null, 쿠팡도 settlementDate 미도래).
#    그래서 오래 지난 건을 「입금일 지남·미수령」으로 두면 총액이 몇 억씩 부풀어 자금계획이
#    통째로 못 쓰게 된다. 단정 대신 별도 부류로 빼고 그 사실을 화면에 적는다.
ASSUME_PAID_AFTER_DAYS = 30

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
    """한 라인의 부류 — **다섯 가지**만. 조건 순서가 상호배타를 보장한다.

        excluded / risk / paid / confirmed / unconfirmed

    🔴 [2026-08-06 교정] overdue·undated·assumed_paid 는 여기서 정하지 않는다 —
       **이벤트 단위**(resolve) 판정이다. 예전엔 여기서도 overdue 를 정하고
       aggregate 는 이벤트로 또 정해, KPI 는 5.5억인데 드릴다운은 0건인 어긋남이
       라이브에 나갔다. 판정은 resolve() 한 곳에서만 한다.
    """
    row = line["row"]
    if str(row.get("_kind") or "") == "change":
        return "excluded"
    st = str(row.get("주문상태") or "")
    if "취소완료" in st or str(row.get("_settle_source") or "") == "zero_cancel":
        return "excluded"
    if any(m in st for m in _RISK_MARKERS):
        return "risk"
    if _norm_date(row.get("_settle_paid_date")):
        return "paid"                       # 마켓이 「송금했다」고 알려준 것만
    if _CONFIRMED in st:
        return "confirmed"
    if any(m in st for m in _SHIPPED_MARKERS):
        return "unconfirmed"
    return "excluded"      # 신규주문·발송대기 등 — 송장 전 단계는 스펙상 대상 아님


def _anchor(line: dict) -> tuple:
    """추정 기준점 (날짜, 주문일폴백여부).

    🔴 [2026-08-06 라이브 실측] status_at(우리가 그 상태를 처음 본 시각)은 **옛 저장분에
       없다** — 라이브 6,084건이 그래서 날짜를 못 정했다. 주문일은 거의 항상 있으므로
       폴백으로 쓴다(정확도는 낮지만 '추정' 배지가 그대로 붙어 정직하다).
    """
    at = line.get("status_at")
    if at is not None:
        return (at.date() if isinstance(at, dt.datetime) else at), False
    od = _norm_date(str(line["row"].get("주문일") or "")[:10])
    if od:
        return dt.date.fromisoformat(od), True
    return None, False


def _estimated_payout(line: dict, rules: dict) -> str | None:
    """규칙 추정 지급예정일. 기준점이 아예 없으면 None(날조 금지 — 「미정」으로 표기)."""
    anchor, from_order = _anchor(line)
    if anchor is None:
        return None
    market = line["market"]
    m = (rules.get("markets") or {}).get(market) or {}
    fast = line.get("account") in ((rules.get("fast_accounts") or {}).get(market) or [])
    st = str(line["row"].get("주문상태") or "")
    if from_order:
        # 주문일부터의 **전 여정**(배송 → 자동확정 → 지급). 현재 상태는 쓰지 않는다 —
        # 주문일 기준이면 그 사이 단계를 이미 다 거쳤다고 보는 게 일관적이다.
        days = int(m.get("order_to_delivered_days") or 0)
        days += (int(m.get("fast_cycle_days") or 1) if fast
                 else int(m.get("auto_confirm_days") or 0) + int(m.get("cycle_days") or 0))
        return (anchor + dt.timedelta(days=days)).isoformat()
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


def resolve(line: dict, rules: dict, *, today: dt.date) -> dict:
    """행 하나의 **최종 판정** — 부류 + 지급 이벤트(각 이벤트에 bucket 표식).

    🔴 aggregate(집계)와 detail(드릴다운)이 **같은 이 함수**를 쓴다. 예전엔 둘이 따로
       판정해 「KPI 5.5억 · 드릴다운 0건」이 라이브에 나갔다(2026-08-06).

    bucket ∈ confirmed | unconfirmed | overdue | undated | assumed_paid
      · undated      = 날짜를 정할 근거가 없음(실값도 기준점도 없음) — **기한 경과 아님**
      · assumed_paid = 예정일이 한참(규칙표 assume_paid_after_days) 지남 → 이미 받았다고
        본다. 지급 완료를 알려주는 마켓이 사실상 없어(ESM·쿠팡 날짜 null 실측) 「안 받았다」
        고 단정할 수 없기 때문이다. 총액에서 빼되 화면에 별도로 적는다(숨기지 않는다).
    """
    cat = classify(line, today=today)
    if cat in ("excluded", "risk", "paid"):
        return {"category": cat, "events": []}
    evs = payout_events(line, rules, today=today)
    limit = int(rules.get("assume_paid_after_days") or ASSUME_PAID_AFTER_DAYS)
    for ev in evs:
        if ev["date"] is None:
            ev["bucket"] = "undated"
            continue
        d = dt.date.fromisoformat(ev["date"])
        if d >= today:
            ev["bucket"] = cat
        elif (today - d).days > limit:
            ev["bucket"] = "assumed_paid"
        else:
            ev["bucket"] = "overdue"
    return {"category": cat, "events": evs}


def bucket_key(date_str: str, unit: str) -> str:
    d = dt.date.fromisoformat(date_str[:10])
    if unit == "week":
        return (d - dt.timedelta(days=d.weekday())).isoformat()   # 월요일 시작
    if unit == "month":
        return date_str[:7]
    return d.isoformat()


def aggregate_payout(lines: list, rules: dict, *, unit: str,
                     today: dt.date) -> dict:
    """지급예정일 축 집계 — 본표(미래 확정/미확정) + 별도 줄들.

    🔴 사라지는 돈 0원 원칙 — 어느 부류든 kpi·extras 로 항상 노출한다.
    total_uncollected = 미래예정 + 기한경과 + 날짜미정.
      · risk(반품·취소 진행)와 assumed_paid(이미 받았을 것)는 **합산 제외**하고 따로 적는다.
    """
    kpi = {"confirmed_future": 0, "unconfirmed_future": 0, "overdue": 0,
           "undated": 0, "assumed_paid": 0, "risk": 0, "paid": 0,
           "total_uncollected": 0}
    counts = {"real_dates": 0, "estimated_dates": 0, "undated": 0}
    buckets: dict = {}
    extras = {"overdue": {}, "undated": {}, "assumed_paid": {}, "risk": {}}

    def _acc(d, market, account, amt):
        mk = d.setdefault(market, {})
        mk[account] = mk.get(account, 0) + amt

    for ln in lines:
        r = resolve(ln, rules, today=today)
        cat = r["category"]
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
        for ev in r["events"]:
            if ev["date_source"] == "real":
                counts["real_dates"] += 1
            elif ev["date_source"] == "estimated":
                counts["estimated_dates"] += 1
            else:
                counts["undated"] += 1
            b_name = ev["bucket"]
            if b_name in ("overdue", "undated", "assumed_paid"):
                kpi[b_name] += ev["amount"]
                _acc(extras[b_name], market, account, ev["amount"])
                continue
            kpi[f"{b_name}_future"] += ev["amount"]
            b = buckets.setdefault(bucket_key(ev["date"], unit),
                                   {"markets": {}, "total": 0})
            slot = b["markets"].setdefault(market, {"confirmed": 0, "unconfirmed": 0,
                                                    "accounts": {}})
            slot[b_name] += ev["amount"]
            a = slot["accounts"].setdefault(account, {"confirmed": 0, "unconfirmed": 0})
            a[b_name] += ev["amount"]
            b["total"] += ev["amount"]
    kpi["total_uncollected"] = (kpi["confirmed_future"] + kpi["unconfirmed_future"]
                                + kpi["overdue"] + kpi["undated"])
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
