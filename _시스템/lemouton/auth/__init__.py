"""auth — 멀티 계정 인증 레이어 (Phase 2-A 골격).

구성:
  · ``secrets``       — env_prefix 기반 시크릿 로더 (.env 실 로딩 + 타입 검증)
  · ``session_store`` — Playwright storage_state 저장/조회/만료 감지 (filelock)
  · 본 모듈 (``__init__``) — 통합 진입점 + 외부 응답 분류 enum

원칙:
  · 시크릿 단일 출처 = ``.env`` (DB 평문 저장 금지)
  · 누락·만료는 명시적 예외 또는 ``None`` (silent fallback 금지)
  · 로깅 시 자동 마스킹 (``ncp_***7890`` 형태)
  · 외부 호출은 ``classify_external_response`` 로 의미 있는 분류로 변환

Phase 2-B/C 가 본 진입점을 사용해 실제 OAuth/Playwright 로직을 추가할 예정.
"""
from __future__ import annotations

import enum
import logging
import os
from pathlib import Path
from typing import Optional, Protocol, Union

import requests

from lemouton.auth import secrets
from lemouton.auth.session_store import SessionStore

logger = logging.getLogger(__name__)


__all__ = [
    "get_credentials",
    "get_session",
    "classify_external_response",
    "ExternalCallStatus",
    "default_auth_dir",
]


# ──────────────────────────────────────────────────────────
#  덕 타이핑 프로토콜 — UploadAccount / SourcingAccount 의존 X
#  (테스트는 SimpleNamespace 로, 실제 코드는 V2 모델로 작동)
# ──────────────────────────────────────────────────────────


class _UploadAccountLike(Protocol):
    market: str
    env_prefix: str


class _SourcingAccountLike(Protocol):
    source: str
    account_key: str


# ──────────────────────────────────────────────────────────
#  기본 auth_dir — config.SOURCING_AUTH 경로 재사용
# ──────────────────────────────────────────────────────────


def default_auth_dir() -> Path:
    """프로젝트 표준 ``data/auth`` 디렉토리. config 가 못 불러지면 fallback."""
    try:
        from config import SOURCING_AUTH
        return Path(SOURCING_AUTH["auth_dir"])
    except Exception:  # config 임포트 실패 시 (테스트 환경 등)
        return Path.cwd() / "data" / "auth"


# ──────────────────────────────────────────────────────────
#  통합 진입점 1: get_credentials
# ──────────────────────────────────────────────────────────


def get_credentials(account: _UploadAccountLike) -> secrets._MaskedReprMixin:
    """``UploadAccount`` 의 자격증명을 ``.env`` 에서 자동 로드.

    Args:
        account: ``market`` + ``env_prefix`` 를 가진 객체 (V2 ``UploadAccount`` 또는 stub)

    Returns:
        마켓별 자격증명 모델 (``SmartstoreCredentials`` / ``CoupangCredentials``)

    Raises:
        SecretsMissingError / SecretsUnknownMarketError — ``secrets.load_credentials`` 그대로 위임
    """
    return secrets.load_credentials(market=account.market, env_prefix=account.env_prefix)


# ──────────────────────────────────────────────────────────
#  통합 진입점 2: get_session
# ──────────────────────────────────────────────────────────


def get_session(
    account: _SourcingAccountLike,
    auth_dir: Optional[Union[str, os.PathLike]] = None,
    ttl_days: float = 30.0,
) -> Optional[dict]:
    """``SourcingAccount`` 의 storage_state 를 로드. 누락/만료 시 ``None``.

    ``None`` 반환은 곧 "재로그인 필요" 신호 (호출자가 자동 로그인 위저드 트리거).

    Args:
        account: ``source`` + ``account_key`` 를 가진 객체
        auth_dir: 세션 파일 디렉토리 (기본값: ``data/auth/``)
        ttl_days: 만료 임계값 (일). 초과 시 None 반환.
    """
    store_dir = Path(auth_dir) if auth_dir is not None else default_auth_dir()
    store = SessionStore(auth_dir=store_dir)

    if store.is_expired(account.source, account.account_key, ttl_days=ttl_days):
        if store.has_session(account.source, account.account_key):
            logger.warning(
                "[auth] session expired (>%sd) for %s/%s — relogin required",
                ttl_days, account.source, account.account_key,
            )
        return None

    return store.load_session(account.source, account.account_key)


# ──────────────────────────────────────────────────────────
#  외부 호출 응답 분류 — 의미 있는 enum
# ──────────────────────────────────────────────────────────


class ExternalCallStatus(enum.Enum):
    """외부 호출 결과의 의미 분류 (재시도/재로그인/DLQ 결정용)."""

    OK = "ok"                                   # 200
    AUTH_FAILED = "auth_failed"                 # 401 → 토큰 갱신 또는 재로그인
    PERMISSION_DENIED = "permission_denied"     # 403 → 사용자 권한 문제
    NOT_FOUND = "not_found"                     # 404 → 리소스 없음
    RATE_LIMIT = "rate_limit"                   # 429 → 백오프 후 재시도
    SERVER_ERROR = "server_error"               # 5xx → 재시도 또는 DLQ
    BAD_REQUEST = "bad_request"                 # 400 → 우리 측 데이터 오류
    TIMEOUT = "timeout"                         # 타임아웃 → 재시도
    NETWORK_ERROR = "network_error"             # 연결 실패 → 재시도
    UNKNOWN = "unknown"                         # 그 외


def classify_external_response(
    response: Optional[requests.Response] = None,
    error: Optional[Exception] = None,
) -> ExternalCallStatus:
    """``requests`` 응답 또는 예외를 ``ExternalCallStatus`` 로 분류.

    Args:
        response: ``requests.Response`` (성공 또는 4xx/5xx)
        error: ``requests.exceptions.*`` (Timeout / ConnectionError 등)

    한 번에 하나만 전달. 둘 다 None 이면 ``UNKNOWN``.
    """
    if error is not None:
        if isinstance(error, requests.exceptions.Timeout):
            return ExternalCallStatus.TIMEOUT
        if isinstance(error, requests.exceptions.ConnectionError):
            return ExternalCallStatus.NETWORK_ERROR
        return ExternalCallStatus.UNKNOWN

    if response is None:
        return ExternalCallStatus.UNKNOWN

    code = response.status_code
    if 200 <= code < 300:
        return ExternalCallStatus.OK
    if code == 400:
        return ExternalCallStatus.BAD_REQUEST
    if code == 401:
        return ExternalCallStatus.AUTH_FAILED
    if code == 403:
        return ExternalCallStatus.PERMISSION_DENIED
    if code == 404:
        return ExternalCallStatus.NOT_FOUND
    if code == 429:
        return ExternalCallStatus.RATE_LIMIT
    if 500 <= code < 600:
        return ExternalCallStatus.SERVER_ERROR
    return ExternalCallStatus.UNKNOWN
