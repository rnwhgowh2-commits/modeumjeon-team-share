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

# [perf 2026-05-29] list_icons() 인메모리 TTL 캐시.
#   brand_color_overrides 는 거의 안 바뀌는데 매 페이지(컨텍스트 프로세서)에서
#   여러 번 조회돼 전 페이지 공통 오버헤드였음. 60초 TTL 캐시로 쿼리 제거.
#   set_icon/clear_icon 시 즉시 무효화(이 워커 한정). 워커별 캐시라 다른 워커는
#   최대 60초 staleness — brand 색 변경 빈도상 무해.
import time as _time
_icons_cache = None
_icons_cache_ts = 0.0
_ICONS_CACHE_TTL = 60.0


def _invalidate_icons_cache() -> None:
    global _icons_cache
    _icons_cache = None

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
    letter: str | None = None,
) -> None:
    """아이콘/색상/텍스트 저장. 삭제 규칙은 기존 JSON 방식과 동일.

    - 브랜드 컨텍스트(context='brand'): bg_color/fg_color/letter 모두 None 이면 삭제.
    - 그 외 컨텍스트: icon is None 이면 삭제.
    """
    with _lock:
        _invalidate_icons_cache()  # [perf] 쓰기 시 캐시 무효화 (이 워커)
        is_brand = context == 'brand'
        should_delete = (
            (is_brand and bg_color is None and fg_color is None and (letter is None or letter == ''))
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
            row.letter = (letter[:16] if letter else None)
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
    """전체 저장 dict. API 응답 형식 호환. [perf] 60초 TTL 캐시."""
    global _icons_cache, _icons_cache_ts
    with _lock:
        now = _time.monotonic()
        if _icons_cache is not None and (now - _icons_cache_ts) < _ICONS_CACHE_TTL:
            return _icons_cache
        s = SessionLocal()
        try:
            rows = s.query(BrandColorOverride).all()
            result: dict[str, dict[str, dict[str, Any]]] = {}
            for r in rows:
                result.setdefault(r.context, {})[r.target_id] = _row_to_dict(r)
            _icons_cache = result
            _icons_cache_ts = now
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
    if getattr(r, 'letter', None):
        d['letter'] = r.letter
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
                    letter=entry.get('letter'),
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
