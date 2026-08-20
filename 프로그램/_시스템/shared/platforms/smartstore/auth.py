# -*- coding: utf-8 -*-
"""
스마트스토어 OAuth2 bcrypt 서명 + 토큰 발급 요청 (stateless).

공식 스펙:
    POST https://api.commerce.naver.com/external/v1/oauth2/token
    Content-Type: application/x-www-form-urlencoded
    form: client_id, timestamp, client_secret_sign, grant_type=client_credentials, type=SELF

    client_secret_sign =
        base64(bcrypt.hashpw(f"{client_id}_{timestamp}", client_secret))

역할 경계:
- 서명 생성·단발성 HTTP 호출만.
- 캐싱·락·재시도 없음 → 상위 token_store.py 담당.
"""
from __future__ import annotations

import base64
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import bcrypt
import requests

logger = logging.getLogger(__name__)

# 네이버 Client Secret = bcrypt salt 문자열 ($2a$04$ + base64 22자).
#  ★ bcrypt.hashpw 에 잘못된 salt 를 넘기면 파이썬 예외가 아니라 네이티브에서 죽어
#    워커가 통째로 내려간다(try/except 로 못 잡음 → 원인 없는 빈 502).
#    그래서 bcrypt 를 부르기 '전에' 형식을 검사한다.
#  끝 앵커($) 필수 — 없으면 뒤에 줄바꿈/쓰레기가 붙은 값이 통과해 bcrypt 로 넘어간다.
_BCRYPT_SALT_RE = re.compile(r"^\$2[abxy]?\$\d{2}\$[./A-Za-z0-9]{22}$")


def normalize_client_secret(client_secret: str) -> str:
    """붙여넣기로 섞인 앞뒤 공백·줄바꿈 제거(bcrypt salt 에는 공백이 없다)."""
    return (client_secret or "").strip()


def is_valid_client_secret(client_secret: str) -> bool:
    """bcrypt salt 형식인지. bcrypt 를 부르기 전 판정용."""
    return bool(_BCRYPT_SALT_RE.match(normalize_client_secret(client_secret)))


@dataclass(frozen=True)
class TokenInfo:
    """발급받은 access_token 메타 정보."""
    access_token: str
    expires_at:   int   # UNIX ts (초)
    issued_at:    int


class SmartStoreAuthError(Exception):
    """서명 또는 토큰 발급 실패."""
    def __init__(self, message: str, status_code: Optional[int] = None, payload: Optional[dict] = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload or {}


def build_client_secret_sign(client_id: str, client_secret: str,
                              timestamp_ms: int) -> str:
    """bcrypt 서명 생성.

    Args:
        client_id:      애플리케이션 ID
        client_secret:  애플리케이션 Secret (bcrypt salt 형식 '$2a$04$...')
        timestamp_ms:   13자리 UNIX ms

    Returns:
        base64 로 인코딩된 서명 문자열.

    Raises:
        ValueError: client_id/client_secret 이 비어있거나 bcrypt salt 형식이 아님.
    """
    if not client_id:
        raise ValueError("client_id 가 비어있습니다 (.env 확인)")
    if not client_secret:
        raise ValueError("client_secret 이 비어있습니다 (.env 확인)")
    secret = normalize_client_secret(client_secret)
    if not _BCRYPT_SALT_RE.match(secret):
        # bcrypt 를 아예 부르지 않는다(부르면 워커가 죽는다).
        raise ValueError(
            "client_secret 이 bcrypt salt 형식이 아닙니다 — 네이버 커머스 API 센터의 "
            "Client Secret 을 앞뒤 공백·줄바꿈 없이 '$2a$' 로 시작하는 전체 문자열로 "
            "다시 입력하세요."
        )

    password = f"{client_id}_{timestamp_ms}".encode("utf-8")
    hashed = bcrypt.hashpw(password, secret.encode("utf-8"))
    return base64.standard_b64encode(hashed).decode("utf-8")


def current_timestamp_ms(now: Optional[datetime] = None, skew_sec: int = 0) -> int:
    """13자리 ms timestamp.

    네이버 공식 docs v2.76.0 는 `System.currentTimeMillis()` 를 그대로 사용한다
    (skew 없음). 시계 오차 걱정되는 환경에서는 skew_sec 파라미터로 조정 가능.
    """
    if now is None:
        base = time.time()
    else:
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        base = now.timestamp()
    return int((base - skew_sec) * 1000)


def request_new_token(client_id: str, client_secret: str,
                       endpoint_url: str,
                       http_timeout_sec: int = 10) -> TokenInfo:
    """토큰 발급 HTTP 호출 (단발성). 캐싱·재시도 없음.

    Raises:
        SmartStoreAuthError: 네트워크/HTTP/응답 파싱 실패.
    """
    ts = current_timestamp_ms()
    sign = build_client_secret_sign(client_id, client_secret, ts)
    form = {
        "client_id":          client_id,
        "timestamp":          str(ts),
        "client_secret_sign": sign,
        "grant_type":         "client_credentials",
        "type":               "SELF",
    }
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept":       "application/json",
    }
    try:
        resp = requests.post(endpoint_url, data=form, headers=headers,
                              timeout=http_timeout_sec)
    except requests.RequestException as e:
        raise SmartStoreAuthError(f"네트워크 예외: {e}") from e

    try:
        payload = resp.json()
    except ValueError:
        raise SmartStoreAuthError(
            f"JSON 파싱 실패 status={resp.status_code} body={resp.text[:200]}",
            status_code=resp.status_code,
        )

    if resp.status_code != 200 or "access_token" not in payload:
        code = payload.get("code", "?")
        msg = payload.get("message", resp.text[:200])
        raise SmartStoreAuthError(
            f"토큰 발급 실패 status={resp.status_code} code={code} message={msg}",
            status_code=resp.status_code,
            payload=payload,
        )

    now = int(time.time())
    return TokenInfo(
        access_token = payload["access_token"],
        issued_at    = now,
        expires_at   = now + int(payload.get("expires_in", 10000)),
    )
