# 정산예정금액 탭 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 주문관리 하위탭 「정산예정금액」 — 기간별(일/주/월) 미래 지급예정 정산금을 지급예정일·주문일 두 축으로, 마켓총→마켓별→계정별→주문별 드릴다운과 실측/추정 배지로 보여준다.

**Architecture:** ① 4개 마켓 정산 스윕이 이미 파싱하는 지급예정일(쿠팡 settlementDate·스스 settleExpectDate·ESM SettleExpectDate/RemitDate·11번가 stlPlnDy)을 `row` JSON에 저장(스윕 로직 무변경, 저장만 추가). ② 신규 순수함수 엔진 `lemouton/margin/settle_plan.py`가 저장 행을 4부류(확정예정/미확정예정/기한경과/위험)로 상호배타 분류하고 지급예정일을 실값→규칙추정 순으로 결정, 기간 버킷 집계. 금액은 기존 `_settlement_for` 재사용(재계산 금지). ③ 읽기 전용 집계 API + 편집 가능한 규칙표(state_store) + 탭 UI.

**Tech Stack:** Flask + SQLAlchemy(MarketOrderLine.row JSON) + 순수 Python 엔진 + 바닐라 JS 템플릿 블록. 테스트 pytest.

**전제 규약 (전 Task 공통 — 위반 금지)**
- 금액 재계산 금지: 정산액은 `_settlement_for(row)`(sell_source.py:278)와 row의 `정산예정금(배송비포함)`·`정산예정금액`만 쓴다.
- 폴백·날조 금지: 날짜·금액이 없으면 없는 대로(추정은 `estimated` 배지, 아예 없으면 `none`).
- 클레임 행(`_kind=='change'`)·취소완료는 예정액 제외. 롯데온 규약(양수만·라인 단위) 준수.
- ESM SettleExpectDate 의 1800~1999년대 값 = 보류 센티널(SettleExceptName) → 날짜 아님, 버린다. `0001-01-01`도 빈 값.
- 스윕에서 **이미 real 인 행도 날짜는 갱신**한다(금액은 기존 규약대로 손대지 않음). 값이 같으면 쓰기 생략.
- 배포 후 상태 파일은 `shared.state_store.state_path()` (컨테이너 data/는 배포마다 증발).
- 새 하위탭 id는 `settle_plan` / 사이드바 `i_settle_plan` (🔴 삭제된 `i_sales` 재사용 금지 — `_REMOVED_IDS`가 지움).

---

### Task 1: 규칙표 저장소 `settle_plan_rules.py`

**Files:**
- Create: `프로그램/_시스템/lemouton/margin/settle_plan_rules.py`
- Test: `프로그램/_시스템/tests/margin/test_settle_plan_rules.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/margin/test_settle_plan_rules.py
"""규칙표 저장소 — 기본값 로드·저장·빠른정산 계정 스위치."""
import json


def test_기본_규칙에_6마켓이_전부_있다(tmp_path, monkeypatch):
    monkeypatch.setenv("MOUM_STATE_DIR", str(tmp_path))
    from lemouton.margin import settle_plan_rules as R
    rules = R.load_rules()
    for mk in ("coupang", "smartstore", "lotteon", "eleven11", "auction", "gmarket"):
        assert mk in rules["markets"], mk
        m = rules["markets"][mk]
        assert m["auto_confirm_days"] >= 0
        assert m["cycle_days"] >= 0
    assert rules["markets"]["coupang"]["split_ratio"] == 0.7
    assert rules["fast_accounts"] == {}          # 기본: 빠른정산 미지정


def test_저장하면_다음_로드에_반영(tmp_path, monkeypatch):
    monkeypatch.setenv("MOUM_STATE_DIR", str(tmp_path))
    from lemouton.margin import settle_plan_rules as R
    rules = R.load_rules()
    rules["fast_accounts"] = {"smartstore": ["본계정"], "coupang": ["쿠팡1"]}
    rules["markets"]["lotteon"]["cycle_days"] = 9
    R.save_rules(rules)
    again = R.load_rules()
    assert again["fast_accounts"]["smartstore"] == ["본계정"]
    assert again["markets"]["lotteon"]["cycle_days"] == 9


def test_깨진_파일이면_기본값으로_복구(tmp_path, monkeypatch):
    monkeypatch.setenv("MOUM_STATE_DIR", str(tmp_path))
    from lemouton.margin import settle_plan_rules as R
    with open(R._rules_path(), "w", encoding="utf-8") as f:
        f.write("{깨짐")
    rules = R.load_rules()
    assert "coupang" in rules["markets"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "프로그램/_시스템" && python -m pytest tests/margin/test_settle_plan_rules.py -v`
Expected: FAIL with `ModuleNotFoundError: settle_plan_rules`

- [ ] **Step 3: Write implementation**

