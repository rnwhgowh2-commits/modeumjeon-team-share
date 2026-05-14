# -*- coding: utf-8 -*-
"""
쿠팡 Open API HMAC-SHA256 서명 생성

공식 문서: https://developers.coupangcorp.com/hc/ko/articles/360033461914

포맷:
    datetime      = "YYMMDDTHHMMSSZ"  (UTC)
    message       = datetime + METHOD + PATH + QUERY   (물음표 없이 연결)
    signature     = HMAC-SHA256(secret_key, message).hexdigest()
    Authorization = "CEA algorithm=HmacSHA256, access-key={AK}, signed-date={dt}, signature={sig}"

역할: 서명 생성만. HTTP 호출·비즈니스 로직 금지.
"""
from __future__ import annotations

import hmac
import hashlib
from datetime import datetime, timezone
from typing import Optional


_DT_FORMAT = "%y%m%dT%H%M%SZ"


def _format_datetime(now: Optional[datetime] = None) -> str:
    """현재(또는 지정) UTC 시각을 쿠팡 규격 문자열로 반환.

    쿠팡 공식 Python 예제 기준: `time.strftime('%y%m%d')+'T'+time.strftime('%H%M%S')+'Z'`
    → 동등한 표현을 UTC aware datetime 으로 생성한다.
    """
    dt = now or datetime.now(timezone.utc)
    # tz 정보가 없으면 UTC 로 간주한다 (테스트 용이성).
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime(_DT_FORMAT)


def _build_message(datetime_str: str, method: str, path: str, query: str) -> str:
    """서명 대상 문자열 조합.

    QUERY 가 '?' 로 시작하면 제거한 후 연결한다 (공식 예제는 '?' 없이 전달).
    """
    q = query.lstrip("?") if query else ""
    return f"{datetime_str}{method.upper()}{path}{q}"


def _sign(secret_key: str, message: str) -> str:
    """HMAC-SHA256 서명 hexdigest."""
    return hmac.new(
        secret_key.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def build_authorization(
    method: str,
    path: str,
    query: str,
    access_key: str,
    secret_key: str,
    now: Optional[datetime] = None,
) -> str:
    """쿠팡 Open API `Authorization` 헤더 값을 완성한다.

    Args:
        method: HTTP 메서드 ("GET", "POST", "PUT", "DELETE")
        path: 엔드포인트 경로 (예: "/v2/providers/seller_api/.../seller-products")
        query: 쿼리 문자열 ("key=val&..." 또는 빈 문자열). 앞의 '?' 는 제거됨.
        access_key: 발급받은 Access Key
        secret_key: 발급받은 Secret Key (절대 로그에 남기지 말 것)
        now: 테스트·재현용 UTC datetime. 미지정 시 현재 시각 사용.

    Returns:
        "CEA algorithm=HmacSHA256, access-key=..., signed-date=..., signature=..."

    Raises:
        ValueError: access_key 또는 secret_key 가 비어있을 때.
    """
    if not access_key:
        raise ValueError("access_key 가 비어있습니다 (.env 확인)")
    if not secret_key:
        raise ValueError("secret_key 가 비어있습니다 (.env 확인)")

    dt_str = _format_datetime(now)
    message = _build_message(dt_str, method, path, query)
    signature = _sign(secret_key, message)

    return (
        "CEA algorithm=HmacSHA256, "
        f"access-key={access_key}, "
        f"signed-date={dt_str}, "
        f"signature={signature}"
    )
