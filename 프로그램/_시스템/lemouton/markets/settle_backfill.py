# -*- coding: utf-8 -*-
"""정산 「깊은 백필」 — 평소 창 밖에서 확정된 정산을 하루 한 마켓씩 데려온다.

🔴 왜 필요한가(2026-08-07 라이브에서 드러남) — 평소 정산 스윕은 최근 45~75일만 본다.
   그 창이 닫힌 뒤 확정된 정산은 **영영 안 들어와** 「이미 받았을 것(확인 불가)」로 쌓인다.
   실측: 확인 불가 **1억 5,242만원**(쿠팡 1억 694만·11번가 1,082만·G마켓 697만·옥션 156만).
   손으로 과거를 넓게 한 번 훑으니 **1억 5,433만이 「확인」으로 넘어갔고**, 덤으로
   옥션 정산율 경고(3.7% vs 15%)도 사라졌다(정산이 덜 채워져 과대로 보이던 것).
   → 그 손 작업을 자동으로. 안 하면 **시간이 지나며 똑같이 다시 쌓인다.**

★ 하루 **한 마켓씩 순환**한다. 한 틱에 전 마켓을 훑으면 무겁다 — 특히 스마트스토어는
  하루씩 조회라 180일이면 계정당 180콜이다. 6마켓이면 6일에 한 바퀴인데, 과거 정산은
  이미 확정된 값이라 그 주기로 충분하다.
★ 상태는 state_store 경유 — 컨테이너 data/ 는 배포마다 사라진다(CLAUDE.md).
"""
from __future__ import annotations

import datetime as _dt
import json

from shared.state_store import state_path

_FILENAME = "settle_deep_backfill.json"

#: 과거 이만큼까지 훑는다. 정산은 구매확정 뒤 최대 2달가량 걸려 확정되므로 넉넉히.
DEEP_DAYS = 180

#: 순환 순서 — 무거운 스마트스토어를 끝에 둬 다른 마켓이 먼저 회복되게.
MARKETS = ("coupang", "eleven11", "auction", "gmarket", "lotteon", "smartstore")


def _path() -> str:
    return state_path(_FILENAME)


def load() -> dict:
    try:
        with open(_path(), "r", encoding="utf-8") as f:
            d = json.load(f) or {}
    except (OSError, json.JSONDecodeError):
        d = {}
    return {"last_date": str(d.get("last_date") or ""),
            "idx": int(d.get("idx") or 0) if str(d.get("idx") or "0").isdigit() else 0,
            "history": list(d.get("history") or [])[-30:]}


def save(d: dict) -> None:
    with open(_path(), "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)


def due_market(*, today: _dt.date, supported=None) -> str | None:
    """오늘 훑을 마켓 하나. 오늘 이미 돌았으면 None.

    supported 를 주면 그 안에 있는 마켓만 고른다(연동 안 된 마켓을 헛되이 부르지 않게).
    """
    st = load()
    if st["last_date"] == today.isoformat():
        return None                      # 하루 1회
    pool = [m for m in MARKETS if supported is None or m in supported]
    if not pool:
        return None
    return pool[st["idx"] % len(pool)]


def mark_done(market: str, *, today: _dt.date, stat: dict | None = None) -> None:
    """오늘 몫을 끝냈다고 적는다(다음 마켓으로 한 칸 이동).

    실패해도 적는다 — 같은 마켓에서 매 틱 재시도하며 다른 마켓을 굶기지 않게.
    결과는 history 에 남겨 「돌긴 도는가」를 화면·로그에서 볼 수 있게 한다.
    """
    st = load()
    st["last_date"] = today.isoformat()
    st["idx"] = (st["idx"] + 1) % max(1, len(MARKETS))
    st["history"] = (st.get("history") or [])[-29:] + [{
        "date": today.isoformat(), "market": market,
        "updated": int((stat or {}).get("updated") or 0),
        "settle_rows": int((stat or {}).get("settle_rows") or 0),
        "errors": len((stat or {}).get("errors") or []),
    }]
    save(st)


def window(*, today: _dt.date, days: int = DEEP_DAYS) -> tuple[_dt.datetime, _dt.datetime]:
    """[오늘−days, 오늘] — 각 스윕이 자기 규칙대로 31일 등으로 쪼갠다."""
    kst = _dt.timezone(_dt.timedelta(hours=9))
    end = _dt.datetime.combine(today, _dt.time(0, 0), tzinfo=kst)
    return end - _dt.timedelta(days=days), end
