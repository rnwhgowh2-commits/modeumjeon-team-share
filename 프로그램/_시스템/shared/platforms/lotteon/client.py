# -*- coding: utf-8 -*-
"""
롯데온 Open API 공통 HTTP 클라이언트.

책임:
- Bearer 인증 헤더 주입 (auth.build_headers 위임)
- Rate Limit: 토큰버킷 (기본 보수적 — 문서 상한은 분당 10,000회)
- 재시도: 429/5xx/네트워크 에 대해 max_retries 회, exponential backoff
- 실패 시 notifier 알림 (3회 재시도 후)

비책임:
- 비즈니스 로직 (prices/inventory/products 에서 처리)
- returnCode/resultCode 해석 (호출자 책임)

주의: 롯데온은 HTTP 200 + body.returnCode('0000'=정상) 구조이며,
      배치 엔드포인트는 data[] 각 원소의 resultCode 로 부분 실패를 표현한다.
      이 클라이언트는 HTTP 계층만 처리하고 body 는 그대로 반환한다.
"""
from __future__ import annotations

import time
import threading
import logging
from typing import Any, Optional

import requests

from shared.platforms import LOTTEON as DEFAULT_LOTTEON_CFG
from shared.platforms.lotteon.auth import build_headers


logger = logging.getLogger(__name__)


# ──────────────────────────────────────────
# 예외
# ──────────────────────────────────────────

class LotteonAPIError(Exception):
    """롯데온 API 호출 실패 (HTTP 계층)."""
    def __init__(self, status_code: int, message: str, payload: Optional[dict] = None):
        super().__init__(f"HTTP {status_code}: {message}")
        self.status_code = status_code
        self.message = message
        self.payload = payload or {}


# ──────────────────────────────────────────
# 토큰 버킷 (쿠팡 클라이언트와 동일 구현)
# ──────────────────────────────────────────

class _TokenBucket:
    """초당 N 요청으로 제한하는 토큰 버킷."""
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


# ──────────────────────────────────────────
# 클라이언트
# ──────────────────────────────────────────

# 재시도 불가 응답 (4xx). 429 는 별도 처리.
#   401 키오류 · 403 IP미등록 · 404 없음 · 400 요청오류 — 재시도해도 동일하므로 즉시 표면화.
_NON_RETRYABLE_CLIENT_ERRORS = {400, 401, 403, 404}


class LotteonClient:
    """롯데온 Open API 공통 클라이언트.

    - 각 호출마다 Bearer 헤더 자동 주입
    - Rate limit / 재시도 / 알림 공통 처리
    """

    def __init__(self, config: Optional[dict] = None, notifier: Optional[Any] = None):
        self._cfg = dict(config or DEFAULT_LOTTEON_CFG)
        self._notifier = notifier
        self._limiter = _TokenBucket(self._cfg.get("rate_limit_per_sec", 50))

    # ── 내부 유틸 ──
    def _url(self, path: str) -> str:
        base = self._cfg["base_url"]
        return f"{base}{path}"

    def _headers(self) -> dict:
        return build_headers(self._cfg.get("api_key", ""))

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
        body: Optional[dict] = None,
    ) -> dict:
        """롯데온 API 호출.

        Returns:
            JSON 응답 dict (returnCode/message/data 구조)

        Raises:
            LotteonAPIError: 재시도 후에도 실패했을 때
        """
        method = method.upper()
        max_retries = int(self._cfg.get("max_retries", 3))
        backoff = float(self._cfg.get("retry_backoff_sec", 2))
        timeout = float(self._cfg.get("request_timeout_sec", 30))

        last_error: Optional[LotteonAPIError] = None
        attempts = max_retries + 1   # 최초 1회 + 재시도 N회

        for attempt in range(attempts):
            self._limiter.acquire()
            url = self._url(path)
            headers = self._headers()

            try:
                resp = requests.request(
                    method=method,
                    url=url,
                    headers=headers,
                    json=body if body is not None else None,
                    timeout=timeout,
                )
            except requests.RequestException as e:
                logger.warning("lotteon request exception attempt=%d err=%s", attempt, e)
                last_error = LotteonAPIError(-1, f"network: {e}")
                time.sleep(backoff * (2 ** attempt))
                continue

            status = resp.status_code

            # 성공 (HTTP). body.returnCode 해석은 호출자 몫.
            if 200 <= status < 300:
                try:
                    return resp.json()
                except ValueError:
                    return {"returnCode": "0000", "raw": resp.text}

            # 429: 접속량 초과 → 대기 후 재시도
            if status == 429:
                retry_after = int(resp.headers.get("Retry-After", "1"))
                logger.warning("lotteon 429 retry_after=%d attempt=%d", retry_after, attempt)
                last_error = LotteonAPIError(429, "rate limited (분당 10,000회 초과)", _safe_json(resp))
                time.sleep(max(retry_after, 1))
                continue

            # 재시도 불가능한 4xx → 즉시 알림 & 예외
            if status in _NON_RETRYABLE_CLIENT_ERRORS:
                payload = _safe_json(resp)
                msg = payload.get("message") or payload.get("returnCode") or resp.text[:300]
                if status == 401:
                    msg = f"인증키 오류(401) — LOTTEON_MAIN_API_KEY 확인. {msg}"
                elif status == 403:
                    msg = f"접근 거부(403) — 출발지 IP 미등록(판매자 센터에서 인증키에 서버 IP 등록). {msg}"
                err = LotteonAPIError(status, str(msg), payload)
                self._notify(
                    subject=f"[롯데온] {method} {path} {status} 에러",
                    detail={"status": status, "message": msg, "body": body, "payload": payload},
                )
                raise err

            # 5xx (or 기타): 재시도
            last_error = LotteonAPIError(status, resp.text[:300], _safe_json(resp))
            logger.warning("lotteon %s retryable attempt=%d body=%s", status, attempt, resp.text[:200])
            time.sleep(backoff * (2 ** attempt))

        # 재시도 소진
        assert last_error is not None
        self._notify(
            subject=f"[롯데온] {method} {path} 재시도 {max_retries}회 실패",
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
