"""UploadAccount → MarketClient 라우팅 + 인스턴스 캐시.

설계:
  · ``MarketDispatcher`` 1 인스턴스 = 1 캐시 (account.id → client)
  · 동일 ``account.id`` 재호출 시 같은 client 반환 → 토큰 캐시 보존
  · ``is_active=False`` 계정 호출 시 ``AccountInactiveError``
  · 시크릿 누락은 ``SecretsMissingError`` 그대로 위임

모듈 레벨 ``get_client(account)`` 는 프로세스 단위 싱글톤 dispatcher 사용.
"""
from __future__ import annotations

import logging
import threading
from typing import Protocol

from lemouton.auth import secrets as S
from lemouton.auth.api_coupang import CoupangApiClient
from lemouton.auth.oauth_smartstore import SmartstoreOAuthClient

logger = logging.getLogger(__name__)


# 프로토콜 — 덕 타이핑 (V2 UploadAccount 또는 SimpleNamespace stub 모두 통과)
class _UploadAccountLike(Protocol):
    id: int
    account_key: str
    market: str
    env_prefix: str
    is_active: bool


# 라우팅 union — 두 client 중 하나
MarketClient = SmartstoreOAuthClient | CoupangApiClient


class AccountInactiveError(RuntimeError):
    """is_active=False 계정으로 client 요청 시."""


class MarketDispatcher:
    """UploadAccount 기반 client 라우터 + 캐시.

    호출 흐름::

        dispatcher = MarketDispatcher()
        client = dispatcher.get_client(account)   # 첫 호출: 새 client 생성
        client2 = dispatcher.get_client(account)  # 두 번째: 캐시 반환 (c is c2)
    """

    def __init__(self) -> None:
        self._cache: dict[int, MarketClient] = {}
        self._lock = threading.Lock()

    def get_client(self, account: _UploadAccountLike) -> MarketClient:
        """``account`` 에 맞는 client 반환. 캐시 hit 시 동일 인스턴스.

        Raises:
            AccountInactiveError: ``account.is_active`` 가 False
            SecretsUnknownMarketError: ``account.market`` 미지원
            SecretsMissingError: ``.env`` 시크릿 누락
        """
        if not account.is_active:
            raise AccountInactiveError(
                f"비활성 계정({account.account_key}) 으로 client 요청 — "
                f"활성화 후 다시 시도하거나 다른 계정 사용"
            )

        with self._lock:
            cached = self._cache.get(account.id)
            if cached is not None:
                return cached

            client = self._build_client(account)
            self._cache[account.id] = client
            logger.info(
                "[dispatcher] new client built — account=%s market=%s",
                account.account_key, account.market,
            )
            return client

    def clear_cache(self) -> None:
        """모든 캐시 무효화 (시크릿 변경·테스트 용)."""
        with self._lock:
            self._cache.clear()

    def evict(self, account_id: int) -> bool:
        """특정 계정만 캐시 제거. 존재하지 않았으면 ``False``."""
        with self._lock:
            return self._cache.pop(account_id, None) is not None

    # ──────────────────────────────────────────────────────
    #  내부 빌더
    # ──────────────────────────────────────────────────────

    def _build_client(self, account: _UploadAccountLike) -> MarketClient:
        creds = S.load_credentials(market=account.market, env_prefix=account.env_prefix)

        if account.market == "smartstore":
            assert isinstance(creds, S.SmartstoreCredentials)
            return SmartstoreOAuthClient(creds)
        if account.market == "coupang":
            assert isinstance(creds, S.CoupangCredentials)
            return CoupangApiClient(creds)

        # secrets.load_credentials 가 미지원 market 을 이미 막지만, 방어적으로 한 번 더
        raise S.SecretsUnknownMarketError(account.market, S.supported_markets())


# ──────────────────────────────────────────────────────────
#  프로세스 단위 싱글톤 헬퍼
# ──────────────────────────────────────────────────────────

_default_dispatcher = MarketDispatcher()


def get_client(account: _UploadAccountLike) -> MarketClient:
    """모듈 레벨 헬퍼 — 기본 dispatcher 사용.

    테스트 격리가 필요한 경우 자체 ``MarketDispatcher()`` 인스턴스 사용 권장.
    """
    return _default_dispatcher.get_client(account)


def clear_cache() -> None:
    """모듈 레벨 헬퍼 — 기본 dispatcher 캐시 무효화."""
    _default_dispatcher.clear_cache()
