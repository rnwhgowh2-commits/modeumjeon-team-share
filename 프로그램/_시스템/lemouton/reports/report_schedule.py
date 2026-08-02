# -*- coding: utf-8 -*-
"""노션 투두 보고 — 발송 시각표.

사장님이 화면에서 **고정 시각을 여러 개** 등록한다(예: 09:30 · 14:00 · 18:00).
같은 시각에 두 번 나가지 않도록 **시각별로 마지막 발송일**을 따로 기록한다
— 하나의 `sent_date` 만 쓰면 그날 첫 발송 뒤 나머지 시각이 전부 막힌다.

저장은 배포를 견디는 폴더(`shared.state_store`). 앱 컨테이너 안 `data/` 는
배포마다 사라져서 시각표가 통째로 초기화된다.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Optional

logger = logging.getLogger(__name__)

_FILE = "notion_todo_schedule.json"
_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")

DEFAULT_TIMES = ["09:30"]

# 테스트에서만 덮어쓴다.
_PATH: Optional[str] = None


def _path() -> str:
    if _PATH:
        return _PATH
    from shared.state_store import state_path

    return state_path(_FILE)


def normalize(raw: str) -> Optional[str]:
    """'9:5' → '09:05'. 형식이 아니면 None (조용히 버리지 않고 호출자가 알린다)."""
    m = _TIME_RE.match((raw or "").strip())
    if not m:
        return None
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def _load() -> dict:
    try:
        with open(_path(), encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("times"), list):
            return data
    except FileNotFoundError:
        pass
    except Exception:  # noqa: BLE001 — 손상 파일이 보고를 영구 차단하지 않게
        logger.exception("시각표 읽기 실패 — 기본값으로 시작")
    return {"times": list(DEFAULT_TIMES), "sent": {}}


def _save(data: dict) -> None:
    path = _path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


def times() -> list[str]:
    """등록된 발송 시각(오름차순)."""
    return sorted(set(_load()["times"]))


def set_times(raw_times: list[str]) -> tuple[list[str], list[str]]:
    """시각표 교체.

    Returns:
        (저장된 시각들, 형식이 틀려 버린 입력들) — 틀린 건 숨기지 않고 돌려준다.
    """
    good, bad = [], []
    for raw in raw_times:
        if not (raw or "").strip():
            continue
        norm = normalize(raw)
        (good.append(norm) if norm else bad.append(raw))
    data = _load()
    data["times"] = sorted(set(good))
    # 없어진 시각의 발송 기록은 같이 지운다(파일이 계속 불어나지 않게).
    data["sent"] = {k: v for k, v in (data.get("sent") or {}).items()
                    if k in data["times"]}
    _save(data)
    return data["times"], bad


def already_sent(slot: str, day: str) -> bool:
    """이 시각의 그날치가 이미 나갔나."""
    return (_load().get("sent") or {}).get(slot) == day


def mark_sent(slot: str, day: str) -> None:
    data = _load()
    data.setdefault("sent", {})[slot] = day
    _save(data)


def status() -> dict:
    data = _load()
    return {"times": sorted(set(data["times"])), "sent": data.get("sent") or {}}
