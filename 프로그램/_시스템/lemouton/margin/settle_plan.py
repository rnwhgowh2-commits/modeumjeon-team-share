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
# 구매확정을 뜻하는 말 — 🔴 옥션·G마켓은 「구매결정」이라 쓴다(2026-08-06 라이브에서
#  1건이 미확정으로 잘못 분류돼 발견). 사유 판정(overdue_reason)은 이미 둘 다 확정으로
#  보고 있었는데 classify 만 「구매확정」 하나만 봐서 **같은 프로그램 안에서 기준이 어긋났다**.
_CONFIRMED_WORDS = ("구매확정", "구매결정")
_CONFIRMED = "구매확정"      # 하위호환(기존 참조)
# 송장 입력 후·확정 전 단계 — 스펙 2)번 부류의 근거 상태.
_SHIPPED_MARKERS = ("배송중", "배송완료", "발송완료", "수취완료")


def _is_confirmed(status: str) -> bool:
    return any(w in status for w in _CONFIRMED_WORDS)


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
    if _is_confirmed(st):
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
    if not _is_confirmed(st):
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


# 「입금했다」를 실제로 알려주는 마켓 — 2026-08-06 실측으로 확정.
#  · 쿠팡  = 지급내역조회(settlement-histories) status DONE
#  · 스스  = 정산 완료일(settleCompleteDate)
#  나머지 4곳(롯데온·11번가·옥션·G마켓)은 **입금 여부를 알려주는 창구가 없다** →
#  받는 날이 지나도 우리가 확인할 방법이 없다(통장·마켓 화면 대조가 유일).
_PAID_CONFIRM_MARKETS = ("coupang", "smartstore")

_MK_KO = {"coupang": "쿠팡", "smartstore": "스마트스토어", "lotteon": "롯데온",
          "eleven11": "11번가", "auction": "옥션", "gmarket": "G마켓"}


def overdue_reason(line: dict, *, market: str) -> str:
    """「받는 날이 지났는데 확인 안 됨」의 사유 코드.

    라이브 실측(2026-08-06, 393건) — 대부분은 **돈이 밀린 게 아니다**:
      not_confirmed_yet  289건 (롯데온 212·쿠팡 74·옥션 2·스스 1)
        = 배송완료인데 아직 구매확정 전. 정산은 구매확정 뒤에 시작하므로 「지남」이 아니라
          「아직 시작 안 함」이다. 추정 날짜가 이른 것.
      no_confirm_channel 104건 (11번가)
        = 마켓이 준 송금예정일이 지났는데, 그 마켓은 입금 완료를 알려주지 않는다.
    """
    st = str(line["row"].get("주문상태") or "")
    if not _is_confirmed(st):
        return "not_confirmed_yet"
    if market not in _PAID_CONFIRM_MARKETS:
        return "no_confirm_channel"
    return "not_in_batch"


def reason_text(code: str, market: str) -> dict:
    """사유 코드 → 사장님이 읽는 말 {뜻, 확인}. 화면·API 가 같은 문구를 쓴다."""
    mk = _MK_KO.get(market, market)
    if code == "not_confirmed_yet":
        return {"뜻": f"아직 구매확정 전이에요 (배송은 끝남) — 정산은 구매확정 뒤에 시작합니다",
                "확인": f"{mk}에서 구매확정이 됐는지 보세요. 배송완료로 오래 머물면 "
                        f"주문 상태를 다시 불러오거나 {mk}에 문의가 필요합니다"}
    if code == "no_confirm_channel":
        return {"뜻": f"{mk}이(가) 알려준 받는 날이 지났어요 — {mk}은(는) 입금했는지를 "
                      f"알려주지 않아 우리가 확인할 수 없습니다",
                "확인": f"통장 또는 {mk} 판매자센터 정산 화면과 대조해 보세요"}
    if code == "not_in_batch":
        return {"뜻": f"{mk} 정산 회차에 아직 안 잡혔어요",
                "확인": f"며칠 뒤 다시 보시거나 {mk} 정산 화면에서 확인하세요"}
    return {"뜻": "", "확인": ""}


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
            # 왜 지났는지를 같이 들려 보낸다 — 숫자만으론 뭘 해야 할지 알 수 없다.
            ev["reason"] = overdue_reason(line, market=line["market"])
            ev["days_over"] = (today - d).days
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
    reasons: dict = {}      # 「지남」이 무엇 때문인지 — 카드 옆 한눈 요약

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
                if b_name == "overdue" and ev.get("reason"):
                    rs = reasons.setdefault(ev["reason"], {"금액": 0, "건수": 0, "마켓": {}})
                    rs["금액"] += ev["amount"]
                    rs["건수"] += 1
                    rs["마켓"][market] = rs["마켓"].get(market, 0) + ev["amount"]
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
            "overdue_reasons": reasons,
            "buckets": [{"key": k, **v} for k, v in sorted(buckets.items())]}


# 마켓별 기대 수수료율(%) — 2026-08-02 사장님 확정분(market_fee_defaults 시드와 같은 값).
#  정산율이 이것과 크게 어긋나면 돈이 틀어진 신호다.
_EXPECT_FEE_PCT = {"coupang": 11.55, "smartstore": 6.0, "lotteon": 18.0,
                   "eleven11": 11.0, "auction": 15.0, "gmarket": 15.0}
#: 이 %p 이상 어긋나면 경고 — 카테고리·경유 수수료 편차를 감안한 여유.
RATE_WARN_GAP_PCT = 5.0


def rate_watch(market_rows: list) -> dict:
    """매출 대비 정산율을 마켓 기대 수수료율과 대조한다(돈 틀어짐 조기 감시).

    🔴 왜 필요한가(2026-08-06 라이브) — 정산율이 6월 90.5%·7월 92.4% 로 나왔다.
      수수료가 6~18% 인데 7~9% 만 뗀 셈이라 **정산액 과대 또는 매출 과소**가 의심되는데,
      화면 어디에도 그걸 알아챌 장치가 없었다. 숫자를 나란히 놓고 어긋나면 말한다.

    market_rows = [{"market","revenue","settle"}] · 재료 없는 마켓은 담지 않는다(날조 금지).
    """
    out = {}
    for r in market_rows or []:
        mk = r.get("market")
        rev = r.get("revenue") or 0
        stl = r.get("settle") or 0
        if not mk or rev <= 0 or stl <= 0:
            continue
        rate = round(stl / rev * 100, 1)
        exp = _EXPECT_FEE_PCT.get(mk)
        if exp is None:
            out[mk] = {"정산율": rate, "기대수수료": None, "차이": None, "경고": False}
            continue
        gap = round(abs((100 - rate) - exp), 2)       # 실수수료 vs 기대수수료 차이(%p)
        out[mk] = {"정산율": rate, "기대수수료": exp, "실수수료": round(100 - rate, 1),
                   "차이": gap, "경고": gap >= RATE_WARN_GAP_PCT}
    return out


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
    # 전 기간 마켓별 합으로 정산율 감시 — 「이 마켓 수수료가 이상하다」를 화면이 말한다.
    tot: dict = {}
    for b in buckets.values():
        for mk, v in (b.get("markets") or {}).items():
            t = tot.setdefault(mk, {"market": mk, "revenue": 0, "settle": 0})
            t["revenue"] += v.get("revenue") or 0
            t["settle"] += v.get("settle") or 0
    return {"meta": {"revenue_substituted": substituted},
            "rate_watch": rate_watch(list(tot.values())),
            "buckets": [{"key": k, **v} for k, v in sorted(buckets.items())]}