```python
# lemouton/margin/settle_plan_rules.py
"""정산예정금액 탭 — 마켓별 정산주기 규칙표 (편집 가능한 데이터).

🔴 왜 데이터인가 — 마켓 정산 정책은 바뀐다. 하드코딩하면 정책이 바뀔 때 표가 통째로
   틀리고 배포 없인 못 고친다. 초기값은 마켓 문서·통념 기반 **추정 시작점**이고,
   화면(규칙표 패널)에서 보고 고친다. 실지급일 이력과의 오차는 API 가 역산해 보여준다.

★ 지급예정일 결정에서 이 규칙은 **실값이 없을 때만** 쓰인다(settle_plan.payout_events).
★ fast_accounts = 빠른정산 사용 계정 목록 {market: [계정명…]} — 사장님이 화면에서 켠다
  (스스 1·쿠팡 1 계정 사용 중이라고 확정, 2026-08-06).
"""
from __future__ import annotations

import json

from shared.state_store import state_path

_FILENAME = "settle_plan_rules.json"

# auto_confirm_days: 배송완료 후 자동 구매확정까지 일수(마켓 안내 기준 초기값)
# transit_days: 배송중→배송완료 추정 일수
# cycle_days: 구매확정(인식) 후 지급까지 일수(달력일 근사 — 영업일 보정은 규칙표에서 조정)
# fast_cycle_days: 빠른정산 계정의 발송(집화) 후 지급까지 일수
# split_ratio/split_rest_days: 쿠팡 주정산 분할(1차 지급 비율·잔여분 추가 일수)
DEFAULT_RULES: dict = {
    "markets": {
        "coupang":    {"auto_confirm_days": 7, "transit_days": 2, "cycle_days": 15,
                       "fast_cycle_days": 2, "split_ratio": 0.7, "split_rest_days": 30},
        "smartstore": {"auto_confirm_days": 8, "transit_days": 2, "cycle_days": 1,
                       "fast_cycle_days": 1, "split_ratio": 1.0, "split_rest_days": 0},
        "lotteon":    {"auto_confirm_days": 7, "transit_days": 2, "cycle_days": 7,
                       "fast_cycle_days": 0, "split_ratio": 1.0, "split_rest_days": 0},
        "eleven11":   {"auto_confirm_days": 7, "transit_days": 2, "cycle_days": 3,
                       "fast_cycle_days": 0, "split_ratio": 1.0, "split_rest_days": 0},
        "auction":    {"auto_confirm_days": 8, "transit_days": 2, "cycle_days": 1,
                       "fast_cycle_days": 0, "split_ratio": 1.0, "split_rest_days": 0},
        "gmarket":    {"auto_confirm_days": 8, "transit_days": 2, "cycle_days": 1,
                       "fast_cycle_days": 0, "split_ratio": 1.0, "split_rest_days": 0},
    },
    "fast_accounts": {},
}


def _rules_path() -> str:
    return state_path(_FILENAME)


def load_rules() -> dict:
    """저장본 로드. 없거나 깨졌으면 기본값. 마켓·키 누락은 기본값으로 채운다(부분 저장 보호)."""
    data: dict = {}
    try:
        with open(_rules_path(), "r", encoding="utf-8") as f:
            data = json.load(f) or {}
    except (OSError, json.JSONDecodeError):
        data = {}
    out = {"markets": {}, "fast_accounts": dict(data.get("fast_accounts") or {})}
    saved = data.get("markets") or {}
    for mk, base in DEFAULT_RULES["markets"].items():
        merged = dict(base)
        merged.update({k: v for k, v in (saved.get(mk) or {}).items() if k in base})
        out["markets"][mk] = merged
    return out


def save_rules(rules: dict) -> None:
    with open(_rules_path(), "w", encoding="utf-8") as f:
        json.dump(rules, f, ensure_ascii=False, indent=1)
```

- [ ] **Step 4: Run test to verify it passes** — 같은 명령, Expected: 3 PASS
- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat(settle-plan): 정산주기 규칙표 저장소(state_store·편집 가능·빠른정산 계정 스위치)"`

---

### Task 2: 분류·지급이벤트·집계 엔진 `settle_plan.py`

**Files:**
- Create: `프로그램/_시스템/lemouton/margin/settle_plan.py`
- Test: `프로그램/_시스템/tests/margin/test_settle_plan_engine.py`

핵심 자료형: 엔진 입력 = `{"row": dict, "status_at": datetime|None, "market": str, "account": str}` 목록 (라우트가 MarketOrderLine에서 만든다). 출력 이벤트 = `{"date": "YYYY-MM-DD"|None, "amount": int, "date_source": "real"|"estimated"|None}`.

- [ ] **Step 1: Write the failing tests** (핵심만 발췌 — 전부 구현할 것)

