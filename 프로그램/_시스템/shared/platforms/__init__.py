# -*- coding: utf-8 -*-
"""[E] Vendored platform clients (Coupang/Smartstore) — config 어댑터.

원본: C:/Users/seung/모음전 자동화/modules/platforms/

이 모듈은 vendored 코드가 `from shared.platforms import COUPANG, SMARTSTORE, NOTIFIER, MONITOR` 로
환경 설정을 끌어다 쓰게 한다. 르무통 프로젝트에는 별도 config.py(Config 클래스)만 있으므로
vendored 코드가 기대하는 dict 형태의 설정을 여기서 직접 제공한다.

값의 출처는 환경변수. 실제 운영 시에는 .env 또는 시스템 환경변수에서 로딩되며,
누락 시 빈 문자열 / 합리적 기본값이 들어간다.
"""
from __future__ import annotations

import os
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_CACHE_DIR = _PROJECT_ROOT / "data" / "platform_cache"


# ──────────────────────────────────────────────────────────────
# 쿠팡
# ──────────────────────────────────────────────────────────────
COUPANG: dict = {
    "base_url": os.environ.get("COUPANG_BASE_URL", "https://api-gateway.coupang.com"),
    "access_key": os.environ.get("COUPANG_ACCESS_KEY", ""),
    "secret_key": os.environ.get("COUPANG_SECRET_KEY", ""),
    "vendor_id": os.environ.get("COUPANG_VENDOR_ID", ""),

    # 클라이언트 동작 파라미터
    "rate_limit_per_sec": float(os.environ.get("COUPANG_RATE_LIMIT_PER_SEC", "5")),
    "max_retries": int(os.environ.get("COUPANG_MAX_RETRIES", "3")),
    "retry_backoff_sec": float(os.environ.get("COUPANG_RETRY_BACKOFF_SEC", "2")),
    "request_timeout_sec": float(os.environ.get("COUPANG_REQUEST_TIMEOUT_SEC", "30")),

    # 가격 정책
    "price_unit": 10,
    "price_change": {
        "auto_force": False,
        "alert_on_limit_hit": True,
    },

    # API 엔드포인트 (path templates)
    "paths": {
        "create_product": (
            "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products"
        ),
        "get_product": (
            "/v2/providers/seller_api/apis/api/v1/marketplace"
            "/seller-products/{sellerProductId}"
        ),
        "update_price": (
            "/v2/providers/seller_api/apis/api/v1/marketplace"
            "/vendor-items/{vendorItemId}/prices/{price}"
        ),
        "update_quantity": (
            "/v2/providers/seller_api/apis/api/v1/marketplace"
            "/vendor-items/{vendorItemId}/quantities/{quantity}"
        ),
        "inflow_status": (
            "/v2/providers/seller_api/apis/api/v1/marketplace"
            "/seller-products/inflow-status"
        ),
        # 매출내역(정산 예정금액) 조회 — settlements.py 사용. (누락돼 있던 경로 추가)
        "revenue_history": "/v2/providers/openapi/apis/api/v1/revenue-history",
    },
}


# ──────────────────────────────────────────────────────────────
# 스마트스토어
# ──────────────────────────────────────────────────────────────
SMARTSTORE: dict = {
    "base_url": os.environ.get("SMARTSTORE_BASE_URL", "https://api.commerce.naver.com"),
    "client_id": os.environ.get("SMARTSTORE_MAIN_CLIENT_ID") or os.environ.get("SMARTSTORE_CLIENT_ID", ""),
    "client_secret": os.environ.get("SMARTSTORE_MAIN_CLIENT_SECRET") or os.environ.get("SMARTSTORE_CLIENT_SECRET", ""),

    # 토큰 캐시
    "token_cache_path": os.environ.get(
        "SMARTSTORE_TOKEN_CACHE_PATH",
        str(_DEFAULT_CACHE_DIR / "smartstore_token.json"),
    ),
    "token_lock_path": os.environ.get(
        "SMARTSTORE_TOKEN_LOCK_PATH",
        str(_DEFAULT_CACHE_DIR / "smartstore_token.lock"),
    ),
    "token_refresh_margin_sec": int(os.environ.get("SMARTSTORE_TOKEN_REFRESH_MARGIN_SEC", "600")),
    "token_lock_acquire_timeout_sec": int(
        os.environ.get("SMARTSTORE_TOKEN_LOCK_ACQUIRE_TIMEOUT_SEC", "10")
    ),

    # rate limit
    "initial_rate_per_sec": float(os.environ.get("SMARTSTORE_INITIAL_RATE_PER_SEC", "5")),
    "min_rate_per_sec": float(os.environ.get("SMARTSTORE_MIN_RATE_PER_SEC", "0.5")),
    "max_rate_per_sec": float(os.environ.get("SMARTSTORE_MAX_RATE_PER_SEC", "20")),
    "rate_safety_margin": float(os.environ.get("SMARTSTORE_RATE_SAFETY_MARGIN", "0.1")),
    "rate_limit_hit_alert_threshold": int(
        os.environ.get("SMARTSTORE_RATE_LIMIT_HIT_ALERT_THRESHOLD", "10")
    ),

    # 재시도
    "max_retries": int(os.environ.get("SMARTSTORE_MAX_RETRIES", "3")),
    "retry_backoff_sec": float(os.environ.get("SMARTSTORE_RETRY_BACKOFF_SEC", "2")),
    "request_timeout_sec": float(os.environ.get("SMARTSTORE_REQUEST_TIMEOUT_SEC", "30")),

    # API 엔드포인트
    "paths": {
        "token": "/external/v1/oauth2/token",
        "change_sale_status": (
            "/external/v1/products/origin-products/{originProductNo}/change-status"
        ),
        "create_product": "/external/v2/products",
        "delete_origin_product": "/external/v2/products/origin-products/{originProductNo}",
    },
}


