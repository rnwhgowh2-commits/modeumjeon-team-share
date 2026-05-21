"""v32 — 아이콘 picker 저장소 (JSON 파일 영속화).

저장 위치: data/icon_overrides.json (단일 사용자 시스템 — JSON 1파일).
api_sidebar.py 의 sidebar_layout.json 과 동일한 패턴 — 매 호출 시 디스크에서
fresh 로드(작은 파일, 멀티워커에서도 안전), atomic tmp-replace 쓰기.

저장 형식:
    {context: {target_id: {icon, color}}}
        context = 'mode' | 'sidebar' | 'model' | 'color_group' | 'source' | ...
        target_id = 위치별 식별자 (모드 키 / sidebar 메뉴 키 / 모음전 model_code 등)

API:
    set_icon(context, target_id, icon, color)
    get_icon(context, target_id) -> {icon, color} | None
    list_icons() -> 전체 dict
    clear_icon(context, target_id)
"""
from __future__ import annotations

import json
import threading
from typing import Any

from config import PROJECT_ROOT

_lock = threading.RLock()
_STORE_PATH = PROJECT_ROOT / 'data' / 'icon_overrides.json'


def _load() -> dict[str, dict[str, dict[str, Any]]]:
    """파일에서 fresh 로드. 없거나 깨졌으면 빈 dict."""
    if not _STORE_PATH.exists():
        return {}
    try:
        with open(_STORE_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save(store: dict) -> None:
    """atomic tmp-replace 쓰기."""
    _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _STORE_PATH.with_suffix('.json.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(store, f, ensure_ascii=False, indent=2)
    tmp.replace(_STORE_PATH)


def set_icon(context: str, target_id: str, icon: str | None, color: str | None) -> None:
    """아이콘 + 색상 저장. icon=None 이면 삭제. 디스크에 영속화."""
    with _lock:
        store = _load()
        if icon is None:
            ctx_map = store.get(context)
            if ctx_map is not None:
                ctx_map.pop(target_id, None)
                if not ctx_map:
                    store.pop(context, None)
        else:
            store.setdefault(context, {})[target_id] = {
                'icon': icon, 'color': color or 'default',
            }
        _save(store)


def get_icon(context: str, target_id: str) -> dict | None:
    with _lock:
        return _load().get(context, {}).get(target_id)


def list_icons() -> dict[str, dict[str, dict[str, Any]]]:
    """전체 저장 dict."""
    with _lock:
        return _load()


def clear_icon(context: str, target_id: str) -> None:
    set_icon(context, target_id, None, None)
