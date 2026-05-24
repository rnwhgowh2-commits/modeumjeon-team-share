"""v32 — 아이콘 picker 저장소 (JSON 파일 영속화).

저장 위치: data/icon_overrides.json (단일 사용자 시스템 — JSON 1파일).
api_sidebar.py 의 sidebar_layout.json 과 동일한 패턴 — 매 호출 시 디스크에서
fresh 로드(작은 파일, 멀티워커에서도 안전), atomic tmp-replace 쓰기.

저장 형식:
    {context: {target_id: {icon, color, bg_color, fg_color}}}
        context = 'mode' | 'sidebar' | 'model' | 'color_group' | 'source' | 'brand' | ...
        target_id = 위치별 식별자 (모드 키 / sidebar 메뉴 키 / 모음전 model_code 등)
        bg_color, fg_color — v34 추가. 바탕색/글자색 hex (예: '#FF5500'). 기존 color
            (palette key) 와 공존. brand 컨텍스트에서는 두 필드만 사용.

API:
    set_icon(context, target_id, icon, color, bg_color=None, fg_color=None)
    get_icon(context, target_id) -> {icon, color, bg_color?, fg_color?} | None
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


def set_icon(
    context: str,
    target_id: str,
    icon: str | None,
    color: str | None,
    bg_color: str | None = None,
    fg_color: str | None = None,
) -> None:
    """아이콘 + 색상 저장. 디스크에 영속화.

    삭제 규칙:
      - 브랜드 컨텍스트(context='brand'): icon 파라미터 없이 호출되므로
        bg_color/fg_color 모두 None 인 경우만 삭제.
      - 그 외 컨텍스트: 기존 동작 — icon is None 이면 삭제.
    """
    with _lock:
        store = _load()
        is_brand = context == 'brand'
        should_delete = (
            (is_brand and bg_color is None and fg_color is None)
            or (not is_brand and icon is None)
        )
        if should_delete:
            ctx_map = store.get(context)
            if ctx_map is not None:
                ctx_map.pop(target_id, None)
                if not ctx_map:
                    store.pop(context, None)
        else:
            entry: dict[str, Any] = {
                'icon': icon,
                'color': color or 'default',
            }
            if bg_color:
                entry['bg_color'] = bg_color
            if fg_color:
                entry['fg_color'] = fg_color
            store.setdefault(context, {})[target_id] = entry
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