# ──────────────────────────────────────────────────────────────
# 롯데온 (LOTTE ON Open API, 셀러센터)
#   근거: docs/markets/lotteon.yaml (API 센터 공개 개발가이드 실측 2026-07-05)
#   인증 = 정적 Bearer 인증키. trNo(거래처번호) 는 모든 상품/가격/재고 호출 필수.
# ──────────────────────────────────────────────────────────────
LOTTEON: dict = {
    "base_url": os.environ.get("LOTTEON_BASE_URL", "https://openapi.lotteon.com"),
    "api_key": os.environ.get("LOTTEON_MAIN_API_KEY", ""),
    "tr_no": os.environ.get("LOTTEON_MAIN_TR_NO", ""),
    "tr_grp_cd": os.environ.get("LOTTEON_TR_GRP_CD", "SR"),   # 일반셀러 상수
    "lrtr_no": os.environ.get("LOTTEON_MAIN_LRTR_NO", ""),    # 하위거래처(선택, 미사용 시 빈값)

    # 클라이언트 동작 파라미터
    #   문서 상한 = 분당 10,000회(≈166/s). 보수적으로 기본 50/s.
    "rate_limit_per_sec": float(os.environ.get("LOTTEON_RATE_LIMIT_PER_SEC", "50")),
    "max_retries": int(os.environ.get("LOTTEON_MAX_RETRIES", "3")),
    "retry_backoff_sec": float(os.environ.get("LOTTEON_RETRY_BACKOFF_SEC", "2")),
    "request_timeout_sec": float(os.environ.get("LOTTEON_REQUEST_TIMEOUT_SEC", "30")),

    # API 엔드포인트 (모두 POST, JSON)
    "paths": {
        "detail": "/v1/openapi/product/v1/product/detail",
        "price_change": "/v1/openapi/product/v1/item/price/change",
        "stock_change": "/v1/openapi/product/v1/item/stock/change",
        "identity": "/v1/openapi/common/v1/identity",
    },
}


# ──────────────────────────────────────────────────────────────
# 11번가 (11st 셀러 Open API)
#   근거: docs/markets/eleven11.yaml (공개 개발문서 실측 2026-07-06).
#   인증 = 셀러오피스 발급 OPENAPI KEY 를 'openapikey' 헤더로 전달(단일 키·시크릿 없음).
#   포맷 = XML(요청·응답). 출발지 IP 를 API 센터에 등록해야 통과.
#   ⚠️ 셀러 REST 엔드포인트(상품/재고/가격) 경로·XML 필드 스펙은 로그인 게이트 안 →
#      미확보(paths=TODO). products/prices/inventory 는 스펙 확보 후 구현(추측 금지).
# ──────────────────────────────────────────────────────────────
ELEVEN11: dict = {
    # 셀러 REST API 베이스(공개 문서상 셀러 API 호스트). 확정 스펙 확보 시 갱신.
    "base_url": os.environ.get("ELEVEN11_BASE_URL", "https://api.11st.co.kr"),
    "openapi_key": os.environ.get("ELEVEN11_MAIN_OPENAPI_KEY", ""),

    # 클라이언트 동작 파라미터 (보수적 기본값)
    "rate_limit_per_sec": float(os.environ.get("ELEVEN11_RATE_LIMIT_PER_SEC", "5")),
    "max_retries": int(os.environ.get("ELEVEN11_MAX_RETRIES", "3")),
    "retry_backoff_sec": float(os.environ.get("ELEVEN11_RETRY_BACKOFF_SEC", "2")),
    "request_timeout_sec": float(os.environ.get("ELEVEN11_REQUEST_TIMEOUT_SEC", "30")),

    # API 엔드포인트 (셀러 REST) — ⚠️ 로그인 게이트로 미확보. 스펙 확보 후 채움(추측 금지).
    "paths": {
        "detail": None,        # 상품/옵션 상세조회 (기존 상품 연동)
        "price_change": None,  # 가격 수정
        "stock_change": None,  # 재고 수정
    },
}