```python
# tests/margin/test_settle_plan_engine.py
"""분류 상호배타·지급이벤트·버킷 집계 — 자금계획 정확성의 핵심."""
import datetime as dt

from lemouton.margin import settle_plan as SP
from lemouton.margin.settle_plan_rules import DEFAULT_RULES

TODAY = dt.date(2026, 8, 6)


def _line(status="구매확정", market="gmarket", incl=10000, src="real",
          date=None, paid=None, kind=None, account="계정A", status_at=None):
    row = {"주문상태": status, "정산예정금(배송비포함)": incl, "정산예정금액": incl,
           "_settle_source": src}
    if date:
        row["정산예정일"] = date
    if paid:
        row["_settle_paid_date"] = paid
    if kind:
        row["_kind"] = kind
    return {"row": row, "market": market, "account": account,
            "status_at": status_at or dt.datetime(2026, 8, 1, 12, 0)}


def test_분류_상호배타_한_주문은_딱_한_부류():
    lines = [
        _line(status="구매확정", date="2026-08-20"),                    # confirmed
        _line(status="배송중"),                                          # unconfirmed
        _line(status="구매확정", date="2026-07-01"),                    # overdue(예정일 경과·수령 미확인)
        _line(status="반품요청"),                                        # risk
        _line(status="취소완료"),                                        # excluded
        _line(kind="change"),                                            # excluded
        _line(status="구매확정", date="2026-07-01", paid="2026-07-02"),  # paid → excluded
    ]
    cats = [SP.classify(ln, today=TODAY) for ln in lines]
    assert cats == ["confirmed", "unconfirmed", "overdue", "risk",
                    "excluded", "excluded", "paid"]


def test_실값_지급예정일이_규칙추정보다_우선():
    ln = _line(status="구매확정", date="2026-08-20")
    evs = SP.payout_events(ln, DEFAULT_RULES, today=TODAY)
    assert evs == [{"date": "2026-08-20", "amount": 10000, "date_source": "real"}]


def test_추정_미확정_배송중은_이동중일수와_자동확정과_주기를_더한다():
    ln = _line(status="배송중", market="lotteon", src="estimated",
               status_at=dt.datetime(2026, 8, 1, 12, 0))
    evs = SP.payout_events(ln, DEFAULT_RULES, today=TODAY)
    # 8/1 관측 + transit2 + auto_confirm7 + cycle7 = 8/17
    assert evs[0]["date"] == "2026-08-17"
    assert evs[0]["date_source"] == "estimated"


def test_쿠팡_추정은_두_조각이고_합이_원금과_같다():
    ln = _line(status="구매확정", market="coupang", incl=10001, src="estimated",
               status_at=dt.datetime(2026, 8, 1, 12, 0))
    evs = SP.payout_events(ln, DEFAULT_RULES, today=TODAY)
    assert len(evs) == 2
    assert sum(e["amount"] for e in evs) == 10001      # 반올림 유실 금지


def test_쿠팡_실값_두_날짜가_있으면_실값으로_분할():
    ln = _line(status="구매확정", market="coupang", incl=10000, date="2026-08-10")
    ln["row"]["_settle_final_date"] = "2026-09-01"
    evs = SP.payout_events(ln, DEFAULT_RULES, today=TODAY)
    assert [e["date"] for e in evs] == ["2026-08-10", "2026-09-01"]
    assert sum(e["amount"] for e in evs) == 10000


def test_빠른정산_계정은_발송기준_주기로_계산():
    rules = {**DEFAULT_RULES, "fast_accounts": {"smartstore": ["본계정"]}}
    ln = _line(status="배송중", market="smartstore", account="본계정",
               src="estimated", status_at=dt.datetime(2026, 8, 5, 9, 0))
    evs = SP.payout_events(ln, rules, today=TODAY)
    assert evs[0]["date"] == "2026-08-06"   # 발송관측 8/5 + fast_cycle 1


def test_버킷_주별은_월요일_시작():
    assert SP.bucket_key("2026-08-06", "week") == "2026-08-03"   # 목→그 주 월요일
    assert SP.bucket_key("2026-08-06", "month") == "2026-08"
    assert SP.bucket_key("2026-08-06", "day") == "2026-08-06"


def test_집계_확정과_미확정이_섞이지_않고_기한경과는_본표_밖():
    lines = [
        _line(status="구매확정", date="2026-08-20", incl=100),
        _line(status="배송완료", src="estimated", incl=200,
              status_at=dt.datetime(2026, 8, 1)),
        _line(status="구매확정", date="2026-07-01", incl=400),   # overdue
    ]
    agg = SP.aggregate_payout(lines, DEFAULT_RULES, unit="week", today=TODAY)
    assert agg["kpi"]["confirmed_future"] == 100
    assert agg["kpi"]["unconfirmed_future"] == 200
    assert agg["kpi"]["overdue"] == 400
    assert agg["kpi"]["total_uncollected"] == 700
    all_bucket_sum = sum(b["total"] for b in agg["buckets"])
    assert all_bucket_sum == 300                     # overdue 는 버킷 밖 별도 줄


def test_주문일축_매출은_실결제_대체시_카운트():
    lines = [_line(status="구매확정", incl=100), _line(status="구매확정", incl=100)]
    lines[0]["row"]["실결제금액"] = 12000
    lines[0]["row"]["주문일"] = "2026-08-01 10:00"
    lines[1]["row"]["상품금액"] = 9000
    lines[1]["row"]["배송비"] = 3000
    lines[1]["row"]["주문일"] = "2026-08-01 11:00"
    agg = SP.aggregate_by_order_date(lines, unit="day",
                                     d_from="2026-08-01", d_to="2026-08-31")
    b = agg["buckets"][0]
    assert b["revenue"] == 24000
    assert agg["meta"]["revenue_substituted"] == 1   # 조용한 대체 금지 — 개수 표기
```

