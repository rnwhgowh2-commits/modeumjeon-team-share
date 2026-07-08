# -*- coding: utf-8 -*-
"""ESM 2.0(옥션·G마켓) HTTP 클라이언트 — JWT 인증·rate limit·재시도.

주문조회는 "5초당 1회" 제한이라 요청 간 최소 간격(order_min_interval_sec)을 강제한다.
config = shared.platforms.AUCTION | GMARKET (base_url·master_id·secret_key·site_id·seller_id·paths).
"""
from __future__ import annotations

import logging
import time

from .auth import build_headers

logger = logging.getLogger(__name__)


class EsmClient:
    def __init__(self, config: dict):
        self._cfg = dict(config or {})
        self.base_url = (self._cfg.get("base_url") or "https://sa2.esmplus.com").rstrip("/")
        self._last_order_call = 0.0

    # ── 인증 ──
    def _headers(self) -> dict:
        return build_headers(
            self._cfg.get("master_id", ""),
            self._cfg.get("secret_key", ""),
            self._cfg.get("site_id", ""),
            self._cfg.get("seller_id", ""),
            issuer=self._cfg.get("auth_issuer", "www.esmplus.com"),
            audience=self._cfg.get("auth_audience", "sa.esmplus.com"),
            iat=int(time.time()),
        )

    def _throttle_orders(self) -> None:
        """주문조회 5초당 1회 — 직전 호출과 최소 간격 확보."""
        gap = float(self._cfg.get("order_min_interval_sec", 5))
        wait = gap - (time.monotonic() - self._last_order_call)
        if wait > 0:
            time.sleep(wait)

    def post(self, path: str, body: dict, *, is_order: bool = False) -> dict:
        """POST {base}{path} (JSON) → JSON. 5xx/네트워크는 지수백오프 재시도."""
        import requests

        if not path:
            raise ValueError("ESM 엔드포인트 경로 미설정 — 스펙 미확보(추측 금지)")
        url = self.base_url + path
        retries = int(self._cfg.get("max_retries", 3))
        backoff = float(self._cfg.get("retry_backoff_sec", 2))
        timeout = float(self._cfg.get("request_timeout_sec", 30))
        last_exc = None
        for attempt in range(retries):
            if is_order:
                self._throttle_orders()
            try:
                resp = requests.post(url, json=body, headers=self._headers(), timeout=timeout)
                if is_order:
                    self._last_order_call = time.monotonic()
                if resp.status_code >= 500:
                    raise RuntimeError(f"ESM {resp.status_code} 서버오류")
                resp.raise_for_status()
                return resp.json()
            except Exception as e:  # noqa: BLE001 — 재시도 대상. 마지막 실패는 전파.
                last_exc = e
                logger.warning("[esm] POST %s 실패(%d/%d): %s", path, attempt + 1, retries, e)
                if attempt < retries - 1:
                    time.sleep(backoff * (attempt + 1))
        raise last_exc

    def request_orders(self, body: dict) -> dict:
        """주문조회(RequestOrders) — 5초 rate limit 적용."""
        path = (self._cfg.get("paths") or {}).get("orders")
        return self.post(path, body, is_order=True)
