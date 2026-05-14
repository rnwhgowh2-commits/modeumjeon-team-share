"""Playwright storage_state 저장/조회/만료 감지 — 멀티 계정 지원.

설계:
  · 1 (source, account_key) → 1 JSON 파일 (``{auth_dir}/{source}_{account_key}.json``)
  · 동시성 안전: ``filelock`` 으로 다중 프로세스 쓰기 직렬화 + atomic rename
  · 만료 감지: 파일 mtime + ``ttl_days`` 비교
  · 손상된 JSON: 경고 로그 후 ``None`` 반환 (silent corrupt 방지)
  · 누락은 정상 흐름 (None / False / 0) — 예외 X (idempotent)

기존 ``lemouton/sourcing/auth.py`` 의 file-path helper 와는 별개:
  · ``sourcing/auth.py`` 는 V1 시대 단일 함수 + Playwright 부팅 (Phase 2-C 에서 통합 예정)
  · 본 모듈은 V2 ``SourcingAccount`` 를 전제로 한 객체지향 store
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

from filelock import FileLock, Timeout

logger = logging.getLogger(__name__)

# 동시성 락 타임아웃 (초). 30초 안에 이전 쓰기가 끝나지 않으면 명시적 실패.
LOCK_TIMEOUT_SEC = 30


class SessionStoreError(RuntimeError):
    """session_store 공통 베이스."""


class SessionLockTimeoutError(SessionStoreError):
    """다른 프로세스가 락을 너무 오래 잡고 있음 — 명시적 실패."""


class SessionStore:
    """Playwright storage_state 저장소 — 1 인스턴스 = 1 ``auth_dir``.

    Args:
        auth_dir: 세션 JSON 보관 디렉토리. 없으면 자동 생성.
    """

    def __init__(self, auth_dir: str | os.PathLike) -> None:
        self.auth_dir = Path(auth_dir)
        self._ensure_dir()

    # ──────────────────────────────────────────────────────
    #  경로
    # ──────────────────────────────────────────────────────

    def _safe_segment(self, value: str) -> str:
        """경로 안전 문자만 허용 — ``/`` ``\\`` 공백 제거."""
        return value.replace(" ", "_").replace("/", "_").replace("\\", "_")

    def get_session_path(self, source: str, account_key: str = "default") -> Path:
        """``{auth_dir}/{source}_{account_key}.json`` 절대경로 반환."""
        safe_source = self._safe_segment(source)
        safe_account = self._safe_segment(account_key)
        return self.auth_dir / f"{safe_source}_{safe_account}.json"

    def _get_lock_path(self, source: str, account_key: str = "default") -> Path:
        """동시성 락 파일 (filelock 라이브러리 표준 패턴)."""
        return self.get_session_path(source, account_key).with_suffix(".lock")

    def _ensure_dir(self) -> None:
        self.auth_dir.mkdir(parents=True, exist_ok=True)

    # ──────────────────────────────────────────────────────
    #  존재 / 삭제 / 나이
    # ──────────────────────────────────────────────────────

    def has_session(self, source: str, account_key: str = "default") -> bool:
        return self.get_session_path(source, account_key).is_file()

    def delete_session(self, source: str, account_key: str = "default") -> bool:
        """삭제. 누락 시 ``False`` 반환 (예외 X — idempotent)."""
        path = self.get_session_path(source, account_key)
        if not path.exists():
            return False
        try:
            path.unlink()
            logger.info("[session_store] deleted %s/%s", source, account_key)
            return True
        except OSError as e:
            logger.warning("[session_store] delete failed %s/%s: %s", source, account_key, e)
            return False

    def age_days(self, source: str, account_key: str = "default") -> Optional[float]:
        """파일 mtime 기준 경과 일수. 누락 시 ``None``."""
        path = self.get_session_path(source, account_key)
        if not path.is_file():
            return None
        mtime = datetime.fromtimestamp(path.stat().st_mtime)
        return (datetime.now() - mtime).total_seconds() / 86400

    def is_expired(
        self,
        source: str,
        account_key: str = "default",
        ttl_days: float = 30.0,
    ) -> bool:
        """``ttl_days`` 초과 시 ``True``. 누락 세션도 ``True`` (= 재로그인 필요)."""
        age = self.age_days(source, account_key)
        if age is None:
            return True
        return age > ttl_days

    # ──────────────────────────────────────────────────────
    #  저장 — atomic + filelock
    # ──────────────────────────────────────────────────────

    def save_session(
        self,
        source: str,
        account_key: str,
        state: dict,
    ) -> Path:
        """세션 JSON 저장 (atomic — 임시파일 → rename, filelock 으로 직렬화).

        Args:
            source: 소싱처 식별자 (``"musinsa"`` 등)
            account_key: 계정 식별자 (``"default"`` 등)
            state: ``Playwright.context.storage_state()`` 결과 dict

        Returns:
            저장된 파일 경로

        Raises:
            SessionLockTimeoutError: 다른 프로세스 락 ``LOCK_TIMEOUT_SEC`` 초과 시
        """
        self._ensure_dir()
        path = self.get_session_path(source, account_key)
        lock_path = self._get_lock_path(source, account_key)

        try:
            with FileLock(str(lock_path), timeout=LOCK_TIMEOUT_SEC):
                # tempfile → atomic rename (load 가 부분쓰기 본문을 보지 않게)
                fd, tmp_name = tempfile.mkstemp(
                    dir=str(self.auth_dir),
                    prefix=f"{path.stem}.",
                    suffix=".tmp",
                )
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as f:
                        json.dump(state, f, ensure_ascii=False, indent=2)
                    os.replace(tmp_name, path)
                    logger.info(
                        "[session_store] saved %s/%s → %s",
                        source, account_key, path.name,
                    )
                except Exception:
                    # 임시파일 정리 (실패 시)
                    try:
                        os.unlink(tmp_name)
                    except OSError:
                        pass
                    raise
        except Timeout as e:
            raise SessionLockTimeoutError(
                f"[session_store] lock timeout {LOCK_TIMEOUT_SEC}s — "
                f"다른 프로세스가 {source}/{account_key} 세션을 점유 중"
            ) from e

        return path

    # ──────────────────────────────────────────────────────
    #  조회 — 손상 JSON 안전
    # ──────────────────────────────────────────────────────

    def load_session(
        self,
        source: str,
        account_key: str = "default",
    ) -> Optional[dict]:
        """세션 JSON 로드. 누락 또는 손상 시 ``None``."""
        path = self.get_session_path(source, account_key)
        if not path.is_file():
            return None
        try:
            with path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            logger.warning(
                "[session_store] corrupt session %s/%s — JSON decode error: %s",
                source, account_key, e,
            )
            return None
        except OSError as e:
            logger.warning(
                "[session_store] read error %s/%s — %s",
                source, account_key, e,
            )
            return None
