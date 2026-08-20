# -*- coding: utf-8 -*-
"""11번가(11st) 셀러 Open API 클라이언트 패키지.

근거: 11번가 OPEN API CENTER 공개 개발문서 실측(2026-07-06).
    · 인증 = 셀러오피스 발급 OPENAPI KEY 를 ``openapikey: {키}`` 헤더로 전달
      (OAuth 토큰교환·HMAC 서명·시크릿 없음).
    · 포맷 = XML(요청·응답).  · 출발지 IP 를 API 센터에 등록해야 통과.
정본 스펙: docs/markets/eleven11.yaml.
롯데온 패키지(shared/platforms/lotteon) 구조를 대칭으로 미러.

⚠️ 셀러 REST 엔드포인트(상품/재고/가격) 경로·XML 필드 스펙은 로그인 게이트 안이라
   미확보. products/prices/inventory 의 실제 호출 로직은 스펙 확보 후 채운다(추측 금지,
   CLAUDE.md 3대 원칙). auth/client 는 인증·전송 계층이라 지금 구현 가능.
"""
