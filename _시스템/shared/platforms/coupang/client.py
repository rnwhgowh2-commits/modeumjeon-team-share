# -*- coding: utf-8 -*-
"""
쿠팡 Open API 공통 HTTP 클라이언트

책임:
- 요청 서명 (auth 위임)
- Rate Limit: 5 req/s 토큰버킷
- 재시도: 429/5xx 에 대해 max_retries 회, exponential backoff
- 429 수신 시 Retry-After 헤더 존중
- 실패 시 notifier 알림 (CLAUDE.md: 3회 재시도 후 알림)

비책임:
- 비즈니스 로직 (prices/inventory/products 에서 처리)
- 이전값 유지 (호출자 책임)
"""
from __future__ import annotations

import json
import time
import threading
import logging
from typing import Any, Optional

import requests

from shared.platforms import COUPANG as DEFAULT_COUPANG_CFG
from shared.platforms.coupang.auth import build_authorization


logger = logging.getLogger(__name__)


# ──────────────────────────────────────────
# 예외
# ──────────────────────────────────────────

class CoupangAPIError(Exception):
    """쿠팡 API 호출 실패."""
    def __init__(self, status_code: int, message: str, payload: Optional[dict] = None):
        super().__init__(f"HTTP {status_code}: {message}")
        self.status_code = status_code
        self.message = message
        self.payload = payload or {}


# ──────────────────────────────────────────
# 토큰 버킷 (간이 구현)
# ──────────────────────────────────────────

class _TokenBucket:
    """초당 N 요청으로 제한하는 토큰 버킷.

    허용 용량 = rate_per_sec (버스트 허용 정도).
    """
    def __init__(self, rate_per_sec: float):
        self._rate = float(rate_per_sec)
        self._capacity = float(rate_per_sec)
        self._tokens = float(rate_per_sec)
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                elapsed = now - self._last
                self._last = now
                self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                # 1토큰 생성까지 대기 시간
                wait = (1.0 - self._tokens) / self._rate
            time.sleep(wait)


# ──────────────────────────────────────────
# 클라이언트
# ──────────────────────────────────────────

# 재시도 불가 응답 (4xx 중 서버 보호용). 429 는 별도 처리.
_NON_RETRYABLE_CLIENT_ERRORS = {400, 401, 403, 404, 422}


class CoupangClient:
    """쿠팡 Open API 공통 클라이언트.

    - 각 호출마다 Authorization 헤더 자동 생성
    - Rate limit / 재시도 / 알림을 공통 처리
    """

    def __init__(self, config: Optional[dict] = None, notifier: Optional[Any] = None):
        self._cfg = dict(config or DEFAULT_COUPANG_CFG)
        self._notifier = notifier
        self._limiter = _TokenBucket(self._cfg.get("rate_limit_per_sec", 5))

    # ── 내부 유틸 ──
    def _url(self, path: str, query: str) -> str:
        base = self._cfg["base_url"]
        return f"{base}{path}?{query}" if query else f"{base}{path}"

    def _headers(self, method: str, path: str, query: str) -> dict:
        authorization = build_authorization(
            method=method,
            path=path,
            query=query,
            access_key=self._cfg["access_key"],
            secret_key=self._cfg["secret_key"],
        )
        return {
            "Authorization": authorization,
            "Content-Type": "application/json;charset=UTF-8",
            "X-EXTENDED-Timeout": "90000",
        }

    def _notify(self, subject: str, detail: dict) -> None:
        if not self._notifier:
            return
        try:
            self._notifier.send_alert(subject=subject, detail=detail)
        except Exception:  # 알림 실패가 API 호출 실패를 덮으면 안 됨
            logger.exception("notifier.send_alert 실패")

    # ── 메인 진입점 ──
    def request(
        self,
        method: str,
        path: str,
        query: str = "",
        body: Optional[dict] = None,
    ) -> dict:
        """쿠팡 API 호출.

        Returns:
            JSON 응답 dict (code/message/data 구조)

        Raises:
            CoupangAPIError: 재시도 후에도 실패했을 때
        """
        method = method.upper()
        max_retries = int(self._cfg.get("max_retries", 3))
        backoff = float(self._cfg.get("retry_backoff_sec", 2))
        timeout = float(self._cfg.get("request_timeout_sec", 30))

        last_error: Optional[CoupangAPIError] = None
        attempts = max_retries + 1   # 최초 1회 + 재시도 N회

        for attempt in range(attempts):
            self._limiter.acquire()
            url = self._url(path, query)
            headers = self._headers(method, path, query)

            try:
                resp = requests.request(
                    method=method,
                    url=url,
                    headers=headers,
                    data=json.dumps(body) if body is not None else None,
                    timeout=timeout,
                )
            except requests.RequestException as e:
                logger.warning("coupang request exception attempt=%d err=%s", attempt, e)
                last_error = CoupangAPIError(-1, f"network: {e}")
                time.sleep(backoff * (2 ** attempt))
                continue

            status = resp.status_code

            # 성공
            if 200 <= status < 300:
                try:
                    return resp.json()
                except ValueError:
                    return {"code": "SUCCESS", "raw": resp.text}

            # 429: Retry-After 존중
            if status == 429:
                retry_after = int(resp.headers.get("Retry-After", "1"))
                logger.warning("coupang 429 retry_after=%d attempt=%d", retry_after, attempt)
                last_error = CoupangAPIError(429, "rate limited", _safe_json(resp))
                time.sleep(max(retry_after, 1))
                continue

            # 재시도 불가능한 4xx → 즉시 알림 & 예외
            if status in _NON_RETRYABLE_CLIENT_ERRORS:
                payload = _safe_json(resp)
                msg = payload.get("message") or payload.get("error") or resp.text[:300]
                err = CoupangAPIError(status, str(msg), payload)
                self._notify(
                    subject=f"[쿠팡] {method} {path} {status} 에러",
                    detail={"status": status, "message": msg, "body": body, "payload": payload},
                )
                raise err

            # 5xx (or 기타): 재시도
            last_error = CoupangAPIError(status, resp.text[:300], _safe_json(resp))
            logger.warning("coupang %s retryable attempt=%d body=%s", status, attempt, resp.text[:200])
            time.sleep(backoff * (2 ** attempt))

        # 재시도 소진
        assert last_error is not None
        self._notify(
            subject=f"[쿠팡] {method} {path} 재시도 {max_retries}회 실패",
            detail={
                "status": last_error.status_code,
                "message": last_error.message,
                "body": body,
            },
        )
        raise last_error


def _safe_json(resp) -> dict:
    try:
        return resp.json()
    except (ValueError, AttributeError):
        return {}
