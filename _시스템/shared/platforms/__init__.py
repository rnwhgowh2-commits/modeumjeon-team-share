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


__all__ = ["COUPANG", "SMARTSTORE", "NOTIFIER", "MONITOR"]
