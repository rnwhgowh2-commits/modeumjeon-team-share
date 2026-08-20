# -*- coding: utf-8 -*-
"""
롯데온 Open API 인증 헤더 생성.

근거(공개 문서 실측): https://api.lotteon.com/apiService/?apiNm=GetStarted
    · 인증 = 판매자 센터에서 발급한 **정적 인증키**를 Bearer 로 전달 (토큰교환·서명 없음).
    · 필수 헤더:
        Authorization  : Bearer {인증키}
        Accept         : application/json
        Accept-Language: ko
        X-Timezone     : GMT+09:00
        Content-Type   : application/json  (POST 필수)
    · 출발지 IP 는 인증키에 등록된 IP 만 통과(미등록 403) — 헤더가 아니라 서버측 IP 등록.

역할: 헤더 조립만. HTTP 호출·비즈니스 로직 금지.
"""
from __future__ import annotations


def build_headers(api_key: str) -> dict:
    """롯데온 Open API 필수 헤더를 구성한다.

    Args:
        api_key: 판매자 센터에서 발급받은 인증키 (절대 로그에 남기지 말 것)

    Returns:
        요청 헤더 dict

    Raises:
        ValueError: api_key 가 비어있을 때.
    """
    if not api_key:
        raise ValueError("api_key(LOTTEON_MAIN_API_KEY) 가 비어있습니다 (.env 확인)")
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "Accept-Language": "ko",
        "X-Timezone": "GMT+09:00",
        "Content-Type": "application/json",
    }
