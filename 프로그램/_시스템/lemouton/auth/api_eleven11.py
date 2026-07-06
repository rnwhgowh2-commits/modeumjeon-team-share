"""11번가(11st) 셀러 Open API client — dispatcher 계층.

11번가 인증(공개 문서 실측 2026-07-06):
  · 셀러오피스 발급 **OPENAPI KEY** 를 ``openapikey: {키}`` 헤더로 전달.
  · 토큰 교환·서명 없음.  · 요청/응답 = XML.
  · 출발지 IP 는 API 센터에 등록된 IP 만(미등록 차단).

레퍼런스: https://openapi.11st.co.kr/openapi/OpenApiOperationGuide.tmall

주의: HTTP 파이프라인(rate limit·재시도)은 shared/platforms/eleven11/client.py 가 담당.
      본 client 는 dispatcher(계정→client) 캐시 계층의 얇은 요청 송신기.
"""
from __future__ import annotations

import logging
from typing import Optional

import requests

from lemouton.auth.secrets import Eleven11Credentials, mask_secret

logger = logging.getLogger(__name__)


DEFAULT_BASE_URL = "https://api.11st.co.kr"
DEFAULT_USER_AGENT = "LemoutonStockManager/2.0 (+https://lemouton.co.kr)"


def build_headers(creds: Eleven11Credentials) -> dict[str, str]:
    """11번가 필수 요청 헤더 (openapikey 포함)."""
    return {
        "openapikey": creds.openapi_key,
        "Accept": "application/xml",
        "Content-Type": "application/xml; charset=euc-kr",
        "User-Agent": DEFAULT_USER_AGENT,
    }


class Eleven11ApiClient:
    """11번가 Open API client. 호출마다 openapikey 헤더 자동 주입.

    Args:
        creds: ``Eleven11Credentials`` (openapi_key)
        base_url: 기본 https://api.11st.co.kr
        timeout: 요청 타임아웃 (초)
    """

    def __init__(
        self,
        creds: Eleven11Credentials,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 15.0,
    ) -> None:
        self.creds = creds
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def send(
        self,
        method: str,
        path: str,
        body: Optional[str] = None,
        extra_headers: Optional[dict[str, str]] = None,
    ) -> requests.Response:
        """요청 송신. 4xx/5xx 도 raise 하지 않고 그대로 반환.

        Args:
            method: HTTP method
            path: 엔드포인트 경로 (쿼리 포함 가능)
            body: XML 요청 본문(str)
            extra_headers: 추가 헤더 (openapikey 는 자동 주입)
        """
        headers = build_headers(self.creds)
        if extra_headers:
            headers.update(extra_headers)

        url = self.base_url + path

        logger.info(
            "[eleven11] %s %s openapikey=%s",
            method.upper(), path, mask_secret(self.creds.openapi_key),
        )

        response = requests.request(
            method=method.upper(),
            url=url,
            headers=headers,
            data=body.encode("euc-kr") if isinstance(body, str) else body,
            timeout=self.timeout,
        )

        logger.info(
            "[eleven11] response %s %s — status=%s",
            method.upper(), path, response.status_code,
        )
        return response
