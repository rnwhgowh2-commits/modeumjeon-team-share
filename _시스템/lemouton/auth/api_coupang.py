"""쿠팡 Wing OPEN API HMAC-SHA256 서명 client.

쿠팡 표준 인증:
  · datetime: ``yyMMddTHHmmssZ`` (UTC)
  · message = ``datetime`` + ``METHOD`` + ``path`` + ``query``
  · signature = HMAC-SHA256(secret_key, message).hexdigest()
  · Authorization 헤더 = ``CEA algorithm=HmacSHA256, access-key={ak}, signed-date={dt}, signature={sig}``

레퍼런스: https://developers.coupangcorp.com/hc/ko/articles/360033723194
"""
from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlsplit

import requests

from lemouton.auth.secrets import CoupangCredentials, mask_secret

logger = logging.getLogger(__name__)


DEFAULT_BASE_URL = "https://api-gateway.coupang.com"
DEFAULT_USER_AGENT = "LemoutonStockManager/2.0 (+https://lemouton.co.kr)"


# ──────────────────────────────────────────────────────────
#  서명 빌더 — 순수 함수 (테스트 용이성)
# ──────────────────────────────────────────────────────────


def sign(secret_key: str, message: str) -> str:
    """HMAC-SHA256 hex digest. 결정적."""
    return hmac.new(
        secret_key.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def build_message(dt: datetime, method: str, path: str, query: str) -> str:
    """쿠팡 서명 대상 메시지 = ``datetime`` + ``METHOD`` + ``path`` + ``query``.

    Args:
        dt: UTC datetime
        method: GET / POST / PUT / DELETE (대소문자 무관 — 자동 대문자화)
        path: ``/v2/providers/seller_api/...``
        query: ``vendorId=A001&status=ACTIVE`` 또는 빈 문자열

    Returns:
        HMAC 입력 문자열
    """
    dt_str = dt.astimezone(timezone.utc).strftime("%y%m%dT%H%M%SZ")
    return f"{dt_str}{method.upper()}{path}{query}"


def build_authorization_header(
    creds: CoupangCredentials,
    dt: datetime,
    method: str,
    path: str,
    query: str,
) -> str:
    """완성된 Authorization 헤더 값 (``CEA algorithm=...``)."""
    dt_str = dt.astimezone(timezone.utc).strftime("%y%m%dT%H%M%SZ")
    message = build_message(dt, method, path, query)
    signature = sign(creds.secret_key, message)
    return (
        f"CEA algorithm=HmacSHA256, "
        f"access-key={creds.access_key}, "
        f"signed-date={dt_str}, "
        f"signature={signature}"
    )


# ──────────────────────────────────────────────────────────
#  Client — 요청 송신
# ──────────────────────────────────────────────────────────


class CoupangApiClient:
    """쿠팡 Wing API client. 호출마다 자동 서명.

    Args:
        creds: ``CoupangCredentials``
        base_url: 기본 https://api-gateway.coupang.com (테스트/스테이징 오버라이드 가능)
        timeout: 요청 타임아웃 (초)
    """

    def __init__(
        self,
        creds: CoupangCredentials,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 15.0,
    ) -> None:
        self.creds = creds
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def send(
        self,
        method: str,
        path_with_query: str,
        json_body: Optional[dict] = None,
        extra_headers: Optional[dict[str, str]] = None,
    ) -> requests.Response:
        """서명된 요청 송신. 4xx/5xx 도 ``raise`` 하지 않고 그대로 반환.

        Args:
            method: HTTP method
            path_with_query: ``/v2/api/path?key=value`` 형식 (쿼리스트링 자동 분리)
            json_body: POST/PUT 등의 JSON 페이로드
            extra_headers: 추가 헤더 (Authorization 은 자동 주입)

        Returns:
            ``requests.Response`` — 분류는 호출자가 ``classify_external_response`` 로
        """
        # path 와 query 분리
        if "?" in path_with_query:
            path, query = path_with_query.split("?", 1)
        else:
            path, query = path_with_query, ""

        dt = datetime.now(timezone.utc)
        auth_header = build_authorization_header(
            creds=self.creds, dt=dt, method=method, path=path, query=query,
        )

        headers = {
            "Authorization": auth_header,
            "Content-Type": "application/json;charset=UTF-8",
            "User-Agent": DEFAULT_USER_AGENT,
        }
        if extra_headers:
            headers.update(extra_headers)

        url = self.base_url + path_with_query

        logger.info(
            "[coupang] %s %s vendor_id=%s access_key=%s",
            method.upper(), path, self.creds.vendor_id,
            mask_secret(self.creds.access_key),
        )

        response = requests.request(
            method=method.upper(),
            url=url,
            headers=headers,
            json=json_body,
            timeout=self.timeout,
        )

        logger.info(
            "[coupang] response %s %s — status=%s",
            method.upper(), path, response.status_code,
        )
        return response
