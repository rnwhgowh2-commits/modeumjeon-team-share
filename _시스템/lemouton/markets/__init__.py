"""markets — 마켓별 client 라우팅 (Phase 2-B).

``UploadAccount`` 의 ``market`` 필드를 보고 적절한 client 를 반환:
  · ``smartstore`` → :class:`lemouton.auth.oauth_smartstore.SmartstoreOAuthClient`
  · ``coupang``    → :class:`lemouton.auth.api_coupang.CoupangApiClient`

시크릿 로드는 ``auth.secrets`` 에 위임 — 본 모듈은 라우팅 + 캐시만 담당.
"""
from __future__ import annotations
