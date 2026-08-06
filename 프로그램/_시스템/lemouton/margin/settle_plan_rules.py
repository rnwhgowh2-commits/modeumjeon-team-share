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
