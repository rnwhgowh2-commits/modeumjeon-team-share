"""v32 — 아이콘 picker 저장소 (인메모리 stub).

다음 세션 (사용자 1·2 결정 후) DB 컬럼 추가 + 영구화 예정.

저장 형식:
    {context: {target_id: {icon, color}}}
        context = 'sidebar' | 'model' | 'color_group' | 'source' | ...
        target_id = 위치별 식별자 (sidebar 메뉴 키 / 모음전 model_code / 색상 code 등)

API:
    set_icon(context, target_id, icon, color)
    get_icon(context, target_id) -> {icon, color} | None
    list_icons() -> 전체 dict
    clear_icon(context, target_id)
"""
from __future__ import annotations

import threading
from typing import Any

_lock = threading.RLock()
_STORE: dict[str, dict[str, dict[str, Any]]] = {}


def set_icon(context: str, target_id: str, icon: str | None, color: str | None) -> None:
    """아이콘 + 색상 저장. icon=None 이면 삭제."""
    with _lock:
        ctx_map = _STORE.setdefault(context, {})
        if icon is None:
            ctx_map.pop(target_id, None)
            if not ctx_map:
                _STORE.pop(context, None)
        else:
            ctx_map[target_id] = {'icon': icon, 'color': color or 'default'}


def get_icon(context: str, target_id: str) -> dict | None:
    with _lock:
        return _STORE.get(context, {}).get(target_id)


def list_icons() -> dict[str, dict[str, dict[str, Any]]]:
    """전체 저장 dict (얕은 copy)."""
    with _lock:
        return {ctx: dict(items) for ctx, items in _STORE.items()}


def clear_icon(context: str, target_id: str) -> None:
    set_icon(context, target_id, None, None)
