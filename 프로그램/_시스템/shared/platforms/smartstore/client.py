# -*- coding: utf-8 -*-
"""
스마트스토어 공통 HTTP 클라이언트.

Phase:
  (Task 5) AdaptiveLimiter + 예외 클래스
  (Task 6) SmartStoreClient.request() 본체

책임:
- Bearer 토큰 자동 부착 (TokenStore 위임)
- 동적 rate limit (응답 헤더 기반 조절)
- 429/401/5xx 처리 분기
- notifier 알림 (연속 rate limit 초과 시 등)
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Optional

import requests

from shared.platforms import SMARTSTORE as DEFAULT_CFG
from shared.platforms.smartstore.token_store import TokenStore

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# 예외
# ──────────────────────────────────────────────────────────────
class SmartStoreAPIError(Exception):
    def __init__(self, status_code: int, code: str, message: str, payload: Optional[dict] = None):
        super().__init__(f"HTTP {status_code} [{code}] {message}")
        self.status_code = status_code
        self.code = code
        self.message = message
        self.payload = payload or {}


class SmartStoreRateLimitError(Exception):
    def __init__(self, retry_after_sec: int):
        super().__init__(f"429 rate limited, retry_after={retry_after_sec}")
        self.retry_after_sec = retry_after_sec


# ──────────────────────────────────────────────────────────────
# Adaptive Limiter (토큰버킷 + 실시간 rate 조정)
# ──────────────────────────────────────────────────────────────
class AdaptiveLimiter:
    """토큰버킷 기반. rate 가 런타임에 변경됨."""

    def __init__(self, initial_rate: float, min_rate: float, max_rate: float,
                 safety_margin: float):
        self._min = float(min_rate)
        self._max = float(max_rate)
        self._margin = float(safety_margin)
        self._rate = float(initial_rate)
        self._capacity = max(self._rate, 1.0)
        self._tokens = self._capacity
        self._last = time.monotonic()
        self._lock = threading.Lock()

    @property
    def rate(self) -> float:
        return self._rate

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
                wait = (1.0 - self._tokens) / max(self._rate, 0.01)
            time.sleep(wait)

    def halve(self) -> None:
        with self._lock:
            self._rate = max(self._min, self._rate / 2.0)
            self._capacity = max(self._rate, 1.0)

    def set_rate_from_replenish(self, replenish_per_sec: float) -> None:
        target = replenish_per_sec * (1.0 - self._margin)
        with self._lock:
            self._rate = max(self._min, min(self._max, target))
            self._capacity = max(self._rate, 1.0)

    def note_success(self) -> None:
        """성공 후 속도 점진 회복 (최대치까지).

        5% 배율 증분 (multiplicative increase) — halve() 의 급격한 감속을
        상쇄하되 과회복 방지를 위해 증가폭은 작게 유지.
        """
        with self._lock:
            self._rate = min(self._max, self._rate * 1.05)
            self._capacity = max(self._rate, 1.0)


# ──────────────────────────────────────────────────────────────
# SmartStoreClient
# ──────────────────────────────────────────────────────────────
_NON_RETRYABLE = {400, 403, 404, 422}


class SmartStoreClient:
    """스마트스토어 공통 HTTP 클라이언트.

    - Bearer 토큰 자동 부착 (TokenStore 위임)
    - 동적 rate limit (응답 헤더 기반 조절)
    - 429/401/4xx/5xx 처리 분기
    - notifier 알림 (연속 rate limit 초과, 토큰 발급 실패 등)
    """

    def __init__(self, config: Optional[dict] = None,
                 token_store: Optional[TokenStore] = None,
                 notifier=None,
                 limiter: Optional[AdaptiveLimiter] = None):
        self._cfg = dict(config or DEFAULT_CFG)
        paths = self._cfg.get("paths", {})
        self._token = token_store or TokenStore(
            client_id=self._cfg["client_id"],
            client_secret=self._cfg["client_secret"],
            endpoint_url=self._cfg["base_url"] + paths.get("token", "/external/v1/oauth2/token"),
            cache_path=self._cfg["token_cache_path"],
            lock_path=self._cfg["token_lock_path"],
            refresh_margin_sec=self._cfg.get("token_refresh_margin_sec", 600),
            lock_acquire_timeout_sec=self._cfg.get("token_lock_acquire_timeout_sec", 10),
        )
        self._limiter = limiter or AdaptiveLimiter(
            initial_rate=self._cfg["initial_rate_per_sec"],
            min_rate=self._cfg["min_rate_per_sec"],
            max_rate=self._cfg["max_rate_per_sec"],
            safety_margin=self._cfg["rate_safety_margin"],
        )
        self._notifier = notifier
        self._consecutive_429 = 0

    def path_for(self, name: str, **kwargs) -> str:
        """설정된 엔드포인트 경로를 파라미터 치환하여 반환한다.

        Args:
            name: config.SMARTSTORE['paths'] 의 키 ('get_product', 'update_price', ...)
            **kwargs: .format() 에 전달할 치환 파라미터 (예: originProductNo=12345)

        Returns:
            완성된 path (base_url 미포함).
        """
        tpl = self._cfg["paths"][name]
        return tpl.format(**kwargs) if kwargs else tpl

    def request(self, method: str, path: str, query: str = "",
                body: Optional[dict] = None) -> dict:
        """스마트스토어 API 호출.

        Raises:
            SmartStoreRateLimitError: 429 수신 (워커가 requeue 처리)
            SmartStoreAPIError: 재시도 소진 또는 재시도 불가능한 4xx
        """
        method = method.upper()
        retried_auth_once = False
        max_retries = int(self._cfg.get("max_retries", 3))
        backoff = float(self._cfg.get("retry_backoff_sec", 2))
        timeout = float(self._cfg.get("request_timeout_sec", 30))

        last_error: Optional[SmartStoreAPIError] = None

        for attempt in range(max_retries + 1):
            self._limiter.acquire()
            url = self._build_url(path, query)
            try:
                token = self._token.get_valid_token()
            except Exception as e:
                self._notify_token_failure(str(e))
                raise

            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type":  "application/json",
                "Accept":        "application/json",
            }
            try:
                resp = requests.request(
                    method=method, url=url, headers=headers,
                    json=body,
                    timeout=timeout,
                )
            except requests.RequestException as e:
                logger.warning("smartstore 네트워크 예외 attempt=%d err=%s", attempt, e)
                last_error = SmartStoreAPIError(-1, "NETWORK", str(e))
                last_error.__cause__ = e   # 원본 traceback 체인 보존
                if attempt < max_retries:
                    time.sleep(backoff * (2 ** attempt))
                continue

            status = resp.status_code
            payload = self._safe_json(resp)

            if 200 <= status < 300:
                self._consecutive_429 = 0
                self._limiter.note_success()
                # 응답 헤더 기반 rate 조정 — note_success 보정을 덮어쓰기 위해 후행
                self._update_limiter_from_headers(resp.headers)
                return payload if payload else {}

            # 비성공 응답에서도 rate 조정 힌트는 반영
            self._update_limiter_from_headers(resp.headers)

            code = str(payload.get("code", ""))
            msg = str(payload.get("message", resp.text[:200]))

            if status == 429:
                # 두 가지 유형 구분: 초당 rate limit vs 판매자 할당량 quota limit
                is_quota = code == "GW.QUOTA_LIMIT"
                if is_quota:
                    # 할당량 — halve 하지 않음 (초당 제한 아님)
                    retry_sec = self._parse_quota_retry(resp)
                    logger.warning("[smartstore] 429 GW.QUOTA_LIMIT — retry_after=%ds", retry_sec)
                else:
                    # 초당 rate limit — 현재 제한의 절반으로 내림
                    self._limiter.halve()
                    self._consecutive_429 += 1
                    threshold = int(self._cfg.get("rate_limit_hit_alert_threshold", 10))
                    if self._consecutive_429 >= threshold:
                        self._notify_rate_limit_saturation(self._consecutive_429)
                    retry_sec = self._parse_retry_after(resp)
                raise SmartStoreRateLimitError(retry_after_sec=retry_sec)

            if status == 401 and code == "GW.AUTHN" and not retried_auth_once:
                logger.info("[smartstore] 401 GW.AUTHN — 토큰 무효화 후 재시도")
                self._token.invalidate()
                retried_auth_once = True
                continue   # attempt 는 다음으로 전진하되 backoff 없이 즉시 재시도 (최대 1회 보장)

            if status == 401:
                # 401 이지만 GW.AUTHN 이 아니거나 이미 재시도함 → 권한 문제로 간주
                logger.warning("[smartstore] 401 but code=%s — 토큰 재발급 불가 상황", code)
                raise SmartStoreAPIError(status, code, msg, payload)

            if status in _NON_RETRYABLE:
                raise SmartStoreAPIError(status, code, msg, payload)

            # 5xx / 기타
            last_error = SmartStoreAPIError(status, code, msg, payload)
            logger.warning("smartstore %s retry attempt=%d body=%s", status, attempt, resp.text[:200])
            if attempt < max_retries:
                time.sleep(backoff * (2 ** attempt))

        # 재시도 소진
        assert last_error is not None
        self._notify_upload_failure(method, path, last_error)
        raise last_error

    # ── helpers ─────────────────────────────────────────
    def _build_url(self, path: str, query: str) -> str:
        base = self._cfg["base_url"]
        return f"{base}{path}?{query}" if query else f"{base}{path}"

    def _safe_json(self, resp) -> dict:
        try:
            return resp.json() or {}
        except ValueError:
            return {}

    def _update_limiter_from_headers(self, headers) -> None:
        replenish = headers.get("GNCP-GW-RateLimit-Replenish-Rate")
        if replenish:
            try:
                self._limiter.set_rate_from_replenish(float(replenish))
            except ValueError:
                pass

    def _parse_retry_after(self, resp) -> int:
        ra = resp.headers.get("Retry-After")
        if ra:
            try: return max(1, int(ra))
            except ValueError: pass
        return 5   # 기본값

    def _parse_quota_retry(self, resp) -> int:
        """GNCP-GW-Quota-* 헤더에서 retry-after 계산.

        Period=SECONDS 면 헤더의 남은 시간에 해당하는 초 반환.
        Period=ROUND 이면 매우 길 수 있으므로 기본 300초.
        """
        period = resp.headers.get("GNCP-GW-Quota-Period", "SECONDS")
        if period == "SECONDS":
            # 다음 1초로 reset — 1초 대기가 안전
            return 1
        if period == "ROUND":
            # 구독 회차 — 보수적으로 5분 대기
            return 300
        # 모르는 값 → 기본 5초
        return 5

    def _notify_token_failure(self, detail: str) -> None:
        try:
            from shared.notifier import notify, AlertType
            notify(AlertType.토큰발급실패, platform="smartstore", detail=detail)
        except Exception:
            logger.exception("토큰 발급 실패 알림 발송 실패")

    def _notify_rate_limit_saturation(self, count: int) -> None:
        from shared.notifier import notify, AlertType
        try:
            notify(AlertType.속도한도도달, platform="smartstore", count=count)
        except Exception:
            logger.exception("속도한도도달 알림 발송 실패")
        self._consecutive_429 = 0   # 재알림 스팸 방지

    def _notify_upload_failure(self, method: str, path: str, err: SmartStoreAPIError) -> None:
        from shared.notifier import notify, AlertType
        try:
            notify(AlertType.업로드실패, platform="smartstore",
                   detail=f"{method} {path} {err.status_code} {err.code} {err.message}")
        except Exception:
            logger.exception("업로드실패 알림 발송 실패")
