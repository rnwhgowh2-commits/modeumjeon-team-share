"""env_prefix 기반 시크릿 로더 — UploadAccount 마켓별 자격증명 자동 수집.

설계 원칙:
  · DB 에는 ``env_prefix`` 만 (예: "SMARTSTORE_MAIN") — 시크릿 평문 저장 금지
  · ``.env`` 의 ``{env_prefix}_{FIELD}`` 패턴으로 자동 수집 (예: ``SMARTSTORE_MAIN_CLIENT_ID``)
  · 누락 시 ``SecretsMissingError`` — 어떤 키가 빠졌는지 정확히 명시
  · 미지원 market 은 ``SecretsUnknownMarketError`` — 지원 목록 안내
  · ``__repr__`` 자동 마스킹 — 로그에 평문 시크릿 노출 0
  · 시크릿 단일 출처 = ``.env`` — DB 와 이중 저장 금지

사용 예시::

    from lemouton.auth import secrets as S

    creds = S.load_credentials(market="smartstore", env_prefix="SMARTSTORE_MAIN")
    requests.post(url, headers={"X-Client-Id": creds.client_id, ...})
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Type

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

try:
    from dotenv import load_dotenv as _load_dotenv
except ImportError:  # dotenv 미설치 환경(테스트 등)
    _load_dotenv = None


def secrets_env_path() -> Path:
    """UI(env_writer)가 시크릿을 쓰는 .env 경로.

    ``LEMOUTON_SECRETS_ENV`` 가 있으면 그 경로(배포 시 호스트 볼륨에 마운트된 영속 경로 —
    컨테이너 교체돼도 유지). 없으면 프로젝트 루트 ``.env``(로컬 개발 폴백).
    """
    p = os.environ.get("LEMOUTON_SECRETS_ENV")
    return Path(p) if p else (Path(__file__).resolve().parents[2] / ".env")


def refresh_env() -> None:
    """멀티 워커(gunicorn --workers N) 간 UI 저장 시크릿 불일치 해소.

    UI 키 저장은 시크릿 ``.env`` 파일 + **저장을 처리한 워커 1개**의 ``os.environ`` 만
    갱신한다. 나머지 워커는 그 키를 못 봐서 "미등록"·"키 누락"·"필수 필드 누락"이 요청마다
    오락가락한다. 자격증명·상태를 읽기 직전 **공유 .env 파일을 다시 로드**해 모든 워커를
    같은 최신 상태로 맞춘다.

    안전: 시크릿 ``.env`` 에는 UI 로 저장한 키만 있고, 쿠팡·스마트스토어 키는
    ``~/app.env``(os.environ, 파일 아님)에서 오므로 override 대상 아님.
    """
    path = secrets_env_path()
    if _load_dotenv is not None and path.exists():
        _load_dotenv(path, override=True)


# ──────────────────────────────────────────────────────────
#  예외 — 명시적 실패 (silent fallback 절대 금지)
# ──────────────────────────────────────────────────────────


class SecretsError(RuntimeError):
    """auth.secrets 공통 베이스."""


class SecretsMissingError(SecretsError):
    """필수 시크릿 환경변수가 ``.env`` 에 없거나 빈 문자열."""

    def __init__(self, env_prefix: str, missing_keys: list[str]) -> None:
        self.env_prefix = env_prefix
        self.missing_keys = missing_keys
        super().__init__(
            f"[secrets] env_prefix='{env_prefix}' 에서 필수 키 {len(missing_keys)}개 누락: "
            f"{', '.join(missing_keys)}. .env 파일을 확인하세요."
        )


class SecretsUnknownMarketError(SecretsError):
    """``MARKET_SCHEMAS`` 에 등록되지 않은 market 이름."""

    def __init__(self, market: str, supported: list[str]) -> None:
        self.market = market
        self.supported = supported
        super().__init__(
            f"[secrets] 미지원 market='{market}'. 지원 마켓: {', '.join(supported)}"
        )


# ──────────────────────────────────────────────────────────
#  마스킹 — 로그 안전성 (시크릿 원본 노출 0)
# ──────────────────────────────────────────────────────────


def mask_secret(value: str | None) -> str:
    """시크릿 값을 ``ncp_***7890`` 형태로 마스킹.

    8자 미만 값은 ``***`` 로 전부 가림. None/빈 문자열은 ``<empty>``.
    """
    if value is None or value == "":
        return "<empty>"
    if len(value) < 8:
        return "***"
    return f"{value[:4]}***{value[-4:]}"


class _MaskedReprMixin(BaseModel):
    """모든 자격증명 모델에 자동 마스킹 ``__repr__`` 적용."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    def __repr__(self) -> str:
        cls = type(self).__name__
        masked = ", ".join(
            f"{name}={mask_secret(getattr(self, name))!r}"
            for name in self.__class__.model_fields
        )
        return f"{cls}({masked})"

    __str__ = __repr__