- [ ] **Step 2: Run to verify FAIL** — `python -m pytest tests/margin/test_settle_plan_engine.py -v`

- [ ] **Step 3: Write implementation**

```python
# lemouton/margin/settle_plan.py
"""정산예정금액 탭 엔진 — 분류·지급이벤트·기간 버킷 집계 (순수 함수, DB 없음).

■ 4부류 상호배타 (스펙 §2 — 중복 원천 차단):
    excluded  = 클레임 행(_kind=change)·취소완료(zero_cancel)
    risk      = 반품·교환·취소 **진행 중** (예정액에서 빼고 별도 줄 — 돈 부풀리기 방지)
    paid      = 수령 확인(_settle_paid_date 있음 — ESM RemitDate·스스 settleCompleteDate)
    overdue   = 지급예정일 < 오늘인데 수령 확인 불가 (**조용히 빼지 않는다** — 별도 줄 상시)
    confirmed / unconfirmed = 미래 예정분 (본표). 상태 문자열로만 갈려 한 행은 한 곳에만.

■ 금액 = margin.sell_source._settlement_for(row) 그대로 (재계산 금지 — 마진계산기와
  같은 숫자를 보게 하는 단일 원천 규약을 이 탭도 따른다).

■ 지급예정일 = 실값(row.정산예정일) → 규칙 추정(settle_plan_rules) 순.
  추정 기준점(anchor)은 마켓 응답에 없는 값이라 **우리 관측 시각(status_at)** 근사 —
  그래서 항상 date_source='estimated' 배지가 붙는다(정직 표기).
"""
from __future__ import annotations

import datetime as dt

from lemouton.margin.sell_source import _settlement_for

# 반품·교환·취소 "진행 중" — 완료(취소완료=excluded·반품완료 등 클레임 경로)와 구분.
_RISK_MARKERS = ("반품요청", "반품진행", "반품접수", "교환요청", "교환진행",
                 "취소요청", "취소접수", "취소철회대기", "미수취신고")
_CONFIRMED = "구매확정"
_SHIPPED_MARKERS = ("배송중", "배송완료", "발송완료", "수취완료", "구매결정")


def _norm_date(s) -> str | None:
    """'2026-08-06'·'2026-08-06T00:00:00'·'2026/08/06'·'20260806' → 'YYYY-MM-DD'.
    2000-01-01 이전은 센티널(ESM 보류 1991-01-01류·빈값 0001-01-01) → None."""
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
        # 잔여분(쿠팡 30%)이 미래에 남아 있으면 아직 「미래 예정」으로 본다.
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
    """한 라인의 지급 이벤트(1~2개). 쿠팡 분할지급은 두 조각, 합=원금(유실 금지)."""
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
        return (d - dt.timedelta(days=d.weekday())).isoformat()   # 월요일
    if unit == "month":
        return date_str[:7]
    return d.isoformat()


def aggregate_payout(lines: list, rules: dict, *, unit: str,
                     today: dt.date) -> dict:
    """지급예정일 축 집계 — 본표(미래 확정/미확정) + 별도 줄(overdue·risk·paid)."""
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
        if cat in ("overdue", "risk"):
            kpi[cat] += amount
            _acc(extras[cat], market, account, amount)
            continue
        for ev in payout_events(ln, rules, today=today):
            if ev["date_source"] == "real":
                counts["real_dates"] += 1
            elif ev["date_source"] == "estimated":
                counts["estimated_dates"] += 1
            else:
                counts["undated"] += 1
            # 이벤트 단위 과거/미래 판정 — 쿠팡 1차분이 이미 지났으면 그 조각만 overdue.
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
    """주문일 축 — 클레임(취소완료·클레임 행·위험 진행분) 제외 매출액 + 정산예정금.
    매출액 = 실결제금액, 없으면 상품금액+배송비 대체(대체 건수 meta 표기 — 조용한 대체 금지)."""
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
```

