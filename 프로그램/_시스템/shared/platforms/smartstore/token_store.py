# -*- coding: utf-8 -*-
"""
스마트스토어 access_token 파일 캐시 + 파일락 관리.

책임:
- 캐시 파일에 {access_token, issued_at, expires_at} JSON 저장
- 만료 margin 이내면 재발급 (portalocker 로 다중 프로세스 직렬화)
- invalidate() 로 401 수신 후 캐시 삭제

파일 포맷:
    {"access_token": "...", "expires_at": 1745209800, "issued_at": 1745199000}
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Optional

import portalocker

from shared.platforms.smartstore.auth import (
    TokenInfo, SmartStoreAuthError, request_new_token,
)

logger = logging.getLogger(__name__)


class TokenStore:
    """파일 기반 토큰 저장소. 프로세스·스레드 간 안전."""

    def __init__(self, client_id: str, client_secret: str, endpoint_url: str,
                 cache_path: str, lock_path: str,
                 refresh_margin_sec: int = 600,
                 lock_acquire_timeout_sec: int = 10):
        self._cid = client_id
        self._secret = client_secret
        self._endpoint = endpoint_url
        self._cache_path = Path(cache_path)
        self._lock_path  = Path(lock_path)
        self._refresh_margin_sec = refresh_margin_sec
        self._lock_timeout = lock_acquire_timeout_sec
        self._thread_lock = threading.Lock()
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)

    def get_valid_token(self) -> str:
        """만료 margin 이내가 아니면 캐시 반환, 아니면 재발급."""
        # 1. 캐시 읽기 (락 없이)
        info = self._read_cache()
        if info and self._is_fresh(info):
            return info.access_token

        # 2. 재발급 — thread 내 직렬화 + 프로세스 간 파일락
        with self._thread_lock:
            # thread lock 통과 후 다시 한 번 확인 (다른 스레드가 방금 갱신했을 수 있음)
            info = self._read_cache()
            if info and self._is_fresh(info):
                return info.access_token
            return self._issue_and_write_with_lock().access_token

    def invalidate(self) -> None:
        """401 등 수신 시 캐시 삭제."""
        try:
            if self._cache_path.exists():
                self._cache_path.unlink()
        except OSError as e:
            logger.warning("캐시 삭제 실패: %s", e)

    # ── 내부 ─────────────────────────────────────────
    def _read_cache(self) -> Optional[TokenInfo]:
        if not self._cache_path.exists():
            return None
        try:
            data = json.loads(self._cache_path.read_text(encoding="utf-8"))
            # ★ 다른 계정(client_id)의 토큰은 절대 쓰지 않는다.
            #   캐시를 공유하면 먼저 토큰을 받은 스토어의 자격으로 다른 스토어를 조회하게 되어
            #   '다른 가게 주문이 통째로 누락'된다(발송 누락 = 금전 손실).
            #   client_id 가 없는 옛 캐시도 신뢰하지 않는다(재발급 유도).
            if data.get("client_id") != self._cid:
                logger.warning("[smartstore] 다른 계정의 토큰 캐시 — 무시하고 재발급")
                return None
            return TokenInfo(
                access_token=data["access_token"],
                issued_at=int(data["issued_at"]),
                expires_at=int(data["expires_at"]),
            )
        except (OSError, ValueError, KeyError) as e:
            logger.warning("캐시 파싱 실패 — 재발급 유도: %s", e)
            return None

    def _is_fresh(self, info: TokenInfo) -> bool:
        return int(time.time()) + self._refresh_margin_sec < info.expires_at

    def _issue_and_write_with_lock(self) -> TokenInfo:
        deadline = time.time() + self._lock_timeout
        while True:
            try:
                with portalocker.Lock(str(self._lock_path), mode="a", timeout=0,
                                      flags=portalocker.LOCK_EX | portalocker.LOCK_NB):
                    # 락 획득 성공 — 다시 캐시 재조회 (다른 프로세스가 방금 갱신했을 수도)
                    info = self._read_cache()
                    if info and self._is_fresh(info):
                        return info
                    logger.info("[smartstore] 토큰 재발급 시작")
                    info = request_new_token(self._cid, self._secret, self._endpoint)
                    self._write_cache(info)
                    return info
            except portalocker.exceptions.LockException as le:
                if time.time() >= deadline:
                    raise SmartStoreAuthError(
                        f"토큰 발급 락 획득 timeout ({self._lock_timeout}s)"
                    ) from le
                # 다른 프로세스가 갱신 중 — 0.5초 대기 후 캐시 재조회
                time.sleep(0.5)
                info = self._read_cache()
                if info and self._is_fresh(info):
                    return info
                # 여전히 없으면 루프 계속

    def _write_cache(self, info: TokenInfo) -> None:
        tmp = self._cache_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({
            "client_id":    self._cid,      # 이 토큰의 주인(다른 계정이 주워 쓰지 못하게)
            "access_token": info.access_token,
            "issued_at":    info.issued_at,
            "expires_at":   info.expires_at,
        }), encoding="utf-8")
        os.replace(tmp, self._cache_path)
