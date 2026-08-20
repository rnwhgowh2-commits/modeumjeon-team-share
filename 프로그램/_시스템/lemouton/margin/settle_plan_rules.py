"""정산예정금액 탭 — 마켓별 정산주기 규칙표 (편집 가능한 데이터).

🔴 왜 데이터인가 — 마켓 정산 정책은 바뀐다. 하드코딩하면 정책이 바뀔 때 표가 통째로
   틀리고 배포 없인 못 고친다. 초기값은 마켓 문서·통념 기반 **추정 시작점**이고,
   화면(규칙표 패널)에서 보고 고친다. 실지급일 이력과의 오차는 API 가 역산해 보여준다
   (webapp/routes/orders.py 의 /orders/api/settle-plan/rules).

★ 지급예정일 결정에서 이 규칙은 **실값이 없을 때만** 쓰인다(settle_plan.payout_events).
  실값 = 쿠팡 settlementDate·스스 settleExpectDate·ESM SettleExpectDate·11번가 stlPlnDy.
  롯데온만 실값이 없어 항상 이 규칙으로 추정한다.
★ fast_accounts = 빠른정산 사용 계정 목록 {market: [계정명…]} — 사장님이 화면에서 켠다
  (스스 1·쿠팡 1 계정 사용 중, 2026-08-06 확정).
★ 상태 파일은 state_store 경유 — 컨테이너 data/ 는 배포마다 사라진다(CLAUDE.md).
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
# order_to_delivered_days: 주문일→배송완료 추정 일수 — status_at(관측시각)이 없는 옛
#   저장분의 폴백 기준점에 쓴다(2026-08-06 라이브 6,084건이 근거 부재로 「미정」이었다)
DEFAULT_RULES: dict = {
    "markets": {
        "coupang":    {"auto_confirm_days": 7, "transit_days": 2, "cycle_days": 15,
                       "fast_cycle_days": 2, "split_ratio": 0.7, "split_rest_days": 30,
                       "order_to_delivered_days": 5},
        "smartstore": {"auto_confirm_days": 8, "transit_days": 2, "cycle_days": 1,
                       "fast_cycle_days": 1, "split_ratio": 1.0, "split_rest_days": 0,
                       "order_to_delivered_days": 5},
        "lotteon":    {"auto_confirm_days": 7, "transit_days": 2, "cycle_days": 7,
                       "fast_cycle_days": 0, "split_ratio": 1.0, "split_rest_days": 0,
                       "order_to_delivered_days": 5},
        "eleven11":   {"auto_confirm_days": 7, "transit_days": 2, "cycle_days": 3,
                       "fast_cycle_days": 0, "split_ratio": 1.0, "split_rest_days": 0,
                       "order_to_delivered_days": 5},
        "auction":    {"auto_confirm_days": 8, "transit_days": 2, "cycle_days": 1,
                       "fast_cycle_days": 0, "split_ratio": 1.0, "split_rest_days": 0,
                       "order_to_delivered_days": 5},
        "gmarket":    {"auto_confirm_days": 8, "transit_days": 2, "cycle_days": 1,
                       "fast_cycle_days": 0, "split_ratio": 1.0, "split_rest_days": 0,
                       "order_to_delivered_days": 5},
    },
    "fast_accounts": {},
    # 셀러월렛 **미인출 잔액** {market: {account: {"금액": int, "적은날": "YYYY-MM-DD"}}}
    # 🔴 이미 사장님 돈인데 아직 안 찾아간 돈이다. 인출해야 회차에서 공제되므로 그 전까지는
    #   주문별 정산액에 그대로 남아 「앞으로 받을 돈」이 그만큼 부푼다(Wing 실측 세소 8,112,876).
    #   셀러월렛은 별도 시스템이라 읽을 API 가 없어 **사장님이 화면에서 직접 적는 값**이다.
    "wallet_balance": {},
    # 예정일이 이만큼 지나면 「이미 받았을 것(확인 불가)」로 보고 총액에서 뺀다.
    "assume_paid_after_days": 30,
}


def _rules_path() -> str:
    return state_path(_FILENAME)


def load_rules() -> dict:
    """저장본 로드. 없거나 깨졌으면 기본값.

    마켓·키 누락은 기본값으로 채우고 모르는 키는 버린다 — 부분 저장·옛 저장본이
    새 코드의 필수 키를 굶기지 않게(규칙표는 자금 계산의 입력이라 결손 = 계산 불능).
    """
    data: dict = {}
    try:
        with open(_rules_path(), "r", encoding="utf-8") as f:
            data = json.load(f) or {}
    except (OSError, json.JSONDecodeError):
        data = {}
    out = {"markets": {}, "fast_accounts": dict(data.get("fast_accounts") or {}),
           "assume_paid_after_days": DEFAULT_RULES["assume_paid_after_days"]}
    try:
        v = int(data.get("assume_paid_after_days"))
        if 0 < v <= 365:
            out["assume_paid_after_days"] = v
    except (TypeError, ValueError):
        pass
    saved = data.get("markets") or {}
    for mk, base in DEFAULT_RULES["markets"].items():
        merged = dict(base)
        merged.update({k: v for k, v in (saved.get(mk) or {}).items() if k in base})
        out["markets"][mk] = merged
    out["wallet_balance"] = _clean_wallet(data.get("wallet_balance"))
    return out


def _clean_wallet(raw) -> dict:
    """셀러월렛 잔액 정제 — 아는 마켓·양수 금액만 남긴다.

    🔴 이 값은 총 받을 돈에서 **빼는** 데 쓰인다. 이상한 값을 조용히 반영하면 자금계획이
       근거 없이 줄어든다 → 숫자가 아니거나 음수면 **버린다**(없는 셈).
    """
    out: dict = {}
    for mk, accs in (raw or {}).items():
        if mk not in DEFAULT_RULES["markets"] or not isinstance(accs, dict):
            continue
        keep = {}
        for acc, ent in accs.items():
            if not isinstance(ent, dict):
                continue
            try:
                amt = int(ent.get("금액"))
            except (TypeError, ValueError):
                continue
            if amt <= 0:
                continue
            keep[acc] = {"금액": amt, "적은날": str(ent.get("적은날") or "")[:10]}
        if keep:
            out[mk] = keep
    return out


def wallet_summary(rules: dict) -> dict:
    """셀러월렛 잔액 합계 + 계정별(큰 금액부터). 「이미 내 돈」 카드에 쓴다."""
    rows = []
    for mk, accs in (rules or {}).get("wallet_balance", {}).items():
        for acc, ent in accs.items():
            rows.append({"마켓": mk, "계정": acc, "금액": int(ent.get("금액") or 0),
                         "적은날": ent.get("적은날") or ""})
    rows.sort(key=lambda r: -r["금액"])
    return {"합계": sum(r["금액"] for r in rows), "계정별": rows}


def save_rules(rules: dict) -> None:
    with open(_rules_path(), "w", encoding="utf-8") as f:
        json.dump(rules, f, ensure_ascii=False, indent=1)
