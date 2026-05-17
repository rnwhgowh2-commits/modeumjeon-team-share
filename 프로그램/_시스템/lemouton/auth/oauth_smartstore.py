"""네이버 커머스 API OAuth 2.0 client — 토큰 발급 + 캐시 + 401 자동 재시도.

설계:
  · ``client_credentials`` grant (네이버 커머스 표준)
  · 토큰 메모리 캐시 (``expires_in`` 기반 만료 자동 감지)
  · ``call_with_retry`` 헬퍼 — 401 발생 시 1회만 재시도 후 그대로 반환
  · 모든 외부 호출 실패는 ``OAuthRefreshError`` 로 명시적 분기

엔드포인트는 환경변수 ``SMARTSTORE_OAUTH_URL`` 로 오버라이드 가능 (테스트/스테이징).
"""
from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

import requests

from lemouton.auth.secrets import SmartstoreCredentials, mask_secret

logger = logging.getLogger(__name__)


DEFAULT_OAUTH_URL = "https://api.commerce.naver.com/external/v1/oauth2/token"

# 만료 직전에 자동 갱신할 여유 시간 (초). 30 → 만료 30초 전부터 새 토큰 발급.
TOKEN_RENEW_LEEWAY_SEC = 30


class OAuthRefreshError(RuntimeError):
    """OAuth 토큰 발급 또는 갱신 실패 — 명시적 신호."""


@dataclass
class SmartstoreToken:
    access_token: str
    expires_at: float                # epoch 초 (만료 시각)
    token_type: str = "Bearer"

    def is_expired(self, leeway_sec: float = TOKEN_RENEW_LEEWAY_SEC) -> bool:
        return time.time() >= (self.expires_at - leeway_sec)

    def authorization_header(self) -> dict[str, str]:
        return {"Authorization": f"{self.token_type} {self.access_token}"}

    def __repr__(self) -> str:
        return f"SmartstoreToken(access_token={mask_secret(self.access_token)!r}, expires_at={self.expires_at})"


class SmartstoreOAuthClient:
    """네이버 커머스 OAuth 2.0 client (싱글-플라이트 + 토큰 캐시).

    Args:
        creds: ``SmartstoreCredentials`` (``client_id`` + ``client_secret``)
        oauth_url: 엔드포인트 (기본값: 네이버 커머스 운영). 환경변수
            ``SMARTSTORE_OAUTH_URL`` 로도 오버라이드.
        timeout: 토큰 요청 타임아웃 (초)
    """

    def __init__(
        self,
        creds: SmartstoreCredentials,
        oauth_url: Optional[str] = None,
        timeout: float = 10.0,
    ) -> None:
        self.creds = creds
        self.oauth_url = (
            oauth_url
            or os.environ.get("SMARTSTORE_OAUTH_URL")
            or DEFAULT_OAUTH_URL
        )
        self.timeout = timeout
        self._token: Optional[SmartstoreToken] = None
        self._lock = threading.Lock()  # single-flight: 동시 갱신 방지

    # ──────────────────────────────────────────────────────
    #  토큰 발급 / 캐시
    # ──────────────────────────────────────────────────────

    def get_token(self, force_refresh: bool = False) -> SmartstoreToken:
        """캐시 우선. 만료 또는 ``force_refresh`` 시 새로 발급."""
        with self._lock:
            if (
                not force_refresh
                and self._token is not None
                and not self._token.is_expired()
            ):
                return self._token

            self._token = self._fetch_new_token()
            return self._token

    def _fetch_new_token(self) -> SmartstoreToken:
        try:
            response = requests.post(
                self.oauth_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.creds.client_id,
                    "client_secret": self.creds.client_secret,
                    "type": "SELF",
                },
                timeout=self.timeout,
            )
        except requests.exceptions.RequestException as e:
            logger.error("[oauth_smartstore] network error: %s", e)
            raise OAuthRefreshError(f"OAuth network error: {e}") from e

        if response.status_code != 200:
            logger.error(
                "[oauth_smartstore] token fetch failed status=%s body=%s",
                response.status_code,
                response.text[:200],
            )
            raise OAuthRefreshError(
                f"OAuth token fetch failed — status={response.status_code} "
                f"body={response.text[:200]}"
            )

        body = response.json()
        access_token = body.get("access_token")
        expires_in = body.get("expires_in", 10800)  # 기본 3시간
        if not access_token:
            raise OAuthRefreshError(f"OAuth response missing access_token: {body}")

        token = SmartstoreToken(
            access_token=access_token,
            expires_at=time.time() + float(expires_in),
            token_type=body.get("token_type", "Bearer"),
        )
        logger.info(
            "[oauth_smartstore] token issued — expires_in=%ss client_id=%s",
            expires_in,
            mask_secret(self.creds.client_id),
        )
        return token

    # ──────────────────────────────────────────────────────
    #  401 자동 재시도 헬퍼
    # ──────────────────────────────────────────────────────

    def call_with_retry(
        self,
        api_call: Callable[[dict[str, str]], requests.Response],
    ) -> requests.Response:
        """``api_call(headers)`` 실행. 401 발생 시 1회만 토큰 갱신 후 재시도.

        Args:
            api_call: ``Authorization`` 헤더 dict 를 인자로 받아 ``Response`` 반환하는 callable

        Returns:
            마지막 ``Response`` (재시도 후에도 401 이면 그 401 그대로)
        """
        token = self.get_token()
        response = api_call(token.authorization_header())

        if response.status_code != 401:
            return response

        # 401 → 강제 갱신 후 재시도 1번만
        logger.warning("[oauth_smartstore] 401 received — refreshing token and retrying once")
        new_token = self.get_token(force_refresh=True)
        return api_call(new_token.authorization_header())