- [ ] **Step 4: Run tests → PASS.** 전 항목 통과 전 다음 Task 진입 금지.
- [ ] **Step 5: Commit** — `feat(settle-plan): 분류·지급이벤트·집계 엔진(4부류 상호배타·쿠팡 분할·주별 월요일)`

---

### Task 3: 스윕 지급예정일 저장 — ESM

**Files:**
- Modify: `프로그램/_시스템/shared/platforms/esm/settlements.py` (settle_detail_map ent 에 날짜 3종 추가)
- Modify: `프로그램/_시스템/lemouton/markets/order_ingest.py:901-917` (refresh_settlement 루프)
- Test: `프로그램/_시스템/tests/markets/test_settle_plan_sweep_dates.py`

- [ ] **Step 1: Test** — settle_detail_map 이 원주문 행의 `SettleExpectDate`→`정산예정일`, `RemitDate`→`송금일`을 정규화해 담고, 1991-01-01 류 센티널은 버리는지. refresh_settlement 가 ①미real 행에 금액+날짜를 함께 쓰고 ②**이미 real 인 행에도 날짜만** 채우는지(금액 불변).

```python
def test_esm_상세맵이_정산예정일과_송금일을_담는다(monkeypatch):
    # _request_with_rate_backoff 를 가짜 응답으로 monkeypatch:
    fake = {"ResultCode": 0, "TotalCount": 1, "Data": [{
        "ContrNo": 123, "Kind": 1, "SettlementPrice": "9000",
        "OrderUnitPrice": "10000", "OrderQty": "1", "BuyerPayAmt": "10000",
        "SettleExpectDate": "2026-08-20T00:00:00", "RemitDate": "0001-01-01T00:00:00"}]}
    ...
    ent = out["123"]
    assert ent["정산예정일"] == "2026-08-20"
    assert ent.get("송금일") is None          # 센티널은 담지 않는다


def test_esm_보류_센티널_1991년은_날짜가_아니다(...):
    # SettleExpectDate "1991-01-01T00:00:00" → ent["정산예정일"] is None
```

- [ ] **Step 2: FAIL 확인**
- [ ] **Step 3: 구현.** `settlements.py` — ent 초기화에 `"정산예정일": None, "송금일": None, "구매확정일": None` 추가, `_is_origin(row)` 블록 안에서:

```python
                if _is_origin(row):
                    ...기존 단가·수량·실결제·SiteGoodsNo...
                    for src_k, dst_k in (("SettleExpectDate", "정산예정일"),
                                         ("RemitDate", "송금일"),
                                         ("BuyDecisonDate", "구매확정일")):
                        if ent.get(dst_k) is None:
                            ent[dst_k] = _norm_settle_date(row.get(src_k))
```

파일 상단에 (settle_plan._norm_date 와 동일 규약 — platforms 는 margin 을 임포트하지 않는다, 층 역전 금지):

```python
def _norm_settle_date(s):
    """ESM Date → 'YYYY-MM-DD'. 2000년 이전(보류 센티널 1991-01-01류·빈값 0001-01-01)은 None."""
    t = str(s or "").strip()[:10].replace("/", "-")
    if len(t) == 8 and t.isdigit():
        t = f"{t[:4]}-{t[4:6]}-{t[6:8]}"
    try:
        import datetime as _d
        return t if _d.date.fromisoformat(t).year >= 2000 else None
    except ValueError:
        return None
```

`order_ingest.refresh_settlement` 루프(901-917) — real-스킵보다 **먼저** ent 를 찾고 날짜를 얹는다:

```python
        for o in lines:
            row = dict(o.row or {})
            if str(row.get("_kind") or "") == "change":
                continue
            ent = smap.get(str(row.get("오픈마켓주문번호") or "").strip())
            if not ent:
                continue
            changed = False
            # ── 날짜는 real 여부와 무관하게 채운다(금액 규약 불변·백필 겸용) ──
            for k in ("정산예정일", "송금일"):
                v = ent.get(k)
                dst = "_settle_paid_date" if k == "송금일" else "정산예정일"
                if v and row.get(dst) != v:
                    row[dst] = v
                    changed = True
            if str(row.get("_settle_source") or "") != "real":
                amt = ent.get("정산예정금액")
                if amt is not None:
                    stat["targets"] += 1
                    row["정산예정금액"] = amt
                    row["_settle_source"] = "real"
                    changed = True
            if not changed:
                continue
            _finalize_rows([row])
            o.row = row
            o.last_seen_at = _store._now()
            stat["updated"] += 1
```

(기존 `if v.get("정산예정금액") is not None: smap.setdefault(...)` 병합부(879-881)는 날짜만 있는 ent 도 담게 `if v.get("정산예정금액") is not None or v.get("정산예정일"):` 로 완화.)

- [ ] **Step 4: PASS 확인** + 기존 ESM 스윕 테스트 회귀: `python -m pytest tests/ -k "settle" -v`
- [ ] **Step 5: Commit** — `feat(settle-plan): ESM 스윕이 정산예정일·송금일 저장(real 행 날짜 백필 겸용·보류 센티널 차단)`

