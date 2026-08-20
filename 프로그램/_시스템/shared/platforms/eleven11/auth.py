# -*- coding: utf-8 -*-
"""
11번가 Open API 인증 헤더 생성.

근거(공개 문서 실측): https://openapi.11st.co.kr/openapi/OpenApiOperationGuide.tmall
    · 인증 = 셀러오피스에서 발급한 **OPENAPI KEY** 를 ``openapikey`` 헤더로 전달.
      (토큰 교환·서명 없음. "openapikey:발급key값" 형태.)
    · 포맷 = XML → Accept/Content-Type 은 application/xml.
    · 출발지 IP 는 API 센터에 등록된 IP 만 통과(미등록 차단) — 헤더가 아니라 서버측 IP 등록.

역할: 헤더 조립만. HTTP 호출·비즈니스 로직 금지.
"""
from __future__ import annotations


def build_headers(openapi_key: str) -> dict:
    """11번가 Open API 필수 헤더를 구성한다.

    Args:
        openapi_key: 셀러오피스에서 발급받은 OPENAPI KEY (절대 로그에 남기지 말 것)

    Returns:
        요청 헤더 dict

    Raises:
        ValueError: openapi_key 가 비어있을 때.
    """
    if not openapi_key:
        raise ValueError("openapi_key(ELEVEN11_MAIN_OPENAPI_KEY) 가 비어있습니다 (.env 확인)")
    return {
        "openapikey": openapi_key,
        "Accept": "application/xml",
        # 11번가 레거시 XML API는 POST 본문에 text/xml 을 요구(application/xml 은 415 거부).
        #   라이브 확인(2026-07-17 prodmarket/stocks 415→text/xml). GET 은 client 가 제거.
        "Content-Type": "text/xml; charset=euc-kr",
    }
