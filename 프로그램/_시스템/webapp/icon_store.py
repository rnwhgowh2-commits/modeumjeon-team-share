"""v34.11 — brand 색·아이콘 저장소 (DB 영속화).

이전: data/icon_overrides.json (머신 로컬 파일) — Fly.io 멀티 인스턴스/머신 reset 시 데이터 휘발.
현재: BrandColorOverride 테이블 (Supabase PostgreSQL / SQLite fallback) — 영구 보존.

저장 형식 (API 호환 유지):
    list_icons() →
    {
      context: {
        target_id: {icon, color, bg_color?, fg_color?}
      }
    }

API:
    set_icon(context, target_id, icon, color, bg_color=None, fg_color=None)
    get_icon(context, target_id) -> dict | None
    list_icons() -> dict
    clear_icon(context, target_id)
    migrate_from_json() -> int  # 기존 JSON 데이터를 DB 로 옮김 (멱등)
"""
from __future__ import annotations

import json
import logging
import threading
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from config import PROJECT_ROOT
from shared.db import SessionLocal, engine
from webapp.icon_store_model import BrandColorOverride

_lock = threading.RLock()
_logger = logging.getLogger(__name__)

# 기존 JSON 위치 — startup 시 자동 마이그레이션 후 폐기 (rename .bak)
_LEGACY_JSON_PATH = PROJECT_ROOT / 'data' / 'icon_overrides.json'


def _is_postgres() -> bool:
    return engine.dialect.name == "postgresql"


def set_icon(
    context: str,
    target_id: str,
    icon: str | None,
    color: str | None,
    bg_color: str | None = None,
    fg_color: str | None = None,
) -> None:
    """아이콘/색상 저장. 삭제 규칙은 기존 JSON 방식과 동일.

    - 브랜드 컨텍스트(context='brand'): bg_color/fg_color 모두 None 이면 삭제.
    - 그 외 컨텍스트: icon is None 이면 삭제.
    """
    with _lock:
        is_brand = context == 'brand'
        should_delete = (
            (is_brand and bg_color is None and fg_color is None)
            or (not is_brand and icon is None)
        )
        s = SessionLocal()
        try:
            tid = str(target_id or '')
            row = (
                s.query(BrandColorOverride)
                .filter_by(context=context, target_id=tid)
                .one_or_none()
            )
            if should_delete:
                if row is not None:
                    s.delete(row)
                    s.commit()
                return
            # upsert
            if row is None:
                row = BrandColorOverride(context=context, target_id=tid)
                s.add(row)
            row.icon = icon
            row.color = color or 'default'
            row.bg_color = bg_color
            row.fg_color = fg_color
            s.commit()
        except Exception:
            s.rollback()
            _logger.exception("set_icon failed (context=%s, target_id=%s)", context, target_id)
        finally:
            s.close()


def get_icon(context: str, target_id: str) -> dict | None:
    with _lock:
        s = SessionLocal()
        try:
            row = (
                s.query(BrandColorOverride)
                .filter_by(context=context, target_id=str(target_id or ''))
                .one_or_none()
            )
            if row is None:
                return None
            return _row_to_dict(row)
        finally:
            s.close()


def list_icons() -> dict[str, dict[str, dict[str, Any]]]:
    """전체 저장 dict. API 응답 형식 호환."""
    with _lock:
        s = SessionLocal()
        try:
            rows = s.query(BrandColorOverride).all()
            result: dict[str, dict[str, dict[str, Any]]] = {}
            for r in rows:
                result.setdefault(r.context, {})[r.target_id] = _row_to_dict(r)
            return result
        except Exception:
            _logger.exception("list_icons failed")
            return {}
        finally:
            s.close()


def clear_icon(context: str, target_id: str) -> None:
    set_icon(context, target_id, None, None)


def _row_to_dict(r: BrandColorOverride) -> dict[str, Any]:
    d: dict[str, Any] = {
        'icon': r.icon,
        'color': r.color or 'default',
    }
    if r.bg_color:
        d['bg_color'] = r.bg_color
    if r.fg_color:
        d['fg_color'] = r.fg_color
    return d


def migrate_from_json() -> int:
    """기존 icon_overrides.json 을 DB 로 이전. 멱등 — 같은 키는 update.

    호출 시점: app 시작 시 (init_db 후) 한 번. 마이그레이션 후 JSON 파일은
    .bak.migrated 로 rename 해 두 번 안 읽도록.

    Returns: 이전된 row 수.
    """
    if not _LEGACY_JSON_PATH.exists():
        return 0
    try:
        with open(_LEGACY_JSON_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return 0
    except (json.JSONDecodeError, OSError):
        return 0
    count = 0
    for ctx, target_map in (data or {}).items():
        if not isinstance(target_map, dict):
            continue
        for tid, entry in target_map.items():
            if not isinstance(entry, dict):
                continue
            try:
                set_icon(
                    ctx,
                    str(tid),
                    entry.get('icon'),
                    entry.get('color'),
                    bg_color=entry.get('bg_color'),
                    fg_color=entry.get('fg_color'),
                )
                count += 1
            except Exception:
                _logger.warning("migrate row failed: ctx=%s tid=%s", ctx, tid)
    # 마이그레이션 완료 — 옛 파일을 .bak.migrated 로 이름 변경
    try:
        _LEGACY_JSON_PATH.rename(_LEGACY_JSON_PATH.with_suffix('.json.bak.migrated'))
    except OSError:
        pass
    _logger.info("icon_store: migrated %d rows from legacy JSON to DB", count)
    return count