---

### Task 4: 스윕 지급예정일 저장 — 쿠팡·스스·11번가

**Files:**
- Modify: `프로그램/_시스템/lemouton/markets/order_export.py:1381-` (`_coupang_settle_map` — 날짜맵 추가 반환)
- Modify: `프로그램/_시스템/lemouton/markets/order_ingest.py` (쿠팡 1196-1244 · 스스 1296-1384 · 11번가 1427-1489)
- Modify: `프로그램/_시스템/shared/platforms/eleven11/settlement.py` (parse_settlement_details·settlement_detail_map 에 날짜 키)
- Test: `tests/markets/test_settle_plan_sweep_dates.py` 에 마켓별 케이스 추가

- [ ] **Step 1: Tests** (마켓별 — FAIL 확인 후 구현)
  - 쿠팡: `_coupang_settle_map` 이 `(item_map, deliv_map, date_map)` 3-튜플을 반환하고 date_map = `{oid: {"정산예정일": settlementDate, "_settle_final_date": finalSettlementDate}}`. 스윕이 row 에 두 날짜를 쓰고, real 행에도 날짜만 백필.
  - 스스: 스윕 수집 루프가 `settleExpectDate`→`정산예정일`, `settleCompleteDate`→`_settle_paid_date` 를 poid 별로 담아 row 에 쓴다.
  - 11번가: `parse_settlement_details` entry 에 `송금예정일`(stlPlnDy, `2026/08/20`→`2026-08-06` 정규화)·`구매확정일`(pocnfrmDt YYYYMMDD 정규화) 추가. 스윕이 `정산예정일` 로 쓴다.
- [ ] **Step 2: 구현 요점**
  - 쿠팡 `_coupang_settle_map`: 페이지 루프의 `order` 레벨에서 `order.get("settlementDate")`·`order.get("finalSettlementDate")` 를 `date_map[oid]` 로 수집(REFUND 주문 제외). **호출부 2곳 전부 갱신**: 스윕 1201 `imap, _deliv = ...` → `imap, _deliv, dmap = ...`, 인라인 조인부(grep `_coupang_settle_map(` 전수 — 시그니처 불일치로 조용히 깨지는 곳 0 확인).
  - 쿠팡 스윕 루프(1225-1244): ESM Task 3 과 동일 패턴 — oid 로 dmap 조회, real 여부 무관 날짜 갱신 + 미real 금액 갱신, changed 플래그.
  - 스스 스윕: 수집 루프(1315-1331)에 `pdate: dict = {}` — 상품행(else 분기)에서 `pdate[str(poid)] = {"정산예정일": el.get("settleExpectDate"), "_settle_paid_date": el.get("settleCompleteDate")}` (None 제외). 갱신 루프(1364-1384)에 changed 패턴 이식.
  - 11번가 `parse_settlement_details`: entry 채집 뒤 `result[key]` 만들 때 `stlPlnDy`·`pocnfrmDt` 정규화(esm 과 같은 `_norm_settle_date` 헬퍼를 이 파일에도 — 층 규약상 platforms 끼리도 서로 임포트하지 않는다, 5줄 중복 허용). `settlement_detail_map` merge 에서 `m.setdefault("송금예정일", ent.get("송금예정일"))` 식으로 첫 값 유지. 스윕 루프(1457-1489)에 `new_row["정산예정일"] = ent["송금예정일"]`(있을 때) + real 행 날짜 백필 changed 패턴.
- [ ] **Step 3: PASS + 회귀** — `python -m pytest tests/markets tests/margin -v` (기존 정산 테스트 전부 초록 확인. 🔴 `_coupang_settle_map` 3-튜플 전환 후 호출부 grep 재확인)
- [ ] **Step 4: Commit** — `feat(settle-plan): 쿠팡(분할 2날짜)·스스(예정+완료일)·11번가(송금예정일) 스윕 저장`

---

### Task 5: 집계 API + 규칙 API (`orders.py`)

**Files:**
- Modify: `프로그램/_시스템/webapp/routes/orders.py` (라우트 3개 추가 — settlement-sweep 라우트 근처)
- Test: `프로그램/_시스템/tests/orders/test_settle_plan_api.py`

- [ ] **Step 1: Tests** — Flask test client 로:
  - `GET /orders/api/settle-plan?axis=payout&unit=week` → 200, kpi 4키·buckets 존재. (세션 DB 에 가짜 MarketOrderLine 2행 심기 — 기존 orders 테스트의 세션 픽스처 재사용)
  - `GET /orders/api/settle-plan?axis=order&unit=day&from=2026-08-01&to=2026-08-31` → revenue 버킷.
  - `GET /orders/api/settle-plan/detail?category=confirmed&market=gmarket&bucket=2026-08-17&unit=week` → 주문 목록(주문번호·상품명·상품분·배송비·배송비포함·지급예정일·배지).
  - `GET /orders/api/settle-plan/rules` → 규칙 JSON + calibration. `POST` 로 fast_accounts 저장 왕복.
