"""롯데온 Open API(셀러센터) Bearer client — dispatcher 계층.

롯데온 인증(공개 문서 실측):
  · 판매자 센터 발급 **정적 인증키**를 ``Authorization: Bearer {키}`` 로 전달.
  · 토큰 교환·HMAC 서명 없음.
  · 필수 헤더 Accept/Accept-Language/X-Timezone/Content-Type.
  · 출발지 IP 는 인증키에 등록된 IP 만(미등록 403).

레퍼런스: https://api.lotteon.com/apiService/?apiNm=GetStarted

주의: HTTP 파이프라인(rate limit·재시도)은 shared/platforms/lotteon/client.py 가 담당.
      본 client 는 dispatcher(계정→client) 캐시 계층의 얇은 요청 송신기.
"""
from __future__ import annotations

import logging
from typing import Optional

import requests

from lemouton.auth.secrets import LotteonCredentials, mask_secret

logger = logging.getLogger(__name__)


DEFAULT_BASE_URL = "https://openapi.lotteon.com"
DEFAULT_USER_AGENT = "LemoutonStockManager/2.0 (+https://lemouton.co.kr)"


def build_headers(creds: LotteonCredentials) -> dict[str, str]:
    """롯데온 필수 요청 헤더 (Bearer 인증키 포함)."""
    return {
        "Authorization": f"Bearer {creds.api_key}",
        "Accept": "application/json",
        "Accept-Language": "ko",
        "X-Timezone": "GMT+09:00",
        "Content-Type": "application/json",
        "User-Agent": DEFAULT_USER_AGENT,
    }


class LotteonApiClient:
    """롯데온 Open API client. 호출마다 Bearer 헤더 자동 주입.

    Args:
        creds: ``LotteonCredentials`` (api_key, tr_no)
        base_url: 기본 https://openapi.lotteon.com
        timeout: 요청 타임아웃 (초)
    """

    def __init__(
        self,
        creds: LotteonCredentials,
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
        json_body: Optional[dict] = None,
        extra_headers: Optional[dict[str, str]] = None,
    ) -> requests.Response:
        """요청 송신. 4xx/5xx 도 raise 하지 않고 그대로 반환.

        Args:
            method: HTTP method (롯데온은 GET/POST 만 지원)
            path: ``/v1/openapi/product/...`` (쿼리 포함 가능)
            json_body: POST JSON 페이로드
            extra_headers: 추가 헤더 (Authorization 은 자동 주입)
        """
        headers = build_headers(self.creds)
        if extra_headers:
            headers.update(extra_headers)

        url = self.base_url + path

        logger.info(
            "[lotteon] %s %s tr_no=%s api_key=%s",
            method.upper(), path, self.creds.tr_no,
            mask_secret(self.creds.api_key),
        )

        response = requests.request(
            method=method.upper(),
            url=url,
            headers=headers,
            json=json_body,
            timeout=self.timeout,
        )

        logger.info(
            "[lotteon] response %s %s — status=%s",
            method.upper(), path, response.status_code,
        )
        return response
