# -*- coding: utf-8 -*-
"""노션 투두 변경 이력 — 「언제 무엇이 어떻게 바뀌었나」.

카톡은 200자라 요약만 담긴다. "어제 오후에 뭐가 바뀌었더라"를 나중에 찾으려면
회차마다 변경분을 쌓아둬야 한다. 이 모듈이 그 창고다.

**시각의 출처**
    우리가 관측한 시각(회차 시각)이 아니라 **노션이 블록마다 알려주는
    `last_edited_time`** 을 함께 남긴다. 회차 사이에 바뀐 것이라 관측 시각으로는
    "언제"를 알 수 없지만, 노션 값은 실제로 고쳐진 순간이다.

**파일 형식**
    JSONL(한 줄 = 한 회차). 통째로 읽고 쓰는 JSON 배열은 커질수록 위험하다.
    보관은 `_KEEP_DAYS` 일. 넘으면 오래된 줄부터 버린다(파일 무한 성장 방지).
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import date, datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

_FILE = "notion_todo_history.jsonl"
_KEEP_DAYS = 60
_lock = threading.Lock()

# 테스트에서만 덮어쓴다.
_PATH: Optional[str] = None


def _path() -> str:
    if _PATH:
        return _PATH
    from shared.state_store import state_path

    return state_path(_FILE)


def _seoul_now() -> datetime:
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("Asia/Seoul"))
    except Exception:  # noqa: BLE001
        return datetime.now(timezone(timedelta(hours=9)))


def _fmt_edited(raw: Optional[str]) -> Optional[str]:
    """노션의 UTC ISO 시각을 서울 시각 'MM/DD HH:MM' 으로. 실패하면 원문 유지."""
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        try:
            from zoneinfo import ZoneInfo

            dt = dt.astimezone(ZoneInfo("Asia/Seoul"))
        except Exception:  # noqa: BLE001
            dt = dt.astimezone(timezone(timedelta(hours=9)))
        return dt.strftime("%m/%d %H:%M")
    except Exception:  # noqa: BLE001
        return raw


def build_entries(changes: dict) -> list[dict]:
    """대조 결과를 이력 항목들로 편다.

    편집(edited)은 「전 → 후」를 그대로 남긴다 — 무엇이 어떻게 바뀌었는지가
    핵심이고, 요약만 남기면 나중에 복원할 수 없다.
    """
    out: list[dict] = []
    for kind in ("added", "completed", "reopened", "removed"):
        for t in changes.get(kind) or []:
            out.append({
                "kind": kind,
                "text": t.get("text") or "",
                "weekday": t.get("weekday"),
                "edited_at": _fmt_edited(t.get("last_edited")),
            })
    for e in changes.get("edited") or []:
        out.append({
            "kind": "edited",
            "text": e.get("after") or "",
            "before": e.get("before") or "",
            "after": e.get("after") or "",
            "edited_at": _fmt_edited(e.get("last_edited")),
        })
    return out


def append(*, slot: str, changes: dict, sent: Optional[bool] = None) -> int:
    """한 회차의 변경분을 이력에 추가. 변경이 없으면 아무것도 안 쌓는다.

    Returns:
        쌓은 항목 수.
    """
    entries = build_entries(changes)
    if not entries:
        return 0
    now = _seoul_now()
    row = {
        "at": now.isoformat(),
        "day": now.date().isoformat(),
        "slot": slot,
        "sent": sent,
        "entries": entries,
    }
    with _lock:
        path = _path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        _prune(path)
    return len(entries)


def _prune(path: str) -> None:
    """보관 기간을 넘긴 줄을 버린다. 실패해도 이력 기록을 막지 않는다."""
    try:
        cutoff = (_seoul_now().date() - timedelta(days=_KEEP_DAYS)).isoformat()
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
        kept = []
        for ln in lines:
            try:
                if (json.loads(ln).get("day") or "") >= cutoff:
                    kept.append(ln)
            except Exception:  # noqa: BLE001 — 깨진 줄은 버린다
                continue
        if len(kept) != len(lines):
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.writelines(kept)
            os.replace(tmp, path)
    except FileNotFoundError:
        pass
    except Exception:  # noqa: BLE001
        logger.exception("이력 정리 실패(무시)")


def load(*, days: int = 7, limit: int = 400) -> list[dict]:
    """최근 회차들 — 최신이 앞. 없으면 빈 목록."""
    try:
        with open(_path(), encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        return []
    except Exception:  # noqa: BLE001
        logger.exception("이력 읽기 실패")
        return []

    cutoff = (_seoul_now().date() - timedelta(days=days)).isoformat()
    rows: list[dict] = []
    for ln in reversed(lines):
        try:
            row = json.loads(ln)
        except Exception:  # noqa: BLE001
            continue
        if (row.get("day") or "") < cutoff:
            break
        rows.append(row)
        if len(rows) >= limit:
            break
    return rows


def by_day(*, days: int = 7) -> list[tuple[str, list[dict]]]:
    """날짜별로 묶어서 — 화면이 「8/2 → 회차들」로 그리기 좋게."""
    grouped: dict[str, list[dict]] = {}
    for row in load(days=days):
        grouped.setdefault(row.get("day") or "?", []).append(row)
    return sorted(grouped.items(), reverse=True)


def today_count() -> int:
    """오늘 쌓인 변경 항목 수 — 화면 요약용."""
    today = _seoul_now().date().isoformat()
    return sum(len(r.get("entries") or [])
               for r in load(days=1) if r.get("day") == today)