- [ ] **Step 2: 구현**

```python
# orders.py 하단(진단 라우트들 근처)에 추가
def _settle_plan_lines(markets=None):
    """MarketOrderLine → 엔진 입력. 최근 180일 주문만(쿠팡 2달 주기 + 여유)."""
    from shared import db as _db
    from lemouton.markets.models_orders import MarketOrderLine
    lo = (_dt.datetime.now() - _dt.timedelta(days=180)).strftime("%Y-%m-%d")
    s = _db.SessionLocal()
    try:
        q = s.query(MarketOrderLine).filter(MarketOrderLine.order_date >= lo)
        if markets:
            q = q.filter(MarketOrderLine.market.in_(markets))
        return [{"row": dict(o.row or {}), "market": o.market,
                 "account": o.account or "", "status_at": o.status_at}
                for o in q.all()]
    finally:
        s.close()


@bp.route('/api/settle-plan')
def settle_plan_agg():
    from lemouton.margin import settle_plan as SP
    from lemouton.margin.settle_plan_rules import load_rules
    axis = (request.args.get('axis') or 'payout').strip()
    unit = (request.args.get('unit') or 'week').strip()
    if unit not in ('day', 'week', 'month'):
        unit = 'week'
    mk = (request.args.get('market') or '').strip()
    lines = _settle_plan_lines([mk] if mk else None)
    today = _dt.date.today()
    if axis == 'order':
        out = SP.aggregate_by_order_date(
            lines, unit=unit,
            d_from=(request.args.get('from') or ''), d_to=(request.args.get('to') or ''))
    else:
        out = SP.aggregate_payout(lines, load_rules(), unit=unit, today=today)
    return jsonify(out)
```

  - `/api/settle-plan/detail`: category(confirmed|unconfirmed|overdue|risk)·market·account·bucket·unit 필터 → classify+payout_events 로 같은 규약 재판정 후 해당 주문 목록 반환. 각 행: `{"주문번호", "상품명", "옵션", "수량", "상품정산예정": 정산예정금액, "배송비예정": (배송비포함−상품분), "총정산예정": 배송비포함, "지급예정일", "date_source", "_settle_source", "주문상태", "account"}`.
  - `/api/settle-plan/rules` GET: `load_rules()` + calibration — 저장 행 중 `정산예정일`(real)과 status_at 이 다 있는 행에서 `(실예정일 − 관측확정일)` 중앙값을 마켓별로 계산해 `{"market": {"rule_days": X, "measured_days": Y, "gap": Y-X, "n": 건수}}` 반환(재료 없으면 `"측정불가"` — 날조 금지). POST: body 검증(아는 키만·수치 범위 0~120) 후 `save_rules`.
  - 🔴 admin 인증: orders.py 의 기존 라우트들과 같은 데코레이터 규약을 따른다(파일 상단 확인 — 없으면 없는 대로, 새 인증 발명 금지).
- [ ] **Step 3: PASS + Commit** — `feat(settle-plan): 집계·상세·규칙 API (+실측 보정 역산)`

---

### Task 6: UI 시안 게이트 (design-mockup 스킬)

- [ ] **Step 1:** `/design-mockup` 스킬 발동 — 신규 탭 화면. 항목별 결정 게이트(KPI 카드 4장·본표 구분 표기 방식·별도 줄 위치·드릴다운 방식·규칙표 패널 위치·배지)를 사장님께 확인. 시안 승인 전 Task 7 착수 금지.
- [ ] **Step 2:** 확정 시안을 이 계획서에 추기(선택 안·숫자).

### Task 7: 탭 UI (`SUBTABS` + 템플릿 블록)

**Files:**
- Modify: `프로그램/_시스템/webapp/routes/orders.py:29-43` (SUBTABS), `98` 근처 무변경 확인
- Modify: `프로그램/_시스템/webapp/templates/orders/index.html` (margin 블록 3705 앞에 `{% elif tab == 'settle_plan' %}` 블록)
- Test: `프로그램/_시스템/tests/orders/test_settle_plan_tab.py`

