# -*- coding: utf-8 -*-
"""빠른정산 선인출 장부 — 「이미 통장에 들어온 돈」을 회차 단위로 기억한다.

🔴 왜 (2026-08-06 사장님 지시: "미리 받은 건 나중에 또 받으면 중복이니 확실하게 해줘")
   우리 정산예정금액 화면은 **주문별 정산액**을 쓴다. 빠른정산(셀러월렛)으로 미리 인출해도
   이 금액은 **그대로 남는다** — 즉 이미 받은 돈이 「앞으로 받을 돈」에 계속 서 있다.
   Wing 실측(세소 6월): 정산대상액 11,081,786 중 **2,916,626 을 7/14 에 이미 인출**했고
   회차에서 공제돼 통장 입금은 300,756 뿐이었다.

★ 쿠팡이 전용 필드를 안 주므로 회차의 공제금액에서 역산한다
  (shared/platforms/coupang/settlements.fast_withdrawn).
★ 회차 단위 금액이라 **주문 한 건 한 건에 나눠 붙일 수 없다.** 그래서 주문 금액은 손대지 않고
  (금액 불가침 규약), 화면에서 「이미 인출한 몫」을 따로 세워 총액에서 뺀다.
★ 상태 파일은 state_store 경유 — 컨테이너 data/ 는 배포마다 사라진다(CLAUDE.md).
"""
from __future__ import annotations

import json

from shared.state_store import state_path

_FILENAME = "settle_fast_withdraw.json"


def _path() -> str:
    return state_path(_FILENAME)


def _key(r: dict) -> str:
    """회차 신원 = 마켓|계정|인식구간|지급일|유형. 다시 훑어도 겹쳐 쌓이지 않게."""
    return "|".join(str(r.get(k) or "") for k in
                    ("market", "account", "from", "to", "settlementDate", "type"))


def load() -> dict:
    try:
        with open(_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {"rows": []}
    if not isinstance(data, dict) or not isinstance(data.get("rows"), list):
        return {"rows": []}
    return data


def save(data: dict) -> None:
    with open(_path(), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def prune_accounts(market: str, keep: set) -> int:
    """그 마켓에서 **빠른정산 계정이 아닌** 행을 장부에서 지운다. 반환 = 지운 수.

    🔴 왜 필요한가(2026-08-06 라이브) — 인출액은 공제금액에서 **역산**하는지라, 빠른정산을
      안 쓰는 계정의 다른 공제(정산차감·전주채권 등)까지 잡혔다(브랜드마켓(쿠팡) 214만).
      그대로 두면 **받지도 않은 돈**으로 「받을 돈」을 깎는다. 계정 설정이 바뀌어도 여기서 정리된다.
    """
    data = load()
    before = len(data["rows"])
    data["rows"] = [r for r in data["rows"]
                    if r.get("market") != market or (r.get("account") or "") in keep]
    n = before - len(data["rows"])
    if n:
        save(data)
    return n


def record(rows: list) -> int:
    """회차 목록을 장부에 반영(같은 회차는 덮어쓰기). 반환 = 저장된 회차 수.

    인출액 0 인 회차는 담지 않는다 — 빠른정산을 안 쓴 계정까지 장부가 부풀지 않게.
    """
    data = load()
    idx = {_key(r): i for i, r in enumerate(data["rows"])}
    n = 0
    for r in rows or []:
        amt = int(r.get("fastWithdrawn") or 0)
        if amt <= 0:
            continue
        rec = {"market": r.get("market") or "coupang", "account": r.get("account") or "",
               "from": r.get("from"), "to": r.get("to"),
               "settlementDate": r.get("settlementDate"), "type": r.get("type") or "",
               # ★ 회차 지급 상태 — 총액에서 뺄지 말지를 가르는 유일한 근거(summary 참조)
               "status": str(r.get("status") or ""),
               "fastWithdrawn": amt}
        k = _key(rec)
        if k in idx:
            data["rows"][idx[k]] = rec
        else:
            idx[k] = len(data["rows"])
            data["rows"].append(rec)
        n += 1
    save(data)
    return n


def summary(*, since: str = "", until: str = "") -> dict:
    """기간(매출인식일 구간이 걸치는지)으로 추린 선인출 합계 + 계정별 내역.

    기간을 안 주면 장부 전체. 「이 돈은 이미 받으셨다」를 화면에 세우는 데 쓴다.

    🔴🔴 **차감액 ≠ 합계** — 두 번 빼면 자금계획이 거꾸로 쪼그라든다.
      · 지급 완료 회차(DONE) → 그 구간 주문은 이미 「이미 받은 것」이라 총액 **밖**에 있다.
        여기서 또 빼면 이중 차감(`수령완료분` 으로만 보여준다).
      · 미지급 회차(SUBJECT) → 그 구간 주문은 아직 「받을 돈」에 서 있는데 이미 인출했다.
        **이 몫(`차감액`)만** 총 미수령액에서 뺀다.
      · 상태를 모르는 옛 장부는 빼지 않는다 — 근거 없이 깎으면 거짓 안심이 된다.
    """
    rows = load()["rows"]
    picked = []
    for r in rows:
        f, t = str(r.get("from") or ""), str(r.get("to") or "")
        if since and t and t < since:
            continue
        if until and f and f > until:
            continue
        picked.append(r)
    by_acc: dict = {}
    차감, 완료 = 0, 0
    for r in picked:
        amt = int(r.get("fastWithdrawn") or 0)
        st = str(r.get("status") or "")
        if st == "DONE":
            완료 += amt
        elif st:                       # SUBJECT 등 아직 안 준 회차 = 총액에 남아 있는 몫
            차감 += amt
        b = by_acc.setdefault(r.get("account") or "(대표)",
                              {"계정": r.get("account") or "(대표)", "금액": 0, "회차수": 0,
                               "차감액": 0, "최근지급일": ""})
        b["금액"] += amt
        b["회차수"] += 1
        if st and st != "DONE":
            b["차감액"] += amt
        sd = str(r.get("settlementDate") or "")
        if sd > b["최근지급일"]:
            b["최근지급일"] = sd
    계정들 = sorted(by_acc.values(), key=lambda b: -b["금액"])
    return {"합계": sum(b["금액"] for b in 계정들), "계정별": 계정들,
            "차감액": 차감, "수령완료분": 완료, "회차수": len(picked)}