# ──────────────────────────────────────────────────────────────
# 옥션·G마켓 (ESM 2.0 · 이베이코리아) 통합 셀러 API
# 인증 = JWT(HmacSHA256): header.kid=master_id, payload.ssi="{site}:{seller_id}"
#   (site: 옥션 "A" / G마켓 "G"), payload.aud="sa.esmplus.com", secret_key 로 서명.
# 옥션·G마켓은 같은 ESM+ 마스터 계정 → master_id·secret_key 공통, seller_id·site 만 다름.
# 주문조회 = POST https://sa2.esmplus.com/shipping/v1/Order/RequestOrders (공개문서 etapi.gmarket.com/67).
#   Authorization: Bearer {JWT}. 상품/정산 엔드포인트는 미확보 → None(추측 금지).
# ──────────────────────────────────────────────────────────────
_ESM_COMMON: dict = {
    # 실 API 호스트(sa2.esmplus.com) — etapi.gmarket.com 은 '문서' 호스트라 호출용 아님.
    "base_url": os.environ.get("ESM_BASE_URL", "https://sa2.esmplus.com"),
    "auth_audience": "sa.esmplus.com",   # JWT payload.aud (고정)
    "auth_issuer": os.environ.get("ESM_AUTH_ISSUER", "www.esmplus.com"),  # JWT payload.iss (발행자 도메인)
    "auth_alg": "HS256",
    "rate_limit_per_sec": float(os.environ.get("ESM_RATE_LIMIT_PER_SEC", "5")),
    "order_min_interval_sec": float(os.environ.get("ESM_ORDER_MIN_INTERVAL_SEC", "5")),  # 주문조회 5초당 1회
    "max_retries": int(os.environ.get("ESM_MAX_RETRIES", "3")),
    "retry_backoff_sec": float(os.environ.get("ESM_RETRY_BACKOFF_SEC", "2")),
    "request_timeout_sec": float(os.environ.get("ESM_REQUEST_TIMEOUT_SEC", "30")),
    "paths": {
        "orders": "/shipping/v1/Order/RequestOrders",  # 주문조회(공개문서 확보)
        "settlement": None,    # 정산 조회 — 미확보
        "detail": None,        # 상품/옵션 상세 — 미확보
        "price_change": None,  # 가격 수정 — 미확보
        "stock_change": None,  # 재고 수정 — 미확보
    },
}

AUCTION: dict = {
    **_ESM_COMMON,
    "site_id": "A",   # ESM payload ssi 앞자리(옥션)
    "master_id": os.environ.get("AUCTION_MAIN_MASTER_ID", ""),
    "secret_key": os.environ.get("AUCTION_MAIN_SECRET_KEY", ""),
    "seller_id": os.environ.get("AUCTION_MAIN_SELLER_ID", ""),
}

GMARKET: dict = {
    **_ESM_COMMON,
    "site_id": "G",   # ESM payload ssi 앞자리(G마켓)
    "master_id": os.environ.get("GMARKET_MAIN_MASTER_ID", ""),
    "secret_key": os.environ.get("GMARKET_MAIN_SECRET_KEY", ""),
    "seller_id": os.environ.get("GMARKET_MAIN_SELLER_ID", ""),
}


# ──────────────────────────────────────────────────────────────
# Notifier (vendored shared/notifier.py 가 참조)
# ──────────────────────────────────────────────────────────────
NOTIFIER: dict = {
    "retry_count": int(os.environ.get("NOTIFIER_RETRY_COUNT", "3")),
    "retry_timeout_sec": float(os.environ.get("NOTIFIER_RETRY_TIMEOUT_SEC", "10")),
    "카카오톡": {
        "enabled": os.environ.get("NOTIFIER_KAKAO_ENABLED", "0") == "1",
        "access_token": os.environ.get("KAKAO_ACCESS_TOKEN", ""),
        "api_url": os.environ.get(
            "KAKAO_API_URL",
            "https://kapi.kakao.com/v2/api/talk/memo/default/send",
        ),
    },
    "슬랙": {
        "enabled": os.environ.get("NOTIFIER_SLACK_ENABLED", "0") == "1",
        "webhook_url": os.environ.get("SLACK_WEBHOOK_URL", ""),
    },
}


# ──────────────────────────────────────────────────────────────
# Monitor / AdaptiveCrawlMonitor (vendored shared/adaptive_interval.py 가 참조)
# ──────────────────────────────────────────────────────────────
MONITOR: dict = {
    "초기간격_초": float(os.environ.get("MONITOR_INITIAL_INTERVAL_SEC", "5")),
    "최소간격_초": float(os.environ.get("MONITOR_MIN_INTERVAL_SEC", "1")),
    "최대간격_초": float(os.environ.get("MONITOR_MAX_INTERVAL_SEC", "60")),
    "에러율_임계값": float(os.environ.get("MONITOR_ERROR_RATE_THRESHOLD", "0.3")),
    "차단_쿨다운_초": float(os.environ.get("MONITOR_BLOCK_COOLDOWN_SEC", "300")),
    "최근기록_윈도우": int(os.environ.get("MONITOR_RECENT_WINDOW", "100")),
}


__all__ = ["COUPANG", "SMARTSTORE", "LOTTEON", "ELEVEN11", "AUCTION", "GMARKET", "NOTIFIER", "MONITOR"]