- [ ] **Step 1: Test** — `GET /orders/?tab=settle_plan` 200 + `id="sp-kpi"`·`id="sp-table"` 마크업 존재(🔴 JS 문자열 아닌 **마크업 id** 로 검사 — `{# #}` 주석·JS 검사기 함정 회피), SUBTABS 에 key 존재.
- [ ] **Step 2: 구현** — SUBTABS 에 `{'key': 'settle_plan', 'label': '정산예정금액', 'desc': '기간별 미래 정산예정금 — 확정/미확정 구분·마켓·계정·주문 드릴다운'}` (recon 뒤). 템플릿 블록: KPI 카드(총 미수령·확정예정·미확정예정·기한경과+위험), 축/단위 토글, 본표(fetch `/orders/api/settle-plan`), 별도 줄(기한경과·위험·수령확인), 셀 클릭 → detail fetch 드릴다운(마켓→계정→주문), 규칙표 패널(GET/POST rules + 보정 오차 표시), 배지(실측=초록·추정=노랑 — `margin_settle_cell.js` 색 규약 재사용). 디자인: tokens.css 변수만(`var(--토큰, #예비값)` 예비값 필수), `.num` 은 값 칸에만(머리글 금지 — 287px 사고 재발 방지), 시안(Task 6) 확정안 그대로.
- [ ] **Step 3: PASS + Commit** — `feat(settle-plan): 주문관리 하위탭 정산예정금액 화면`

---

### Task 8: 사이드바 메뉴 + 마이그레이션

**Files:**
- Modify: `프로그램/_시스템/webapp/routes/api_sidebar.py` (28-65 `_ITEM_DEFS` · 74 `_STAGE_SPEC` · 마이그레이션 함수 · `_load()` 443 근처)
- Test: `프로그램/_시스템/tests/catalog/test_sidebar_inject.py` 에 케이스 추가

- [ ] **Step 1: Test** — 저장본(구 레이아웃 dict)에 `_migrate_settle_plan` 적용 시 s_order 분류에 `i_settle_plan` 이 생기고, 재적용은 False(멱등).
- [ ] **Step 2: 구현**

```python
# _ITEM_DEFS 에:
    'i_settle_plan': {'emoji': '💰', 'name': '정산예정금액',
                      'url': '/orders/?tab=settle_plan',
                      'active_key': 'orders_settle_plan'},
# _STAGE_SPEC 74행: ['i_orders', 'i_ship', 'i_cs', 'i_settle_plan']

def _migrate_settle_plan(layout: dict) -> bool:
    """[2026-08-06] 「💰 정산예정금액」 메뉴 — 주문 관리 분류에 추가(1회, idempotent).
    🔴 스펙만 고치면 라이브에 안 나온다 — 서버는 저장본을 쓴다(_migrate_notion_report 선례)."""
    if _has_item_id(layout, 'i_settle_plan'):
        return False
    for st in (layout.get('stages') or []):
        if st.get('id') == 's_order':
            st['items'] = list(st.get('items') or []) + [_item('i_settle_plan')]
            return True
    layout['standalone'] = list(layout.get('standalone') or []) + [_item('i_settle_plan')]
    return True

# _load() 의 _mig9 다음:
        _mig10 = _migrate_settle_plan(data)   # [2026-08-06] 정산예정금액 메뉴(1회)
        if _mig1 or ... or _mig9 or _mig10:
```

- [ ] **Step 3: PASS + Commit** — `feat(settle-plan): 사이드바 주문관리에 정산예정금액 메뉴(+저장본 마이그레이션)`

---

### Task 9: 마무리 검증·배포·백필

- [ ] **Step 1:** 전체 회귀 `python -m pytest tests/ -x -q` (origin/main 기존 실패 목록은 `reference_pytest_preexisting_failures` 와 대조해 신규 실패만 판정)
- [ ] **Step 2:** CSS/디자인 게이트 로컬 실행(check_design_tokens 등 CI 게이트 스크립트 있으면 선실행 — 줄 단위 차단 전례)
- [ ] **Step 3:** PR 생성 → CI 초록 → 머지(🔴 **머지 실제 확인** — CI 통과≠머지·감시 죽음 3회 전례) → 배포 완료 확인(🔴 배포 경합: 먼저 시작한 run 이 늦게 끝나며 덮는지 run 시각 확인)
- [ ] **Step 4:** 라이브 백필 — `POST /orders/settlement-sweep/run` 을 마켓별 넓은 창으로 1회(기존 real 행에 날짜 백필). 결과 updated 수 기록.
- [ ] **Step 5:** 라이브 실브라우저 검증(/ui-verify) — 탭 진입·KPI·본표·드릴다운·규칙표 저장 왕복·마진계산기 총액 교차 대조. 7섹션 보고.

## Self-Review 결과
- 스펙 §2(4부류)=Task 2 classify · §3(날짜 우선순위)=Task 2-4 · §3 빠른정산=Task 1+2 · §3 실측검증=Task 5 calibration · §4(금액 재사용)=Task 2 `_settlement_for` · §5(축2·단위3·드릴·3칸)=Task 5+7 · §6(배선)=Task 7+8 · §7(검증)=각 Task 테스트+Task 9. 누락 없음.
- placeholder 없음(모든 코드 스텝에 실코드/정확한 수정 위치). 타입 일치(payout_events 반환 형식·rules 키 명칭 전 Task 동일).
