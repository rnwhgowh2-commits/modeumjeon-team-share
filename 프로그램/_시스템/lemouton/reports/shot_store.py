# -*- coding: utf-8 -*-
"""노션 요일 칸 캡처 보관소.

사장님 PC 의 크롬 확장이 노션 화면을 잘라 올리면 여기 저장하고, 카카오가 읽어갈
공개 주소로 서빙한다. **서버는 브라우저를 띄우지 않는다** — 이 서버는 램 2GB·1코어라
크롬을 얹으면 2026-07 의 램 고갈 프리즈가 재발한다.

**사진이 없을 때 보고를 막지 않는다.** PC 가 꺼져 있으면 그 회차는 글만 나간다 —
사진은 거들 뿐이고, 못 받는 것보다 글만이라도 받는 게 낫다.
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

_DIRNAME = "notion_shots"
_META = "meta.json"

# 캡처가 이보다 오래됐으면 「오늘 것이 아니다」로 본다. 회차 간격보다 넉넉히.
STALE_MINUTES = 90

# 업로드 상한 — 요일 칸 하나라 이 이상 나올 일이 없다. 넘으면 뭔가 잘못된 것.
MAX_BYTES = 6 * 1024 * 1024

_PATH: Optional[str] = None   # 테스트에서만


def _dir() -> str:
    if _PATH:
        d = _PATH
    else:
        from shared.state_store import state_path

        d = state_path(_DIRNAME)
    os.makedirs(d, exist_ok=True)
    return d


def _seoul_now() -> datetime:
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("Asia/Seoul"))
    except Exception:  # noqa: BLE001
        return datetime.now(timezone(timedelta(hours=9)))


def _meta_path() -> str:
    return os.path.join(_dir(), _META)


def save(png_bytes: bytes, *, weekday: str = "", note: str = "") -> dict:
    """캡처 1장 저장. 파일명은 고정 — 최신 1장만 두면 충분하다.

    Raises:
        ValueError — 빈 데이터 / 상한 초과 / PNG 가 아님
    """
    if not png_bytes:
        raise ValueError("빈 이미지")
    if len(png_bytes) > MAX_BYTES:
        raise ValueError(f"이미지가 너무 큼 ({len(png_bytes)} bytes)")
    if not png_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("PNG 형식이 아님")

    now = _seoul_now()
    # 카카오가 URL 로 읽어가므로 파일명이 바뀌어야 캐시를 안 탄다.
    name = f"shot_{int(time.time())}.png"
    path = os.path.join(_dir(), name)
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(png_bytes)
    os.replace(tmp, path)

    meta = {"file": name, "at": now.isoformat(), "weekday": weekday,
            "note": note, "bytes": len(png_bytes)}
    mtmp = _meta_path() + ".tmp"
    with open(mtmp, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)
    os.replace(mtmp, _meta_path())

    _prune(keep=name)
    clear_request()
    return meta


def _prune(*, keep: str) -> None:
    """최신 1장 + meta 만 남긴다. 볼륨이 캡처로 차오르지 않게."""
    try:
        for f in os.listdir(_dir()):
            if f in (keep, _META) or not f.startswith("shot_"):
                continue
            try:
                os.remove(os.path.join(_dir(), f))
            except OSError:
                pass
    except Exception:  # noqa: BLE001
        logger.exception("캡처 정리 실패(무시)")


def load_meta() -> Optional[dict]:
    try:
        with open(_meta_path(), encoding="utf-8") as f:
            meta = json.load(f)
        return meta if isinstance(meta, dict) else None
    except FileNotFoundError:
        return None
    except Exception:  # noqa: BLE001
        logger.exception("캡처 메타 읽기 실패")
        return None


def path_of(name: str) -> Optional[str]:
    """서빙용 실제 경로. 경로 탈출은 막는다."""
    if not name or "/" in name or "\\" in name or not name.startswith("shot_"):
        return None
    p = os.path.join(_dir(), name)
    return p if os.path.exists(p) else None


def age_minutes() -> Optional[float]:
    meta = load_meta()
    if not meta:
        return None
    try:
        at = datetime.fromisoformat(meta["at"])
        return (_seoul_now() - at).total_seconds() / 60.0
    except Exception:  # noqa: BLE001
        return None


def is_fresh() -> bool:
    """지금 보고에 붙여도 되는 캡처인가."""
    age = age_minutes()
    return age is not None and age <= STALE_MINUTES


def public_url() -> Optional[str]:
    """카카오가 읽어갈 절대 주소. 신선하지 않으면 None(= 글만 보낸다)."""
    meta = load_meta()
    if not meta or not is_fresh():
        return None
    base = (os.environ.get("MOUM_PUBLIC_BASE") or "https://mou-m.com").rstrip("/")
    return f"{base}/reports/notion-todo/shot/{meta['file']}"


# ──────────────────────────────────────────────────────────────
# 「지금 찍어줘」 요청 — 테스트 발송용
# ──────────────────────────────────────────────────────────────
#   평소엔 발송 시각 10분 전에만 찍는다(노션 탭을 여는 일이라 자주 하면 거슬린다).
#   테스트는 그 창을 기다릴 수 없으니, 화면에서 눌러 즉시 찍게 하는 길을 둔다.
_REQ = "capture_request.json"
REQUEST_TTL_MINUTES = 5     # 요청이 오래 남아 엉뚱한 때 찍는 걸 막는다


def _req_path() -> str:
    return os.path.join(_dir(), _REQ)


def request_capture() -> dict:
    """다음 확장 폴링(최대 1분) 때 캡처하라고 표시."""
    meta = {"at": _seoul_now().isoformat()}
    tmp = _req_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)
    os.replace(tmp, _req_path())
    return meta


def clear_request() -> None:
    try:
        os.remove(_req_path())
    except FileNotFoundError:
        pass
    except OSError:
        logger.exception("캡처 요청 해제 실패")


def is_requested() -> bool:
    """유효한 요청이 걸려 있나. 오래된 요청은 스스로 만료된다."""
    try:
        with open(_req_path(), encoding="utf-8") as f:
            at = datetime.fromisoformat(json.load(f)["at"])
    except FileNotFoundError:
        return False
    except Exception:  # noqa: BLE001
        return False
    if (_seoul_now() - at).total_seconds() / 60.0 > REQUEST_TTL_MINUTES:
        clear_request()
        return False
    return True


def status() -> dict:
    meta = load_meta()
    age = age_minutes()
    return {
        "has_shot": bool(meta),
        "file": (meta or {}).get("file"),
        "at": (meta or {}).get("at"),
        "weekday": (meta or {}).get("weekday"),
        "age_minutes": (round(age, 1) if age is not None else None),
        "fresh": is_fresh(),
        "stale_after_minutes": STALE_MINUTES,
        "capture_requested": is_requested(),
    }
