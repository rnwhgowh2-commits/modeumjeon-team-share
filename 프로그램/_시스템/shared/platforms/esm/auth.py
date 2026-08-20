# -*- coding: utf-8 -*-
"""ESM 2.0(옥션·G마켓) JWT 인증 — HmacSHA256 서명.

근거(공개문서 etapi.gmarket.com/pages/API-가이드, 2026-07-07 실측):
  header  = {"alg":"HS256","typ":"JWT","kid": <ESM+ 마스터ID>}
  payload = {"iss": <발행자 도메인>, "sub":"sell", "aud":"sa.esmplus.com",
             "ssi": "<site>:<seller_id>"}   # site: 옥션 "A" / G마켓 "G"
  signature = HmacSHA256(base64url(header)+"."+base64url(payload), secret_key)
  전송     = "Authorization: Bearer <jwt>"

키/시크릿 없이도 서명 로직은 결정적(단위테스트 가능). iat/exp 는 문서상 필수 아님(iat 선택).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json


def _b64url(raw: bytes) -> str:
    """base64url(패딩 '=' 제거) — JWT 규격."""
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def build_jwt(master_id: str, secret_key: str, site_id: str, seller_id: str,
              issuer: str = "www.esmplus.com", audience: str = "sa.esmplus.com",
              iat: int | None = None) -> str:
    """ESM JWT 문자열 생성. 필수값 누락 시 ValueError(추측 서명 금지)."""
    if not (master_id and secret_key and site_id and seller_id):
        raise ValueError("ESM JWT 필수값 누락 (master_id·secret_key·site_id·seller_id)")
    header = {"alg": "HS256", "typ": "JWT", "kid": master_id}
    payload = {"iss": issuer, "sub": "sell", "aud": audience,
               "ssi": f"{site_id}:{seller_id}"}
    if iat is not None:
        payload["iat"] = int(iat)
    seg = (_b64url(json.dumps(header, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
           + "." +
           _b64url(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")))
    sig = hmac.new(secret_key.encode("utf-8"), seg.encode("ascii"), hashlib.sha256).digest()
    return seg + "." + _b64url(sig)


def build_headers(master_id: str, secret_key: str, site_id: str, seller_id: str,
                  issuer: str = "www.esmplus.com", audience: str = "sa.esmplus.com",
                  iat: int | None = None) -> dict:
    """ESM API 요청 헤더 — Authorization: Bearer {JWT} + JSON."""
    token = build_jwt(master_id, secret_key, site_id, seller_id,
                      issuer=issuer, audience=audience, iat=iat)
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