# ──────────────────────────────────────────────────────────
#  자격증명 스키마 — 마켓별 (Phase 2-A 는 smartstore + coupang 만)
# ──────────────────────────────────────────────────────────


class SmartstoreCredentials(_MaskedReprMixin):
    """네이버 스마트스토어 커머스 API 자격증명.

    ``.env`` 키: ``{env_prefix}_CLIENT_ID``, ``{env_prefix}_CLIENT_SECRET``
    """

    client_id: str = Field(min_length=1)
    client_secret: str = Field(min_length=1)


class CoupangCredentials(_MaskedReprMixin):
    """쿠팡 Wing OPEN API 자격증명.

    ``.env`` 키: ``{env_prefix}_ACCESS_KEY``, ``{env_prefix}_SECRET_KEY``, ``{env_prefix}_VENDOR_ID``
    """

    access_key: str = Field(min_length=1)
    secret_key: str = Field(min_length=1)
    vendor_id: str = Field(min_length=1)


class LotteonCredentials(_MaskedReprMixin):
    """롯데온 Open API(셀러센터) 자격증명.

    ``.env`` 키: ``{env_prefix}_API_KEY``, ``{env_prefix}_TR_NO``
    · api_key = 판매자 센터 발급 정적 Bearer 인증키
    · tr_no   = 거래처번호 (모든 상품/가격/재고 호출 필수 파라미터)
    """

    api_key: str = Field(min_length=1)
    tr_no: str = Field(min_length=1)


# 마켓 → 스키마 라우팅 (Phase 2-B/C 에서 11번가·OAuth 등 확장 가능)
MARKET_SCHEMAS: dict[str, Type[_MaskedReprMixin]] = {
    "smartstore": SmartstoreCredentials,
    "coupang": CoupangCredentials,
    "lotteon": LotteonCredentials,
}


def supported_markets() -> list[str]:
    """``MARKET_SCHEMAS`` 에 등록된 마켓 목록."""
    return sorted(MARKET_SCHEMAS.keys())


# ──────────────────────────────────────────────────────────
#  로더 — 환경변수 → 자격증명 객체
# ──────────────────────────────────────────────────────────


def _normalize_prefix(env_prefix: str) -> str:
    """``"SMARTSTORE_MAIN__"`` → ``"SMARTSTORE_MAIN"`` (trailing _ 제거)."""
    return env_prefix.rstrip("_")


def load_credentials(
    market: str,
    env_prefix: str,
) -> _MaskedReprMixin:
    """``market`` 의 자격증명을 ``env_prefix`` 하위 환경변수에서 로드.

    Args:
        market: ``"smartstore"`` | ``"coupang"`` (``MARKET_SCHEMAS`` 키)
        env_prefix: ``"SMARTSTORE_MAIN"`` 같은 식별자.
            trailing ``_`` 은 자동 정규화.

    Returns:
        ``SmartstoreCredentials`` | ``CoupangCredentials`` 등 마켓별 모델 인스턴스.

    Raises:
        SecretsUnknownMarketError: ``market`` 이 ``MARKET_SCHEMAS`` 에 없을 때.
        SecretsMissingError: 필수 환경변수가 누락 또는 빈 값일 때.
    """
    schema = MARKET_SCHEMAS.get(market)
    if schema is None:
        raise SecretsUnknownMarketError(market, supported_markets())

    # 멀티 워커 일관성 — UI 로 방금 저장된 키를 이 워커도 보도록 공유 .env 재로드.
    refresh_env()

    norm = _normalize_prefix(env_prefix)
    field_names = list(schema.model_fields.keys())

    raw: dict[str, str] = {}
    missing: list[str] = []
    for fname in field_names:
        env_key = f"{norm}_{fname.upper()}"
        value = os.environ.get(env_key, "")
        if value == "":
            missing.append(env_key)
        else:
            raw[fname] = value

    if missing:
        # audit 로그 — 누락 키만 (값은 어차피 없음)
        logger.warning(
            "[secrets] credential load FAILED — env_prefix=%s market=%s missing=%s",
            norm,
            market,
            missing,
        )
        raise SecretsMissingError(norm, missing)

    instance = schema(**raw)
    logger.info(
        "[secrets] credential load OK — env_prefix=%s market=%s repr=%r",
        norm,
        market,
        instance,
    )
    return instance
