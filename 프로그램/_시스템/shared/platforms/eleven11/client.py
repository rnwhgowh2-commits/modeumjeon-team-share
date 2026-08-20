# -*- coding: utf-8 -*-
"""
11번가 Open API 공통 HTTP 클라이언트 (XML 전송 계층).

책임:
- openapikey 인증 헤더 주입 (auth.build_headers 위임)
- Rate Limit: 토큰버킷 (보수적 기본값)
- 재시도: 429/5xx/네트워크 에 대해 max_retries 회, exponential backoff
- 실패 시 notifier 알림 (3회 재시도 후)

비책임:
- 비즈니스 로직 (prices/inventory/products 에서 처리)
- XML 파싱·필드 해석 (호출자 책임)

주의: 11번가는 요청·응답이 **XML**(주로 euc-kr 인코딩). 이 클라이언트는 HTTP 계층만
      담당하고 응답 본문(XML 텍스트)을 그대로 반환한다.
      롯데온 클라이언트(JSON)와 대칭이되, 반환형이 dict 가 아니라 XML 문자열이다.
"""
from __future__ import annotations

import time
import threading
import logging
from typing import Any, Optional

import requests

from shared.platforms import ELEVEN11 as DEFAULT_ELEVEN11_CFG
from shared.platforms.eleven11.auth import build_headers


logger = logging.getLogger(__name__)


class Eleven11APIError(Exception):
    """11번가 API 호출 실패 (HTTP 계층)."""
    def __init__(self, status_code: int, message: str, payload: Optional[str] = None):
        super().__init__(f"HTTP {status_code}: {message}")
        self.status_code = status_code
        self.message = message
        self.payload = payload or ""


class _TokenBucket:
    """초당 N 요청으로 제한하는 토큰 버킷 (롯데온·쿠팡 클라이언트와 동일 구현)."""
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
                wait = (1.0 - self._tokens) / self._rate
            time.sleep(wait)


# 재시도 불가 응답 (4xx). 429 는 별도 처리.
_NON_RETRYABLE_CLIENT_ERRORS = {400, 401, 403, 404}


class Eleven11Client:
    """11번가 Open API 공통 클라이언트.

    - 각 호출마다 openapikey 헤더 자동 주입
    - Rate limit / 재시도 / 알림 공통 처리
    - 반환 = 응답 XML 본문(str). HTTP 성공(2xx)만 판정하고 XML 해석은 호출자 몫.
    """

    def __init__(self, config: Optional[dict] = None, notifier: Optional[Any] = None):
        self._cfg = dict(config or DEFAULT_ELEVEN11_CFG)
        self._notifier = notifier
        self._limiter = _TokenBucket(self._cfg.get("rate_limit_per_sec", 5))

    def _url(self, path: str) -> str:
        base = self._cfg["base_url"]
        return f"{base}{path}"

    def _headers(self) -> dict:
        return build_headers(self._cfg.get("openapi_key", ""))

    def _notify(self, subject: str, detail: dict) -> None:
        if not self._notifier:
            return
        try:
            self._notifier.send_alert(subject=subject, detail=detail)
        except Exception:  # 알림 실패가 API 호출 실패를 덮으면 안 됨
            logger.exception("notifier.send_alert 실패")

    def request(self, method: str, path: str, body: Optional[str] = None) -> str:
        """11번가 API 호출.

        Args:
            method: HTTP method
            path: 엔드포인트 경로
            body: XML 요청 본문(str) — 11번가는 XML 페이로드.

        Returns:
            응답 XML 본문(str).

        Raises:
            Eleven11APIError: 재시도 후에도 실패했을 때.
        """
        method = method.upper()
        max_retries = int(self._cfg.get("max_retries", 3))
        backoff = float(self._cfg.get("retry_backoff_sec", 2))
        timeout = float(self._cfg.get("request_timeout_sec", 30))

        last_error: Optional[Eleven11APIError] = None
        attempts = max_retries + 1

        for attempt in range(attempts):
            self._limiter.acquire()
            url = self._url(path)
            headers = self._headers()
            if body is None:
                # 본문 없는 GET 에 요청 Content-Type 을 실으면 일부 서비스가 415 로 거부
                # (예: prodqnaservices). GET 은 요청 Content-Type 이 무의미 → 제거.
                headers.pop("Content-Type", None)

            try:
                resp = requests.request(
                    method=method,
                    url=url,
                    headers=headers,
                    data=body.encode("euc-kr") if isinstance(body, str) else body,
                    timeout=timeout,
                )
            except requests.RequestException as e:
                logger.warning("eleven11 request exception attempt=%d err=%s", attempt, e)
                last_error = Eleven11APIError(-1, f"network: {e}")
                time.sleep(backoff * (2 ** attempt))
                continue

            status = resp.status_code

            if 200 <= status < 300:
                # 11번가는 euc-kr XML — requests 가 인코딩을 못 잡으면 명시.
                if not resp.encoding:
                    resp.encoding = "euc-kr"
                return resp.text

            if status == 429:
                retry_after = int(resp.headers.get("Retry-After", "1"))
                logger.warning("eleven11 429 retry_after=%d attempt=%d", retry_after, attempt)
                last_error = Eleven11APIError(429, "rate limited", resp.text[:300])
                time.sleep(max(retry_after, 1))
                continue

            if status in _NON_RETRYABLE_CLIENT_ERRORS:
                msg = resp.text[:300]
                if status == 401:
                    msg = f"인증키 오류(401) — ELEVEN11_MAIN_OPENAPI_KEY 확인. {msg}"
                elif status == 403:
                    msg = f"접근 거부(403) — 출발지 IP 미등록(API 센터에 서버 IP 등록). {msg}"
                err = Eleven11APIError(status, str(msg), resp.text[:300])
                self._notify(
                    subject=f"[11번가] {method} {path} {status} 에러",
                    detail={"status": status, "message": msg, "body": body},
                )
                raise err

            last_error = Eleven11APIError(status, resp.text[:300], resp.text[:300])
            logger.warning("eleven11 %s retryable attempt=%d body=%s", status, attempt, resp.text[:200])
            time.sleep(backoff * (2 ** attempt))

        assert last_error is not None
        self._notify(
            subject=f"[11번가] {method} {path} 재시도 {max_retries}회 실패",
            detail={"status": last_error.status_code, "message": last_error.message, "body": body},
        )
        raise last_error
