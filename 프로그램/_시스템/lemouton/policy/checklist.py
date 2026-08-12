# -*- coding: utf-8 -*-
"""개발 체크리스트 — 셀 판정 (순수 함수, Flask 의존 없음).

🔴 여기 WIRED 는 화면 6상태 중 하나이고, required.WIRED 는 배선 2상태 중 하나다.
  문자열이 우연히 같을 뿐 다른 개념이다 — 비교는 반드시 심볼로 한다.
"""
from __future__ import annotations

import json
import os

_DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                     "webapp", "data")


def load_columns(name: str = "dev_checklist_columns.json") -> list[dict]:
    with open(os.path.join(_DATA, name), encoding="utf-8") as f:
        return json.load(f)["columns"]


from lemouton.policy import required as _req

#: 칸 상태 — 화면 표시와 뜻
NA = "na"                  # ➖ 해당없음    : 엑셀이 비었거나 「-」
IMPOSSIBLE = "impossible"  # ⚫ 불가        : 엑셀이 「X」 (마켓에 기능 자체가 없음)
TODO = "todo"              # ⬜ 미착수      : 우리 칸이 없거나 마켓 근거를 못 찾음
STORED = "stored"          # 🟡 저장만 됨   : 칸은 있는데 보내는 코드가 없음
WIRED = "wired"            # 🟢 나감(미검증) : 보내지만 실계정 확인 전
DONE = "done"              # 🟢 검증완료    : 보내고 실계정으로 확인함

_BLANK = ("", "-")


def _spec(market: str, col: dict) -> str:
    """그 마켓의 엑셀 메모. 모르는 마켓 이름이면 **터뜨린다.**

    🔴 조용히 빈 문자열로 떨어뜨리면 「모른다」가 「해당없음」으로 둔갑한다.
      오타 난 마켓 키가 화면에 ➖ 로 뜨면 아무도 못 알아챈다.
    """
    specs = col.get("specs") or {}
    if market not in specs:
        raise KeyError(
            f"「{col.get('name', '?')}」 열에 마켓 {market!r} 가 없습니다 — "
            f"있는 마켓: {', '.join(sorted(specs)) or '(없음)'}")
    return (specs[market] or "").strip()


def cell_state(market: str, col: dict, marks: dict | None = None) -> str:
    """그 칸의 상태 하나. 판정 순서를 바꾸지 말 것 — 앞 조건이 뒤를 가린다."""
    spec = _spec(market, col)
    if spec in _BLANK:
        return NA
    if spec.upper() == "X":
        return IMPOSSIBLE
    item = col.get("item")
    if not item:
        return TODO                       # 프로그램에 담을 칸이 아직 없다
    status, _evidence, _note = _req.status_of(market, item)
    if status == _req.UNKNOWN:
        return TODO                       # 「없다」가 아니라 「모른다」 — 지어내지 않는다
    if _req.wiring_of(item)[0] != _req.WIRED:
        return STORED                     # 채워도 안 나간다
    key = f"{market}:{col['col']}"
    if ((marks or {}).get(key) or {}).get("verified"):
        return DONE
    return WIRED


def conflict_of(market: str, col: dict) -> str:
    """우리 기준과 마켓 문서가 어긋나는가. 기계 판정만 — 추측하지 않는다.

    CONDITIONAL(「~인 경우 필수」)은 **일부러 안 잡는다** — 조건이 맞는지는 기계가 못 정한다.
    """
    item = col.get("item")
    if not item:
        return ""
    spec = _spec(market, col)
    status, _e, _n = _req.status_of(market, item)
    if spec in _BLANK or spec.upper() == "X":
        if status == _req.REQUIRED:
            return "마켓 문서는 [필수]라는데 우리는 안 쓰기로 돼 있습니다"
    return ""


MARKETS = [("coupang", "쿠팡"), ("smartstore", "스마트스토어"), ("lotteon", "롯데온"),
           ("eleven11", "11번가"), ("auction", "옥션"), ("gmarket", "G마켓")]


def load_marks() -> dict:
    """사람이 단 값. 파일이 없으면 빈 것으로 본다(아직 아무도 안 달았다는 뜻)."""
    path = os.path.join(_DATA, "dev_checklist_marks.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f).get("marks") or {}


def build(columns_file: str = "dev_checklist_columns.json") -> dict:
    """화면이 그대로 그릴 수 있는 한 벌."""
    cols = load_columns(columns_file)
    marks = load_marks()
    cells, rows = {}, []
    for market, label in MARKETS:
        counts = {k: 0 for k in (NA, IMPOSSIBLE, TODO, STORED, WIRED, DONE)}
        for col in cols:
            state = cell_state(market, col, marks)
            counts[state] += 1
            item = col.get("item")
            status, evidence, note = (_req.status_of(market, item) if item
                                      else (_req.UNKNOWN, "", "프로그램에 담을 칸이 아직 없습니다"))
            wiring = _req.wiring_of(item) if item else ("", "")
            cells[f"{market}:{col['col']}"] = {
                "state": state,
                "spec": _spec(market, col),
                "required": status,
                "evidence": evidence,
                "note": note,
                "wiring": wiring[0],
                "wiring_note": wiring[1],
                "api": _req.SOURCE_API.get(market, ""),
                "conflict": conflict_of(market, col),
                "verified": ((marks.get(f"{market}:{col['col']}") or {}).get("verified") or ""),
            }
        counts["total"] = len(cols) - counts[NA]
        rows.append({"market": market, "label": label, "counts": counts})
    return {"columns": cols, "rows": rows, "cells": cells,
            "drift": drift(marks, columns_file)}


def drift(marks: dict, columns_file: str = "dev_checklist_columns.json") -> list[str]:
    """손으로 단 값이 코드와 어긋나면 사람 말로 돌려준다. 없으면 빈 목록.

    🔴 조용한 통과 금지 — 「나가지도 않는 값에 검증완료가 달린 것」이 가장 위험하다.
      그 칸은 화면에서 초록으로 보이지만 마켓에는 아무것도 안 갔다.
    """
    by_col = {c["col"]: c for c in load_columns(columns_file)}
    out = []
    for key, mark in (marks or {}).items():
        if not (mark or {}).get("verified"):
            continue
        market, _, raw = key.partition(":")
        try:
            col = by_col[int(raw)]
        except (ValueError, KeyError):
            out.append(f"손보정에 없는 열 번호가 있습니다: {key}")
            continue
        item = col.get("item")
        if not item:
            out.append(f"「{col['name']}」({market}) 는 프로그램에 담을 칸이 아직 없는데 "
                       f"검증완료로 표시돼 있습니다")
        elif _req.wiring_of(item)[0] != _req.WIRED:
            out.append(f"「{col['name']}」({market}) 는 저장만 되고 마켓으로 나가지 않는데 "
                       f"검증완료로 표시돼 있습니다")
    return out
