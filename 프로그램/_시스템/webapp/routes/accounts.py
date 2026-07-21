"""[E] 계정 관리 페이지 — V2 멀티 계정 시스템.

라우트:
  · GET /accounts/upload   — UploadAccount 목록 (스마트스토어/쿠팡 셀러 계정)
  · GET /accounts/sourcing — SourcingAccount 목록 (무신사/SSF 회원 세션)
  · POST /accounts/wizard/start — 자동 로그인 위저드 시작 (Phase 2-C 진입점)

데이터 출처: 모두 V2 모델 (lemouton.sourcing.models_v2). V1 잔존 데이터와 분리.
"""
from __future__ import annotations

import logging
import os
import re

from flask import Blueprint, jsonify, render_template, request

logger = logging.getLogger(__name__)

from lemouton.auth import secrets as S
from lemouton.sourcing.models_v2 import SourcingAccount, UploadAccount
from shared.db import SessionLocal

bp = Blueprint("accounts", __name__, url_prefix="/accounts")



def _LIVE_VERIFIABLE_MARKETS() -> set:
    """라이브 검증으로 열 수 있는 마켓. order_export 단일 원천(지연 임포트)."""
    try:
        from lemouton.markets import order_export as _oe
        return set(_oe.LIVE_VERIFIABLE)
    except Exception:  # noqa: BLE001
        return set()


# ─── 팀공유 모드: admin 전용 (시크릿·API키 노출 위험). 기존 모드 통과. ───
@bp.before_request
def _admin_only():
    import os
    if os.environ.get("ENVIRONMENT") != "team-share-dev":
        return None
    from webapp.auth.permissions import enforce_admin
    return enforce_admin()


# ──────────────────────────────────────────────────────────
#  /accounts/upload — 마켓 셀러 계정
# ──────────────────────────────────────────────────────────


@bp.route("/upload")
def upload_accounts_view():
    """판매처 (마켓) 계정 — UploadAccount 목록.

    각 계정의 ``env_prefix`` 시크릿 존재 여부도 함께 표시 (마스킹).
    """
    from lemouton.auth.profile_store import default_store as _profile_store
    from datetime import datetime
    import sqlite3, shutil, tempfile
    profile_store = _profile_store()

    # 마켓별 영구 인증 쿠키 검사 SQL
    # smartstore: NID_AUT 등 Naver 영구 쿠키 + sell.smartstore / commerce 도메인의 is_persistent=1
    # coupang: wing.coupang.com 도메인의 is_persistent=1 쿠키 (WING-USER-* / accessToken 등)
    _AUTH_COOKIE_SQL = {
        "smartstore": (
            "SELECT 1 FROM cookies WHERE "
            "  (host_key LIKE '%naver.com' AND name IN ('NID_AUT','NID_SES','NID_JKL','NID_EOR','NID_PSI')) "
            "  OR (host_key LIKE '%sell.smartstore.naver.com' AND is_persistent = 1) "
            "  OR (host_key LIKE '%.commerce.naver.com' AND is_persistent = 1 AND name NOT IN ('NEONB')) "
            "LIMIT 1"
        ),
        "coupang": (
            "SELECT 1 FROM cookies WHERE "
            "  host_key LIKE '%wing.coupang.com' AND is_persistent = 1 "
            "LIMIT 1"
        ),
    }
    # 마켓별 LocalStorage 흔적 키 (세션 only 신호)
    _SESSION_TRACE_TOKEN = {
        "smartstore": "sell.smartstore.naver.com",
        "coupang": "wing.coupang.com",
    }

    def _has_persistent_auth_cookie(profile_dir, market: str) -> bool:
        """진짜 영구 인증 쿠키 존재 여부 — 마켓별 SQL 분기.

        smartstore: Naver [로그인 상태 유지] path 만 영구 쿠키 발급.
        coupang: Wing 로그인 시 wing.coupang.com 도메인에 영구 쿠키 저장.
        """
        sql = _AUTH_COOKIE_SQL.get(market)
        if sql is None:
            return False
        for sub in ("Default/Network/Cookies", "Default/Cookies"):
            src = profile_dir / sub
            if not src.exists():
                continue
            try:
                tmp = tempfile.mktemp(suffix=".db")
                shutil.copy(src, tmp)
                try:
                    con = sqlite3.connect(tmp)
                    cur = con.cursor()
                    cur.execute(sql)
                    if cur.fetchone() is not None:
                        return True
                finally:
                    try: con.close()
                    except: pass
                    try: os.unlink(tmp)
                    except: pass
            except (PermissionError, sqlite3.DatabaseError, OSError):
                continue
        return False

    def _has_session_trace(profile_dir, market: str) -> bool:
        """과거 로그인 흔적 — LocalStorage 에 마켓 도메인 데이터 다량 있음.

        세션 살아있다는 보장은 없음. 단순히 "한 번이라도 로그인했었다" 의 신호.
        """
        token = _SESSION_TRACE_TOKEN.get(market)
        if token is None:
            return False
        ls_dir = profile_dir / "Default" / "Local Storage" / "leveldb"
        if not ls_dir.exists():
            return False
        try:
            for f in ls_dir.iterdir():
                if not f.is_file() or f.name in ("LOCK", "CURRENT"):
                    continue
                try:
                    data = f.read_bytes()
                except (PermissionError, OSError):
                    continue
                text = data.decode("utf-8", errors="replace").lower()
                if text.count(token) >= 10:
                    return True
        except (PermissionError, OSError):
            pass
        return False

    s = SessionLocal()
    try:
        accounts = s.query(UploadAccount).all()

        rows = []
        for acc in accounts:
            try:
                creds = S.load_credentials(market=acc.market, env_prefix=acc.env_prefix)
                cred_status = "✅ 등록"
                cred_state = "ok"
                missing_count = 0
                masked_id = _first_field_masked(creds)
            except S.SecretsMissingError as e:
                cred_status = f"⚠️ 누락 ({len(e.missing_keys)} 키)"
                cred_state = "missing"
                missing_count = len(e.missing_keys)
                masked_id = "—"
            except S.SecretsUnknownMarketError:
                cred_status = "❌ 미지원 market"
                cred_state = "unknown"
                missing_count = 0
                masked_id = "—"

            # 자동 로그인용 LOGIN_ID/PW 등록 여부
            has_login_creds = bool(
                os.environ.get(f"{acc.env_prefix}_LOGIN_ID")
                and os.environ.get(f"{acc.env_prefix}_LOGIN_PW")
            )

            # 영구 로그인 (Playwright user_data_dir) 상태 — 실 인증 쿠키 검사
            login_state = "n/a"
            login_status = "—"
            login_age = None
            if acc.market in ("smartstore", "coupang"):
                profile_dir = profile_store.profile_dir(acc.market, acc.env_prefix)
                if not profile_store.has_profile(acc.market, acc.env_prefix):
                    login_state = "not_logged_in"
                    login_status = "⚪ 로그인 안됨"
                elif _has_persistent_auth_cookie(profile_dir, acc.market):
                    cookies_path = profile_dir / "Default" / "Network" / "Cookies"
                    if not cookies_path.exists():
                        cookies_path = profile_dir / "Default" / "Cookies"
                    mtime = cookies_path.stat().st_mtime if cookies_path.exists() else profile_dir.stat().st_mtime
                    age_days = (datetime.now().timestamp() - mtime) / 86400.0
                    login_age = age_days
                    if age_days <= 30:
                        login_state = "logged_in"
                        login_status = f"🟢 영구 로그인 ({age_days:.0f}일 경과)"
                    else:
                        login_state = "stale"
                        login_status = f"🟡 30일 초과 ({age_days:.0f}일 — 재로그인 권장)"
                elif _has_session_trace(profile_dir, acc.market):
                    profile_mtime = profile_dir.stat().st_mtime
                    age_days = (datetime.now().timestamp() - profile_mtime) / 86400.0
                    login_age = age_days
                    login_state = "session_only"
                    login_status = "⚠ 세션 only (재로그인 필요할 수 있음)"
                else:
                    login_state = "incomplete"
                    login_status = "⚠ 로그인 미완료"

            meta = MARKET_METADATA.get(acc.market, {})
            rows.append({
                "id": acc.id,
                "account_key": acc.account_key,
                "display_name": acc.display_name,
                "market": acc.market,
                "market_label": meta.get("label", acc.market),
                "market_icon": meta.get("icon", "🔧"),
                "env_prefix": acc.env_prefix,
                "is_active": acc.is_active,
                "cred_status": cred_status,
                "cred_state": cred_state,           # ok | missing | unknown
                "missing_count": missing_count,
                "masked_id": masked_id,
                "note": acc.note or "",
                "login_state": login_state,         # logged_in | stale | not_logged_in | n/a
                "login_status": login_status,
                "login_age_days": round(login_age, 1) if login_age is not None else None,
                "has_login_creds": has_login_creds,  # .env 에 LOGIN_ID/PW 등록 여부
                # 라이브 검증 — 이 마켓이 「🧪 라이브 검증」 대상인지 + 이 계정의 검증 여부.
                "live_verifiable": acc.market in _LIVE_VERIFIABLE_MARKETS(),
                "live_verified": acc.live_verified_at is not None,
                "live_verified_at": (acc.live_verified_at.strftime("%Y-%m-%d %H:%M")
                                     if acc.live_verified_at else None),
                "live_verified_count": acc.live_verified_count,
            })

        # 마켓 우선순위 정렬: 쿠팡 > 스스 > 롯데온 > 11번가 > 옥션 > G마켓 > 기타
        rows.sort(key=lambda r: (
            MARKET_METADATA.get(r["market"], {}).get("sort_order", 999),
            r["account_key"],
        ))

        # 사이드바 마켓 리스트 — 모든 마켓(MARKET_METADATA) + 등록된 계정 수
        market_counts = {}
        for r in rows:
            market_counts[r["market"]] = market_counts.get(r["market"], 0) + 1
        market_nav = []
        for key, meta in sorted(MARKET_METADATA.items(),
                                key=lambda kv: kv[1].get("sort_order", 999)):
            market_nav.append({
                "key": key,
                "label": meta["label"],
                "count": market_counts.get(key, 0),
                "status": meta["status"],
                "ready": meta["status"] == "ready",
            })
    finally:
        s.close()

    return render_template(
        "accounts/upload.html",
        active="accounts_upload",
        accounts=rows,
        total=len(rows),
        market_nav=market_nav,
    )


# ──────────────────────────────────────────────────────────
#  /accounts/sourcing — 소싱처 회원 세션
# ──────────────────────────────────────────────────────────


@bp.route("/sourcing")
def sourcing_accounts_view():
    """소싱처 — 크롤링 대상 매핑 (V1 Model 기반) + 회원 세션 (V2 SourcingAccount).

    상단: 소싱처별 매핑 현황 (5소싱처 × 모음전 N — 어느 모음전에 URL 채워졌는지)
    하단: 회원 가격 접근용 storage_state 세션 (무신사·SSF만)
    """
    from lemouton.auth.session_store import SessionStore
    from lemouton.auth import default_auth_dir
    from lemouton.sourcing.models import Model

    # 5 소싱처 정의 — DB 컬럼명 ↔ 표시명 ↔ 회원 가격 여부
    SOURCES = [
        {"key": "lemouton",    "label": "르무통 공홈",        "needs_login": False},
        {"key": "musinsa",     "label": "무신사",            "needs_login": True},
        {"key": "ssf",         "label": "SSF",              "needs_login": True},
        {"key": "lotteon",     "label": "롯데홈쇼핑",        "needs_login": False},
        {"key": "ss_lemouton", "label": "스마트스토어 르무통", "needs_login": False},
    ]
    URL_ATTR = {
        "lemouton": "url_lemouton",
        "musinsa": "url_musinsa",
        "ssf": "url_ssf",
        "lotteon": "url_lotteon",
        "ss_lemouton": "url_ss_lemouton",
    }

    store = SessionStore(auth_dir=default_auth_dir())
    s = SessionLocal()
    try:
        # ── 1) 매핑 매트릭스 — V1 Model 의 url_* 컬럼 + BundleSourceUrl (v6 P5.5 — custom 도 포함)
        try:
            from lemouton.sourcing.models import BundleSourceUrl, SourcingSource
        except Exception:
            BundleSourceUrl, SourcingSource = None, None
        models = s.query(Model).order_by(Model.model_code).all()
        mapping_matrix = []
        # builtin 5
        for src in SOURCES:
            attr = URL_ATTR[src["key"]]
            cells = []
            mapped_count = 0
            for m in models:
                url = getattr(m, attr, None)
                if url:
                    mapped_count += 1
                    cells.append({"model_code": m.model_code, "url": url, "mapped": True})
                else:
                    cells.append({"model_code": m.model_code, "url": None, "mapped": False})
            mapping_matrix.append({
                "key": src["key"], "label": src["label"], "needs_login": src["needs_login"],
                "mapped_count": mapped_count, "total": len(models), "cells": cells,
                "builtin": True,
            })
        # custom 사용자 추가분 — BundleSourceUrl 조회 (트랜잭션 격리)
        custom_srcs = []
        if SourcingSource is not None:
            try:
                custom_srcs = (s.query(SourcingSource)
                               .filter(SourcingSource.is_active.is_(True))
                               .order_by(SourcingSource.sort_order, SourcingSource.id)
                               .all())
            except Exception:
                s.rollback()
                custom_srcs = []
        for src in custom_srcs:
            # 한번에 모델별 url 조회 — N+1 회피
            url_by_model = {}
            for row in (s.query(BundleSourceUrl)
                          .filter_by(source_key=src.source_key)
                          .order_by(BundleSourceUrl.sort_order, BundleSourceUrl.id).all()):
                # 모델별 첫 URL 만 매트릭스 표시 (다중은 edit 페이지에서)
                url_by_model.setdefault(row.model_code, row.url)
            cells = []
            mapped_count = 0
            for m in models:
                url = url_by_model.get(m.model_code)
                if url:
                    mapped_count += 1
                    cells.append({"model_code": m.model_code, "url": url, "mapped": True})
                else:
                    cells.append({"model_code": m.model_code, "url": None, "mapped": False})
            mapping_matrix.append({
                "key": src.source_key, "label": src.label, "needs_login": src.needs_login,
                "mapped_count": mapped_count, "total": len(models), "cells": cells,
                "builtin": False, "logo_color": src.logo_color, "logo_letter": src.logo_letter,
            })

        # ── 2) 회원 세션 — V2 SourcingAccount
        accounts = s.query(SourcingAccount).order_by(
            SourcingAccount.source, SourcingAccount.account_key
        ).all()
        session_rows = []
        for acc in accounts:
            has_session = store.has_session(acc.source, acc.account_key)
            age_days = store.age_days(acc.source, acc.account_key)
            is_expired = store.is_expired(acc.source, acc.account_key, ttl_days=30)
            if not has_session:
                session_status = "⏸ 미로그인"
            elif is_expired:
                session_status = "⚠️ 만료 (재로그인 필요)"
            else:
                session_status = f"✅ 활성 ({age_days:.0f}일 경과)"
            session_rows.append({
                "id": acc.id,
                "source": acc.source,
                "account_key": acc.account_key,
                "display_name": acc.display_name or "—",
                "is_active": acc.is_active,
                "has_session": has_session,
                "is_expired": is_expired,
                "session_status": session_status,
                "age_days": round(age_days, 1) if age_days is not None else None,
                "last_login_at": acc.last_login_at.isoformat() if acc.last_login_at else "—",
                "note": acc.note or "",
            })
    finally:
        s.close()

    return render_template(
        "accounts/sourcing.html",
        active="accounts_sourcing",
        mapping_matrix=mapping_matrix,
        models=models,
        accounts=session_rows,
        total_sessions=len(session_rows),
        total_models=len(models),
    )


# ──────────────────────────────────────────────────────────
#  /accounts/wizard/start — 자동 로그인 위저드 시작 (Phase 2-C 진입점)
# ──────────────────────────────────────────────────────────


# ──────────────────────────────────────────────────────────
#  /api/accounts/secrets/{env_prefix} — 시크릿 UI 저장
# ──────────────────────────────────────────────────────────


# 마켓별 필요 키 (env_prefix 뒤에 붙는 suffix)
MARKET_KEY_SUFFIXES = {
    "smartstore": ["CLIENT_ID", "CLIENT_SECRET"],
    "coupang": ["ACCESS_KEY", "SECRET_KEY", "VENDOR_ID"],
    "lotteon": ["API_KEY", "TR_NO"],
    "eleven11": ["OPENAPI_KEY"],   # 11번가 = openapikey 헤더 단일 인증키 (OAuth·시크릿 없음)
    # 옥션·G마켓 = ESM 2.0(이베이코리아) 통합. JWT(HmacSHA256): kid=마스터ID, ssi="{site}:{판매자ID}".
    # master_id·secret_key 는 두 마켓 공통, seller_id 만 다름(옥션 site A / G마켓 site G).
    "auction": ["MASTER_ID", "SECRET_KEY", "SELLER_ID"],
    "gmarket": ["MASTER_ID", "SECRET_KEY", "SELLER_ID"],
}

# UI 노출용 라벨 — sensitive 여부도 표시
KEY_LABELS = {
    "CLIENT_ID": ("Client ID", False),
    "CLIENT_SECRET": ("Client Secret", True),
    "ACCESS_KEY": ("Access Key", False),
    "SECRET_KEY": ("Secret Key", True),
    "VENDOR_ID": ("Vendor ID (셀러 코드)", False),
    "API_KEY": ("API 인증키 (Bearer)", True),
    "TR_NO": ("거래처번호 (판매자 센터)", False),
    "OPENAPI_KEY": ("OpenAPI 인증키 (openapikey 헤더)", True),
    "MASTER_ID": ("ESM 마스터 ID (ESM+ 통합)", False),
    "SELLER_ID": ("판매자 ID (옥션/G마켓)", False),
}

# 마켓 메타데이터 — UI 사이드바에서 사용 (라벨·아이콘·도움말·상태)
# sort_order: 사용자 지정 — 쿠팡 > 스마트스토어 > 롯데온 > 11번가 > 옥션 > G마켓 > 기타
MARKET_METADATA = {
    "coupang": {
        "label": "쿠팡",
        "icon": "🟠",
        "api_type": "HMAC (Wing Open API)",
        "guide_url": "https://wing.coupang.com/",
        "guide_text": "쿠팡 Wing → 마이쿠팡 → API 키 관리에서 발급",
        "default_prefix": "COUPANG_MAIN",
        "status": "ready",
        "sort_order": 1,
    },
    "smartstore": {
        "label": "스마트스토어",
        "icon": "🟢",
        "api_type": "OAuth (네이버 커머스)",
        "guide_url": "https://apicenter.commerce.naver.com/",
        "guide_text": "네이버 커머스 API 센터에서 애플리케이션 등록 후 Client ID·Secret 발급",
        "default_prefix": "SMARTSTORE_MAIN",
        "status": "ready",
        "sort_order": 2,
    },
    "lotteon": {
        "label": "롯데온",
        "icon": "🔴",
        "api_type": "OpenAPI (Bearer 인증키)",
        "guide_url": "https://store.lotteon.com/",
        "guide_text": ("롯데온 판매자 센터 > 판매자정보 > OpenAPI관리 에서 "
                       "① 서버 IP 등록(54.116.196.90) ② 인증키 발급. 거래처번호(trNo)도 여기서 확인."),
        "default_prefix": "LOTTEON_MAIN",
        # UI 온보딩(계정·키 등록·연결 테스트) 개방. 실제 전송은 MOUM_LIVE_UPLOAD(OFF)가 별도 게이트.
        "status": "ready",
        "sort_order": 3,
    },
    "eleven11": {
        "label": "11번가",
        "icon": "🟣",
        "api_type": "OpenAPI (openapikey 헤더 · XML)",
        "guide_url": "https://openapi.11st.co.kr/openapi/OpenApiFrontMain.tmall",
        "guide_text": ("11번가 셀러오피스 로그인 > 하단 Open API > 서비스 등록·확인 에서 "
                       "① OPENAPI KEY 발급 ② 서버 IP 등록(54.116.196.90). 인증은 "
                       "'openapikey: {발급키}' 헤더(단일 인증키·시크릿 없음)."),
        "default_prefix": "ELEVEN11_MAIN",
        # UI 온보딩(키 등록) 개방. 실제 주문조회·전송은 스펙 확보+검증 후. (order_export.SUPPORTED 미포함)
        "status": "ready",
        "sort_order": 4,
    },
    "auction": {
        "label": "옥션",
        "icon": "🟡",
        "api_type": "ESM 2.0 (이베이코리아 · JWT)",
        "guide_url": "https://etapi.gmarket.com/",
        "guide_text": ("ESM+ 로그인 > 판매자정보 > 판매도구 관리에서 사용 설정 후 ESM Trading API "
                       "발급. 필요값 = ① ESM 마스터 ID ② 시크릿 키 ③ 옥션 판매자 ID. "
                       "옥션·G마켓은 같은 마스터ID·시크릿을 쓰고 판매자 ID만 다름."),
        "default_prefix": "AUCTION_MAIN",
        # UI 온보딩 개방. 주문 API 엔드포인트 스펙은 확보 후 채움(추측 금지). (order_export.SUPPORTED 미포함)
        "status": "ready",
        "sort_order": 5,
    },
    "gmarket": {
        "label": "G마켓",
        "icon": "🟡",
        "api_type": "ESM 2.0 (이베이코리아 · JWT)",
        "guide_url": "https://etapi.gmarket.com/",
        "guide_text": ("ESM+ 로그인 > 판매자정보 > 판매도구 관리에서 사용 설정 후 ESM Trading API "
                       "발급. 필요값 = ① ESM 마스터 ID ② 시크릿 키 ③ G마켓 판매자 ID. "
                       "옥션과 같은 마스터ID·시크릿, 판매자 ID만 다름."),
        "default_prefix": "GMARKET_MAIN",
        "status": "ready",
        "sort_order": 6,
    },
    # 기타 — sort_order 99+
    "wemakeprice": {
        "label": "위메프",
        "icon": "🟤",
        "api_type": "파트너센터 API",
        "guide_url": "https://wpartner.wemakeprice.com/",
        "guide_text": "위메프 파트너센터에서 API 키 발급",
        "default_prefix": "WEMAKE_MAIN",
        "status": "coming_soon",
        "sort_order": 99,
    },
    "interpark": {
        "label": "인터파크",
        "icon": "🔵",
        "api_type": "셀러센터 API",
        "guide_url": "https://sellercenter.interpark.com/",
        "guide_text": "인터파크 셀러센터 API 발급",
        "default_prefix": "INTERPARK_MAIN",
        "status": "coming_soon",
        "sort_order": 100,
    },
}


def market_sort_key(market: str) -> tuple:
    """마켓 정렬 키 — sort_order 기반, 누락 시 999."""
    meta = MARKET_METADATA.get(market, {})
    return (meta.get("sort_order", 999), market)


# 마켓별 '셀러를 식별하는' 키 접미사. 이 값이 같으면 이름이 달라도 같은 판매자 계정이다.
#  order_export._IDENTITY_KEYS 와 같은 필드를 가리킨다(지문도 같은 값이 나오도록).
_IDENTITY_SUFFIX = {
    "coupang": "VENDOR_ID",
    "smartstore": "CLIENT_ID",
    "lotteon": "TR_NO",
    "eleven11": "OPENAPI_KEY",
    "auction": "SELLER_ID",
    "gmarket": "SELLER_ID",
}


def _find_duplicate_key_account(market: str, env_prefix: str, env_keys: dict):
    """이번에 저장할 셀러 식별키가 같은 마켓의 '다른 활성 계정'에 이미 있으면 (계정명들, 지문).

    없으면 None. 값 자체는 어디에도 노출하지 않는다(지문만).
    """
    sfx = _IDENTITY_SUFFIX.get(market)
    if not sfx:
        return None
    # 이번에 들어온 값. 안 들어왔으면 기존값(=변경 없음)이라 중복 검사 불필요.
    new_val = (env_keys.get(f"{env_prefix}_{sfx}") or "").strip()
    if not new_val:
        return None

    s = SessionLocal()
    try:
        others = (s.query(UploadAccount)
                  .filter(UploadAccount.market == market,
                          UploadAccount.is_active == True,          # noqa: E712
                          UploadAccount.env_prefix != env_prefix)
                  .order_by(UploadAccount.id).all())
        names = [a.display_name for a in others
                 if (os.environ.get(f"{a.env_prefix}_{sfx}", "") or "").strip() == new_val]
    finally:
        s.close()

    if not names:
        return None
    from lemouton.markets.order_export import _ident_fingerprint
    return names, _ident_fingerprint(f"{market}:{sfx.lower()}:{new_val}")


@bp.route("/api/secrets/<env_prefix>", methods=["POST"])
def save_secrets(env_prefix: str):
    """UI에서 입력한 시크릿을 .env 에 저장 + 환경변수 즉시 반영.

    Body: ``{"market": "smartstore"|"coupang", "values": {"CLIENT_ID": "...", ...}}``
    Response: ``{"ok": true, "masked": {"SMARTSTORE_MAIN_CLIENT_ID": "ncp_***7890"}}``
    """
    from pathlib import Path
    from lemouton.auth.env_writer import update_env_keys, EnvWriteError

    body = request.get_json(silent=True) or {}
    market = body.get("market", "").lower()
    values = body.get("values") or {}

    if market not in MARKET_KEY_SUFFIXES:
        return jsonify({
            "ok": False,
            "error": f"지원하지 않는 market: {market}",
            "supported": list(MARKET_KEY_SUFFIXES.keys()),
        }), 400

    if not env_prefix or not env_prefix.replace("_", "").isalnum():
        return jsonify({
            "ok": False,
            "error": "env_prefix 형식 오류 (영숫자 + 언더스코어만)",
        }), 400

    # 멀티 워커 일관성 — 다른 워커가 저장한 기존값을 이 워커도 보게 해서
    # '빈 칸이지만 기존값 있음' 판정이 워커 간 일관되도록(필수 필드 오거부 방지).
    from lemouton.auth import secrets as _S
    _S.refresh_env()

    # 입력 검증 — 빈 칸 + 기존값 있으면 기존 유지(확인만 하고 저장 시 안 깨짐)
    expected_suffixes = MARKET_KEY_SUFFIXES[market]
    env_keys = {}
    truly_missing = []
    for sfx in expected_suffixes:
        v = (values.get(sfx) or "").strip()
        if v:
            env_keys[f"{env_prefix}_{sfx}"] = v
        elif os.environ.get(f"{env_prefix}_{sfx}"):
            continue  # 비워둠 + 기존값 존재 → 기존 유지
        else:
            truly_missing.append(sfx)

    if truly_missing:
        return jsonify({
            "ok": False,
            "error": f"필수 필드 누락(기존값도 없음): {truly_missing}",
        }), 400

    if not env_keys:
        return jsonify({
            "ok": True,
            "env_prefix": env_prefix,
            "market": market,
            "masked": {},
            "message": "변경 사항 없음 — 기존 키 그대로 유지됩니다.",
        })

    # ★ 같은 셀러 키가 두 계정에 저장되는 것을 '저장 단계'에서 막는다(전 마켓 공통).
    #   실제 사고: 11번가 두 쌍이 같은 OPENAPI_KEY 로 저장돼, 주문조회에서 한쪽 가게가 통째로
    #   빠졌다(브라우저 자동완성이 이전 계정 키를 다시 채운 것으로 추정). 저장을 막지 않으면
    #   같은 주문 2배 계상 또는 다른 가게 주문 누락(발송 사고)으로 이어진다.
    conflict = _find_duplicate_key_account(market, env_prefix, env_keys)
    if conflict:
        names, fp = conflict
        return jsonify({
            "ok": False,
            "error": f"이 키는 이미 「{'」, 「'.join(names)}」 계정에 등록돼 있어요 (키 지문 {fp}).",
            "hint": "브라우저 자동완성이 이전 계정의 키를 다시 채웠을 수 있어요. "
                    "칸을 비우고 이 가게의 키를 직접 붙여넣어 주세요.",
            "conflicts": names,
            "fingerprint": fp,
        }), 409

    # 영속 경로(호스트 볼륨 마운트) 우선 — 컨테이너 교체돼도 유지. 없으면 프로젝트 .env.
    from lemouton.auth import secrets as _S2
    env_path = _S2.secrets_env_path()

    try:
        masked = update_env_keys(env_path, env_keys)
    except EnvWriteError as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    return jsonify({
        "ok": True,
        "env_prefix": env_prefix,
        "market": market,
        "masked": masked,
        "message": f"{env_prefix} 시크릿 {len(env_keys)}개 저장 완료. API 즉시 사용 가능.",
    })


@bp.route("/api/markets", methods=["GET"])
def list_markets():
    """지원 마켓 메타데이터 목록 — 등록 모달 사이드바에서 사용.

    Response: ``{
        "ok": true,
        "markets": [
            {"key": "smartstore", "label": "스마트스토어", "icon": "🟢",
             "api_type": "OAuth", "key_count": 2, "status": "ready", ...},
            ...
        ]
    }``
    """
    markets = []
    for key, meta in MARKET_METADATA.items():
        suffixes = MARKET_KEY_SUFFIXES.get(key, [])
        markets.append({
            "key": key,
            "label": meta["label"],
            "icon": meta["icon"],
            "api_type": meta["api_type"],
            "key_count": len(suffixes),
            "status": meta["status"],
            "guide_url": meta.get("guide_url", ""),
            "guide_text": meta.get("guide_text", ""),
            "default_prefix": meta.get("default_prefix", ""),
        })
    # 사용자 지정 우선순위: 쿠팡 > 스스 > 롯데온 > 11번가 > 옥션 > G마켓 > 기타
    markets.sort(key=lambda m: MARKET_METADATA.get(m["key"], {}).get("sort_order", 999))
    return jsonify({"ok": True, "markets": markets})


def _next_free_env_prefix(market: str) -> str:
    """신규 계정용 '빈' 고유 env_prefix 발급.

    마켓당 여러 계정 + 계정별 API 키가 별개이므로, 신규 등록 시 기존 계정과
    다른 저장칸을 써야 한다. 후보 = default_prefix(…_MAIN) → {ROOT}_2 → {ROOT}_3 …
    이미 UploadAccount 가 쓰거나 .env 에 값이 남아있는 prefix 는 건너뛴다
    (빈 폼 보장 — 기존 키가 새 폼에 새어나오지 않게).
    """
    meta = MARKET_METADATA.get(market, {})
    default_prefix = meta.get("default_prefix") or f"{market.upper()}_MAIN"
    root = default_prefix[:-5] if default_prefix.endswith("_MAIN") else default_prefix
    suffixes = MARKET_KEY_SUFFIXES.get(market, [])
    first_sfx = suffixes[0] if suffixes else "CLIENT_ID"

    s = SessionLocal()
    try:
        used = {row[0] for row in s.query(UploadAccount.env_prefix).all()}
    finally:
        s.close()

    candidates = [default_prefix] + [f"{root}_{i}" for i in range(2, 100)]
    for cand in candidates:
        if cand in used:
            continue
        if os.environ.get(f"{cand}_{first_sfx}"):
            continue  # .env 잔존값 있으면 스킵 (빈 폼 보장)
        return cand
    # 폴백 — 극단적 상황 (계정 100개 초과)
    return f"{root}_{len(used) + 1}"


@bp.route("/api/markets/<market>/next-prefix", methods=["GET"])
def market_next_prefix(market: str):
    """신규 계정 등록 모달이 마켓 선택 즉시 호출 — 빈 고유 env_prefix 반환."""
    market = market.lower()
    if market not in MARKET_KEY_SUFFIXES:
        return jsonify({"ok": False, "error": "market 미지원"}), 400
    return jsonify({
        "ok": True,
        "market": market,
        "env_prefix": _next_free_env_prefix(market),
    })


# ──────────────────────────────────────────────────────────
#  우리 서버 IP 명부 — 마켓 "출발지 IP 등록"칸에 붙여넣을 값 (팀 공유)
# ──────────────────────────────────────────────────────────

# 첫 조회 시 목록이 비어 있으면 넣어주는 기본값(업로드 서버).
_DEFAULT_SERVER_IPS = [("업로드 서버", "54.116.196.90")]
_IP_RE = re.compile(r"^[0-9A-Fa-f:.]+$")


def _seed_server_ips_if_empty(s) -> None:
    from webapp.server_ip_model import ServerIp
    if s.query(ServerIp).count() == 0:
        for i, (name, ip) in enumerate(_DEFAULT_SERVER_IPS):
            s.add(ServerIp(name=name, ip=ip, sort_order=i))
        s.commit()


@bp.route("/api/server-ips", methods=["GET"])
def list_server_ips():
    """우리 서버 IP 목록. 비어 있으면 기본(업로드 서버)을 시드 후 반환."""
    from webapp.server_ip_model import ServerIp
    s = SessionLocal()
    try:
        _seed_server_ips_if_empty(s)
        rows = s.query(ServerIp).order_by(ServerIp.sort_order, ServerIp.id).all()
        return jsonify({"ok": True, "items": [r.to_dict() for r in rows]})
    finally:
        s.close()


@bp.route("/api/server-ips", methods=["POST"])
def add_server_ip():
    """서버 IP 한 건 추가. Body: {"name": "업로드 서버", "ip": "54.116.196.90"}. 이름은 선택."""
    from sqlalchemy import func
    from webapp.server_ip_model import ServerIp
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    ip = (body.get("ip") or "").strip()
    if not ip:
        return jsonify({"ok": False, "error": "IP 주소를 입력하세요"}), 400
    if len(ip) > 64 or not _IP_RE.match(ip):
        return jsonify({"ok": False, "error": "IP 형식이 올바르지 않아요 (숫자·점만)"}), 400
    s = SessionLocal()
    try:
        max_order = s.query(func.coalesce(func.max(ServerIp.sort_order), 0)).scalar() or 0
        row = ServerIp(name=name[:80], ip=ip, sort_order=int(max_order) + 1)
        s.add(row)
        s.commit()
        s.refresh(row)
        return jsonify({"ok": True, "item": row.to_dict()})
    except Exception as e:
        s.rollback()
        return jsonify({"ok": False, "error": f"저장 실패: {type(e).__name__}: {e}"}), 500
    finally:
        s.close()


@bp.route("/api/server-ips/<int:ip_id>", methods=["DELETE"])
def delete_server_ip(ip_id: int):
    """서버 IP 한 건 삭제."""
    from webapp.server_ip_model import ServerIp
    s = SessionLocal()
    try:
        row = s.get(ServerIp, ip_id)
        if row is None:
            return jsonify({"ok": False, "error": "이미 없는 항목이에요"}), 404
        s.delete(row)
        s.commit()
        return jsonify({"ok": True})
    finally:
        s.close()


@bp.route("/api/upload/accounts", methods=["POST"])
def create_upload_account():
    """새 판매처 계정 등록 — UploadAccount row 생성 (시크릿은 별도 모달에서).

    Body: ``{
        "account_key": "르무통_본계_smartstore",
        "display_name": "르무통 본계 스마트스토어",
        "market": "smartstore"|"coupang",
        "env_prefix": "SMARTSTORE_MAIN",
        "note": "..."
    }``
    """
    body = request.get_json(silent=True) or {}
    account_key = (body.get("account_key") or "").strip()
    display_name = (body.get("display_name") or "").strip()
    market = (body.get("market") or "").strip().lower()
    env_prefix = (body.get("env_prefix") or "").strip()
    note = (body.get("note") or "").strip() or None

    # 유효성 검사
    if not account_key:
        return jsonify({"ok": False, "error": "account_key 필수"}), 400
    if not display_name:
        return jsonify({"ok": False, "error": "display_name 필수"}), 400
    if market not in MARKET_KEY_SUFFIXES:
        return jsonify({
            "ok": False,
            "error": f"지원하지 않는 market: {market}",
            "supported": list(MARKET_KEY_SUFFIXES.keys()),
        }), 400
    if not env_prefix or not env_prefix.replace("_", "").isalnum():
        return jsonify({"ok": False, "error": "env_prefix 형식 오류 (영숫자 + 언더스코어만)"}), 400

    s = SessionLocal()
    try:
        # ── 중복 검사 — 계정명은 '같은 마켓 안에서만' 중복으로 본다.
        # 사장님 기준으로 「쿠팡 브랜드위시」와 「옥션 브랜드위시」는 서로 다른 계정이다.
        # 예전엔 account_key(전역 UNIQUE)로만 검사해서, 다른 마켓에 같은 이름이 있으면
        # 등록 자체가 막혔다(2026-07-20 옥션 등록 중 발견).
        same_market = (s.query(UploadAccount)
                       .filter_by(market=market, display_name=display_name).first())
        if same_market:
            return jsonify({
                "ok": False,
                "error": f"'{display_name}' 은(는) 이 마켓에 이미 등록된 계정입니다 — 다른 이름 사용",
            }), 409

        # account_key 는 화면에 안 보이는 내부 슬러그인데 DB 전역 UNIQUE 라
        # 마켓이 다른 동명 계정끼리 충돌한다 → 마켓 접미사로 고유화.
        # (빠른 추가 경로가 쓰는 "{별칭}_{market}" 및 모델 예시 "르무통_본계_smartstore" 와 같은 규칙)
        if s.query(UploadAccount).filter_by(account_key=account_key).first():
            base = f"{account_key}_{market}"
            candidate, n = base, 1
            while s.query(UploadAccount).filter_by(account_key=candidate).first():
                n += 1
                candidate = f"{base}_{n}"
            account_key = candidate

        existing_prefix = s.query(UploadAccount).filter_by(env_prefix=env_prefix).first()
        if existing_prefix:
            return jsonify({
                "ok": False,
                "error": f"env_prefix '{env_prefix}' 이미 사용 중 ({existing_prefix.display_name})",
            }), 409

        acc = UploadAccount(
            account_key=account_key,
            display_name=display_name,
            market=market,
            env_prefix=env_prefix,
            note=note,
            is_active=True,
        )
        s.add(acc)
        s.commit()
        s.refresh(acc)
        return jsonify({
            "ok": True,
            "id": acc.id,
            "account_key": acc.account_key,
            "env_prefix": acc.env_prefix,
            "market": acc.market,
            "message": f"{display_name} 계정 등록 완료. 다음 단계: 🔑 키 입력으로 API 키를 등록하세요.",
        })
    except Exception as e:
        s.rollback()
        return jsonify({"ok": False, "error": f"DB 저장 실패: {type(e).__name__}: {e}"}), 500
    finally:
        s.close()


@bp.route("/api/upload/accounts/<int:account_id>", methods=["PATCH"])
def update_upload_account(account_id: int):
    """판매처 계정 수정 — display_name / note / is_active.

    market 과 env_prefix 는 불변 (시크릿 키 매핑 깨짐 방지).
    Body: ``{"display_name": "...", "note": "...", "is_active": true}``
    """
    body = request.get_json(silent=True) or {}
    s = SessionLocal()
    try:
        acc = s.query(UploadAccount).get(account_id)
        if not acc:
            return jsonify({"ok": False, "error": "계정 없음"}), 404

        changed = []
        if "display_name" in body:
            new_name = (body["display_name"] or "").strip()
            if not new_name:
                return jsonify({"ok": False, "error": "display_name 비어있음"}), 400
            if new_name != acc.display_name:
                # 마켓이 다르면 같은 이름을 허용한다(등록 경로와 같은 규칙).
                # 단 같은 마켓 안에서 동명 계정 둘은 화면에서 구분이 불가능하고,
                # 채널→계정 해석(set_link_service._resolve_env_prefix)이 모호해져
                # 엉뚱한 계정으로 업로드될 수 있으므로 막는다.
                dup = (s.query(UploadAccount)
                       .filter(UploadAccount.market == acc.market,
                               UploadAccount.display_name == new_name,
                               UploadAccount.id != acc.id).first())
                if dup:
                    return jsonify({
                        "ok": False,
                        "error": f"'{new_name}' 은(는) 이 마켓에 이미 등록된 계정입니다 — 다른 이름 사용",
                    }), 409
                acc.display_name = new_name
                changed.append("display_name")
        if "note" in body:
            acc.note = (body["note"] or "").strip() or None
            changed.append("note")
        if "is_active" in body:
            acc.is_active = bool(body["is_active"])
            changed.append("is_active")

        if not changed:
            return jsonify({"ok": True, "message": "변경 사항 없음", "changed": []})

        s.commit()
        return jsonify({
            "ok": True,
            "id": acc.id,
            "changed": changed,
            "message": f"{acc.display_name} 수정 완료 ({', '.join(changed)})",
        })
    except Exception as e:
        s.rollback()
        return jsonify({"ok": False, "error": f"DB 수정 실패: {type(e).__name__}: {e}"}), 500
    finally:
        s.close()


# 마켓별 영구 로그인 진입 URL
_MARKET_LOGIN_URLS = {
    "smartstore": "https://sell.smartstore.naver.com/",
    "coupang": "https://wing.coupang.com/",
}


@bp.route("/api/upload/accounts/<int:account_id>/login", methods=["POST"])
def login_upload_account(account_id: int):
    """판매처 영구 로그인 — 일반 Chrome 으로 user_data_dir 띄우기.

    Flow:
      1. UploadAccount 조회 → market 확인 (smartstore | coupang)
      2. data/profiles/{market}_{env_prefix}/ 디렉터리에 영구 쿠키 저장될 위치 결정
      3. 마켓별 로그인 URL 로 detached Chrome 스폰
      4. 사용자가 직접 ID/PW 입력 → 창 닫음 → 쿠키 영구 저장

    클라이언트는 즉시 응답 받음. 브라우저는 사용자 닫을 때까지 유지.
    """
    s = SessionLocal()
    try:
        acc = s.query(UploadAccount).get(account_id)
        if not acc:
            return jsonify({"ok": False, "error": "계정을 찾을 수 없어요"}), 404
        market = acc.market
        env_prefix = acc.env_prefix
        display_name = acc.display_name
    finally:
        s.close()

    login_url = _MARKET_LOGIN_URLS.get(market)
    if login_url is None:
        return jsonify({
            "ok": False,
            "error": f"{market} 영구 로그인 미지원 (지원: {', '.join(_MARKET_LOGIN_URLS)})",
        }), 400

    # 기존에 같은 프로필 쓰던 Chrome 있으면 자동 종료 후 새 창 오픈 (kill_chrome_using 은 launcher 내부에서도 호출)
    from lemouton.auth.profile_store import default_store as _profile_store
    _store = _profile_store()
    profile_path = _store.profile_dir(market, env_prefix)
    closed_count = 0
    if os.name == "nt":
        try:
            import subprocess
            ps_cmd = (
                "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
                "Where-Object { $_.CommandLine -like '*" + profile_path.name + "*' } | "
                "Measure-Object | Select-Object -ExpandProperty Count"
            )
            # CREATE_NO_WINDOW — powershell cmd 창 깜빡임 방지
            _NO_WIN = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            r = subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd],
                               capture_output=True, text=True, timeout=8,
                               creationflags=_NO_WIN)
            closed_count = int((r.stdout or "0").strip() or "0")
        except Exception:
            pass
        # 실제 종료 + 락 정리
        _store.kill_chrome_using(profile_path)
        _store.cleanup_lock(profile_path)

    try:
        # 첫 로그인은 일반 Chrome 으로 — 봇 탐지 우회 (Playwright 안 씀)
        # 쿠키는 user_data_dir 에 그대로 저장 → 그 후 Playwright 가 같은 dir 사용 시 자동 로그인
        from lemouton.auth.marketplace_browser import spawn_native_chrome
        pid = spawn_native_chrome(profile_path=profile_path, url=login_url)
    except Exception as e:
        logger.exception("[accounts] 로그인 창 스폰 실패")
        return jsonify({"ok": False, "error": f"브라우저 스폰 실패: {type(e).__name__}: {e}"}), 500

    market_label = MARKET_METADATA.get(market, {}).get("label", market)
    if closed_count > 0:
        msg = (
            f"기존 {display_name} 창 {closed_count}개 종료 후 새 Chrome 창 오픈 (일반 모드 — 봇 탐지 우회). "
            f"{market_label} ID/PW 입력 → 끝까지 진입 → X 로 닫기. 한 번이면 영구 저장."
        )
    else:
        msg = (
            f"{display_name} 로그인 창이 일반 Chrome 으로 열렸어요 (봇 탐지 우회). "
            f"{market_label} ID/PW 입력 → 끝까지 진입 후 X 로 닫기. 한 번이면 영구 저장."
        )
    return jsonify({"ok": True, "pid": pid, "display_name": display_name, "message": msg})


@bp.route("/api/upload/accounts/<int:account_id>/key-fingerprint", methods=["GET"])
def account_key_fingerprint_api(account_id: int):
    """계정에 '실제로 저장된' 셀러 식별키의 지문(해시 앞 6자). 읽기 전용·키 값 미노출.

    지문이 같은 두 계정 = 같은 키가 저장돼 있다는 뜻(입력 실수 또는 저장 오류).
    주문조회의 중복 판정(_client_identity)과 완전히 같은 값을 쓰므로, 배너에 뜬 지문과
    이 값을 대조하면 어느 계정끼리 겹치는지 사용자가 직접 확인할 수 있다.
    """
    from lemouton.markets.order_export import (
        _account_client, _client_identity, _ident_fingerprint)

    s = SessionLocal()
    try:
        acc = s.query(UploadAccount).get(account_id)
        if not acc:
            return jsonify({"ok": False, "error": "계정 없음"}), 404
        market, env_prefix, name = acc.market, acc.env_prefix, acc.display_name
    finally:
        s.close()

    try:
        cli = _account_client(market, env_prefix)
    except Exception as e:   # noqa: BLE001
        return jsonify({"ok": False, "account": name, "error": f"{type(e).__name__}"}), 400
    if cli is None:
        return jsonify({"ok": False, "account": name, "market": market,
                        "env_prefix": env_prefix, "error": "키 미등록"}), 400

    ident = _client_identity(market, cli)
    if ident is None:
        return jsonify({"ok": True, "account": name, "market": market,
                        "env_prefix": env_prefix, "fingerprint": None,
                        "note": "이 마켓은 식별키 비교를 지원하지 않아요."})
    return jsonify({"ok": True, "account": name, "market": market,
                    "env_prefix": env_prefix,
                    "fingerprint": _ident_fingerprint(ident)})


@bp.route("/api/upload/accounts/<int:account_id>/test", methods=["POST"])
def test_upload_account_api(account_id: int):
    """판매처 API 연결 테스트 — 등록된 자격증명으로 실 API 호출.

    쿠팡: GET /v2/providers/seller_api/apis/api/v1/marketplace/seller-products?nextToken=&maxPerPage=1
    스마트스토어: POST /external/v1/oauth2/token (토큰 발급 시도)
    """
    from lemouton.auth import secrets as S

    s = SessionLocal()
    try:
        acc = s.query(UploadAccount).get(account_id)
        if not acc:
            return jsonify({"ok": False, "error": "계정 없음"}), 404
        market = acc.market
        env_prefix = acc.env_prefix
        display_name = acc.display_name
    finally:
        s.close()

    # 자격증명 로드
    try:
        creds = S.load_credentials(market=market, env_prefix=env_prefix)
    except S.SecretsMissingError as e:
        return jsonify({
            "ok": False,
            "error": f"키 누락 — {', '.join(e.missing_keys)}",
            "hint": "🔑 키 입력 으로 먼저 등록하세요.",
        }), 400
    except S.SecretsUnknownMarketError:
        return jsonify({"ok": False, "error": f"미지원 market: {market}"}), 400

    # 마켓별 호출
    if market == "coupang":
        return _test_coupang(creds, display_name, env_prefix)
    elif market == "smartstore":
        return _test_smartstore(creds, display_name, env_prefix)
    elif market == "lotteon":
        return _test_lotteon(creds, display_name, env_prefix)
    elif market == "eleven11":
        return _test_eleven11(creds, display_name, env_prefix)
    elif market in ("auction", "gmarket"):
        return _test_esm(creds, display_name, env_prefix, market)
    else:
        return jsonify({"ok": False, "error": f"{market} 테스트 미구현"}), 400


@bp.route("/api/upload/accounts/<int:account_id>/write-test", methods=["POST"])
def write_test_upload_account_api(account_id: int):
    """롯데온 무변화 쓰기 왕복 테스트 — 한 옵션의 **현재 재고를 그대로 재전송**.

    쓰기 API(재고 변경)가 실계정에서 성공하는지 확인한다. 보내는 값 = 지금 값 →
    실제 재고는 바뀌지 않는다(idempotent). 재고 관리(stkMgtYn=Y) 옵션이 없으면
    아무 것도 전송하지 않고 중단(안전).

    body: ``{"spd_no": "LO..."}``
    """
    from lemouton.auth import secrets as S

    body = request.get_json(silent=True) or {}
    spd_no = str(body.get("spd_no") or "").strip()
    if not spd_no:
        return jsonify({"ok": False, "error": "spd_no(판매자상품번호)가 필요해요."}), 400

    s = SessionLocal()
    try:
        acc = s.query(UploadAccount).get(account_id)
        if not acc:
            return jsonify({"ok": False, "error": "계정 없음"}), 404
        market, env_prefix, display_name = acc.market, acc.env_prefix, acc.display_name
    finally:
        s.close()

    if market != "lotteon":
        return jsonify({"ok": False, "error": f"{market} 무변화 테스트 미지원(현재 롯데온 전용)"}), 400

    try:
        creds = S.load_credentials(market=market, env_prefix=env_prefix)
    except S.SecretsMissingError as e:
        return jsonify({"ok": False, "error": f"키 누락 — {', '.join(e.missing_keys)}"}), 400

    from shared.platforms import LOTTEON
    from shared.platforms.lotteon.client import LotteonClient
    from shared.platforms.lotteon.products import get_product_detail, extract_items
    from shared.platforms.lotteon.inventory import update_stock

    client = LotteonClient(config={**LOTTEON, "api_key": creds.api_key, "tr_no": creds.tr_no})

    # 1) 현재 상세 읽기
    try:
        detail = get_product_detail(spd_no, client=client, tr_no=creds.tr_no)
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "error": f"상세조회 실패: {e}"}), 502
    items = extract_items(detail)
    if not items:
        return jsonify({"ok": False, "error": "옵션(단품)이 없어요."}), 400

    # 2) 재고 관리 + 실수량 있는 옵션 1개 (무변화 안전 대상)
    target = next((it for it in items
                   if it.get("stock_managed") and it.get("stock") is not None), None)
    if not target:
        return jsonify({
            "ok": False,
            "error": "재고 관리(stkMgtYn=Y) 옵션이 없어 무변화 재고 테스트를 못 해요"
                     "(모든 옵션이 재고 미관리). 다른 상품번호로 시도하거나 가격 테스트를 원하시면 알려주세요.",
            "options_read": len(items),
        }), 200

    sitm_no = target["sitm_no"]
    cur_stock = int(target["stock"])

    # 3) 같은 값 재전송 — 실제 변화 없음
    try:
        ok = update_stock(spd_no, sitm_no, cur_stock, client=client, tr_no=creds.tr_no)
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "error": f"재고 전송 실패: {e}"}), 502

    return jsonify({
        "ok": bool(ok),
        "message": (f"✅ {display_name} 쓰기 왕복 성공 — 옵션 {sitm_no}의 재고 {cur_stock}개를 "
                    f"'그대로' 재전송(값 변화 없음). 쓰기 API 정상."
                    if ok else f"쓰기 실패 — 옵션 {sitm_no}"),
        "sitm_no": sitm_no,
        "stock_resent": cur_stock,
        "options_read": len(items),
        "note": "값을 바꾸지 않는 무변화 테스트입니다.",
    })


def _test_coupang(creds, display_name: str, env_prefix: str):
    """쿠팡 Wing OPEN API ping — 셀러 상품 1건만 조회."""
    import time as _time
    import hmac as _hmac
    import hashlib as _hashlib
    import requests
    from urllib.parse import urlencode

    started = _time.time()
    base_url = "https://api-gateway.coupang.com"
    method = "GET"
    path = "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products"
    query = urlencode({"vendorId": creds.vendor_id, "maxPerPage": "1"})
    full_path = f"{path}?{query}"

    # HMAC-SHA256 서명 (쿠팡 Wing 표준)
    datetime_gmt = _time.strftime("%y%m%dT%H%M%SZ", _time.gmtime())
    message = f"{datetime_gmt}{method}{path}{query}"
    signature = _hmac.new(
        creds.secret_key.encode("utf-8"),
        message.encode("utf-8"),
        _hashlib.sha256,
    ).hexdigest()
    auth = (
        f"CEA algorithm=HmacSHA256, "
        f"access-key={creds.access_key}, "
        f"signed-date={datetime_gmt}, "
        f"signature={signature}"
    )

    try:
        r = requests.get(
            base_url + full_path,
            headers={"Authorization": auth, "Content-Type": "application/json"},
            timeout=15,
        )
    except Exception as e:
        elapsed = round(_time.time() - started, 2)
        return jsonify({
            "ok": False,
            "error": f"네트워크 오류: {type(e).__name__}: {e}",
            "elapsed_sec": elapsed,
        }), 500

    elapsed = round(_time.time() - started, 2)
    if r.status_code == 200:
        try:
            data = r.json()
            count = len(data.get("data", []))
            return jsonify({
                "ok": True,
                "message": f"✅ {display_name} 쿠팡 API 연결 성공 (응답 {elapsed}s, 상품 {count}건)",
                "status_code": r.status_code,
                "elapsed_sec": elapsed,
                "vendor_id": creds.vendor_id,
            })
        except Exception:
            return jsonify({
                "ok": True,
                "message": f"✅ 쿠팡 API 응답 (200, JSON 파싱 실패)",
                "status_code": r.status_code,
                "elapsed_sec": elapsed,
            })

    # 실패 — 응답 본문 일부 노출 (시크릿 마스킹)
    body_snippet = (r.text or "")[:300]
    return jsonify({
        "ok": False,
        "error": f"쿠팡 API 실패 — HTTP {r.status_code}",
        "status_code": r.status_code,
        "elapsed_sec": elapsed,
        "body_snippet": body_snippet,
        "hint": "Vendor ID/Access/Secret 정확한지 확인",
    }), 502


def _test_lotteon(creds, display_name: str, env_prefix: str):
    """롯데온 Open API ping — identity 호출로 인증키+출발지 IP 검증 (상품 불필요).

    GET /v1/openapi/common/v1/identity — 발급키가 유효하고 서버 IP 가 인증키에
    등록돼 있으면 200 + returnCode 정상. 401=키 오류 / 403=IP 미등록.
    """
    import time as _time
    import requests
    from shared.platforms.lotteon.auth import build_headers

    started = _time.time()
    url = "https://openapi.lotteon.com/v1/openapi/common/v1/identity"
    try:
        r = requests.get(url, headers=build_headers(creds.api_key), timeout=15)
    except Exception as e:
        elapsed = round(_time.time() - started, 2)
        return jsonify({
            "ok": False,
            "error": f"네트워크 오류: {type(e).__name__}: {e}",
            "elapsed_sec": elapsed,
        }), 500

    elapsed = round(_time.time() - started, 2)
    if r.status_code == 200:
        try:
            data = r.json()
            rc = str(data.get("returnCode"))
            if rc in ("0000", "SUCCESS"):
                return jsonify({
                    "ok": True,
                    "message": f"✅ {display_name} 롯데온 API 연결 성공 (인증키·출발지 IP OK, 응답 {elapsed}s)",
                    "status_code": 200,
                    "elapsed_sec": elapsed,
                    "tr_no": creds.tr_no,
                })
            return jsonify({
                "ok": False,
                "error": f"롯데온 응답 이상 — returnCode={rc}",
                "status_code": 200,
                "elapsed_sec": elapsed,
                "body_snippet": (r.text or "")[:300],
            }), 502
        except Exception:
            return jsonify({
                "ok": True,
                "message": "✅ 롯데온 API 응답 (200, JSON 파싱 실패)",
                "status_code": 200,
                "elapsed_sec": elapsed,
            })

    hint = {
        401: "인증키(API 인증키) 가 틀렸거나 만료 — OpenAPI관리에서 재발급 후 다시 등록",
        403: "출발지 IP 미등록 — OpenAPI관리 1단계에 서버 IP(54.116.196.90) 등록 필요",
        429: "호출량 초과(분당 10,000) — 잠시 후 재시도",
    }.get(r.status_code, "인증키·거래처번호가 정확한지 확인")
    return jsonify({
        "ok": False,
        "error": f"롯데온 API 실패 — HTTP {r.status_code}",
        "status_code": r.status_code,
        "elapsed_sec": elapsed,
        "body_snippet": (r.text or "")[:300],
        "hint": hint,
    }), 502


def _test_esm(creds, display_name: str, env_prefix: str, market: str):
    """옥션·G마켓(ESM 2.0) 연결 테스트 — JWT 인증으로 read-only 주문조회 1건 프로브.

    RequestOrders(읽기 전용, 5초/1회 rate limit)를 최근 1일·pageSize=1 로 호출해
    인증(JWT 서명)+조회 라운드트립을 확인한다. 실제 값 변경 없음(identity+read).
    401=JWT/키 오류 · 403=IP 미등록/판매도구 미사용 · 429=호출초과.
    """
    import time as _time
    import datetime as _dt
    import requests
    from shared.platforms import AUCTION, GMARKET
    from shared.platforms.esm.auth import build_headers

    cfg = AUCTION if market == "auction" else GMARKET
    base = (cfg.get("base_url") or "https://sa2.esmplus.com").rstrip("/")
    path = (cfg.get("paths") or {}).get("orders") or "/shipping/v1/Order/RequestOrders"
    site_type = 1 if market == "auction" else 2
    now = _dt.datetime.now()
    body = {
        "siteType": site_type,
        "orderStatus": 1,
        "requestDateType": 1,
        "requestDateFrom": (now - _dt.timedelta(days=1)).strftime("%Y-%m-%d %H:%M"),
        "requestDateTo": now.strftime("%Y-%m-%d %H:%M"),
        "pageIndex": 1,
        "pageSize": 1,
    }
    try:
        headers = build_headers(
            creds.master_id, creds.secret_key, cfg.get("site_id", ""), creds.seller_id,
            issuer=cfg.get("auth_issuer", "www.esmplus.com"),
            audience=cfg.get("auth_audience", "sa.esmplus.com"),
            iat=int(_time.time()),
        )
    except Exception as e:
        return jsonify({"ok": False, "error": f"JWT 생성 실패 — {e}",
                        "hint": "마스터ID·시크릿키·판매자ID 를 다시 확인하세요."}), 400

    started = _time.time()
    try:
        r = requests.post(base + path, json=body, headers=headers, timeout=15)
    except Exception as e:
        return jsonify({"ok": False, "error": f"네트워크 오류: {type(e).__name__}: {e}",
                        "elapsed_sec": round(_time.time() - started, 2)}), 500

    elapsed = round(_time.time() - started, 2)
    label = "옥션" if market == "auction" else "G마켓"
    if r.status_code == 200:
        try:
            data = r.json()
            rc = str(data.get("ResultCode"))
            if rc in ("0", "None"):
                return jsonify({
                    "ok": True,
                    "message": f"✅ {display_name} {label} ESM API 연결 성공 (JWT 인증 OK, 응답 {elapsed}s)",
                    "status_code": 200, "elapsed_sec": elapsed, "seller_id": creds.seller_id,
                })
            return jsonify({"ok": False, "error": f"{label} 응답 이상 — ResultCode={rc}",
                            "status_code": 200, "elapsed_sec": elapsed,
                            "body_snippet": (r.text or "")[:300]}), 502
        except Exception:
            return jsonify({"ok": True, "message": f"✅ {label} ESM API 응답 (200, JSON 파싱 실패)",
                            "status_code": 200, "elapsed_sec": elapsed})

    hint = {
        401: "JWT 인증 실패 — 마스터ID·시크릿키 확인(ESM+ 판매도구 관리에서 재발급)",
        403: "권한 없음 — 판매도구 사용 '사용' 설정 / 서버 IP(54.116.196.90) 등록 확인",
        429: "호출 횟수 초과 — 잠시 후 재시도(주문조회 5초당 1회)",
    }.get(r.status_code, "마스터ID·시크릿키·판매자ID 가 정확한지 확인")
    return jsonify({
        "ok": False, "error": f"{label} ESM API 실패 — HTTP {r.status_code}",
        "status_code": r.status_code, "elapsed_sec": elapsed,
        "body_snippet": (r.text or "")[:300], "hint": hint,
    }), 502


def _test_eleven11(creds, display_name: str, env_prefix: str):
    """11번가 셀러 OpenAPI ping — 최근 6시간 결제완료 주문 목록 조회(읽기 전용).

    프로덕션 주문조회가 쓰는 경로(iter_orders)를 그대로 쓴다 — 테스트가 통과했는데 실제
    주문조회가 실패하는 어긋남을 막기 위해. 주문 0건도 성공(인증·IP 통과가 판정 대상).
    """
    import time as _time
    import datetime as _dt2

    started = _time.time()
    try:
        from lemouton.uploader.market_fetch import _eleven11_client
        from shared.platforms.eleven11.orders import iter_orders
        client = _eleven11_client(env_prefix)
        until = _dt2.datetime.now()
        since = until - _dt2.timedelta(hours=6)
        seen = 0
        for _od in iter_orders(since, until, client=client):
            seen += 1
            if seen >= 1:
                break                      # 1건만 확인하면 충분(전량 조회 안 함)
    except Exception as e:                 # noqa: BLE001 — 사유를 그대로 표면화(키 미노출)
        elapsed = round(_time.time() - started, 2)
        msg = f"{type(e).__name__}: {e}"
        hint = ""
        if "403" in msg:
            hint = "403 — 11번가 API 센터에 서버 IP(54.116.196.90) 등록이 필요합니다."
        elif "401" in msg:
            hint = "401 — OPENAPI KEY 를 다시 확인하세요."
        elif "500" in msg:
            hint = "500 — 11번가 서버 오류. 잠시 후 다시 시도하세요."
        return jsonify({"ok": False, "error": msg[:300], "hint": hint,
                        "elapsed_sec": elapsed}), 400

    elapsed = round(_time.time() - started, 2)
    return jsonify({
        "ok": True,
        "market": "eleven11",
        "account": display_name,
        "detail": f"최근 6시간 결제완료 주문 {seen}건 조회 성공(인증·IP 통과)",
        "elapsed_sec": elapsed,
    })


def _test_smartstore(creds, display_name: str, env_prefix: str):
    """스마트스토어 OAuth 토큰 발급 시도 — Bcrypt 서명."""
    import time as _time
    import bcrypt
    import base64
    import requests

    started = _time.time()
    timestamp = str(int(_time.time() * 1000))
    password = f"{creds.client_id}_{timestamp}".encode("utf-8")
    # ★ 잘못된 salt 를 bcrypt 에 넘기면 파이썬 예외가 아니라 네이티브에서 죽어 워커가 통째로
    #   내려간다(try/except 로 못 잡음 → 원인 없는 빈 502). bcrypt 를 부르기 '전에' 형식 검사.
    from shared.platforms.smartstore.auth import (
        is_valid_client_secret, normalize_client_secret)
    if not is_valid_client_secret(creds.client_secret):
        return jsonify({
            "ok": False,
            "error": "Client Secret 형식 오류 — bcrypt salt 형식이 아닙니다.",
            "hint": "네이버 커머스 API 센터의 Client Secret 을 그대로 다시 입력하세요"
                    " (앞뒤 공백·줄바꿈 없이, $2a$ 로 시작하는 전체 문자열 29자).",
            "elapsed_sec": round(_time.time() - started, 2),
        }), 400
    hashed = bcrypt.hashpw(password, normalize_client_secret(creds.client_secret).encode("utf-8"))
    client_secret_sign = base64.standard_b64encode(hashed).decode("utf-8")

    try:
        r = requests.post(
            "https://api.commerce.naver.com/external/v1/oauth2/token",
            data={
                "client_id": creds.client_id,
                "timestamp": timestamp,
                "grant_type": "client_credentials",
                "client_secret_sign": client_secret_sign,
                "type": "SELF",
            },
            timeout=15,
        )
    except Exception as e:
        elapsed = round(_time.time() - started, 2)
        return jsonify({
            "ok": False,
            "error": f"네트워크 오류: {type(e).__name__}: {e}",
            "elapsed_sec": elapsed,
        }), 500

    elapsed = round(_time.time() - started, 2)
    if r.status_code != 200:
        body_snippet = (r.text or "")[:300]
        hint = ""
        if r.status_code == 403:
            hint = ("403 — 해외 IP 차단 또는 셀러센터 API 허용목록 미등록. "
                    "AWS 서버라면 네이버 커머스 API 센터에 서버 IP(54.116.196.90) 등록 필요.")
        elif r.status_code == 401:
            hint = "401 — Client ID/Secret 또는 서명 오류. 키를 다시 확인하세요."
        return jsonify({
            "ok": False,
            "error": f"스마트스토어 OAuth 실패 — HTTP {r.status_code}",
            "status_code": r.status_code,
            "elapsed_sec": elapsed,
            "body_snippet": body_snippet,
            "hint": hint,
        }), 502

    # ── 토큰 발급 성공 → 상품/재고 조회까지 검증 (읽기 전용) ──
    data = r.json()
    token = data.get("access_token", "")
    steps = [f"토큰 발급 성공 ({elapsed}s)"]
    product_count = None
    sample = None
    try:
        from shared.platforms.smartstore.client import SmartStoreClient
        client = SmartStoreClient()
        resp = client.request("POST", "/external/v1/products/search",
                              body={"page": 1, "size": 5})
        contents = (resp or {}).get("contents") or []
        product_count = (resp or {}).get("totalElements", len(contents))
        steps.append(f"상품 목록 조회 성공 (전체 {product_count}건)")

        # 첫 상품의 옵션별 재고 조회
        first_origin = contents[0].get("originProductNo") if contents else None
        if first_origin:
            from shared.platforms.smartstore.get_options import fetch_product_options
            opt = fetch_product_options(int(first_origin), client=client)
            if opt.success:
                stock_total = sum(o.stock for o in opt.options)
                sample = {
                    "origin_product_no": first_origin,
                    "name": opt.product_name,
                    "sale_price": opt.sale_price,
                    "option_count": len(opt.options),
                    "stock_total": stock_total,
                }
                steps.append(
                    f"재고 조회 성공 — '{opt.product_name}' "
                    f"옵션 {len(opt.options)}개 / 총재고 {stock_total}"
                )
    except Exception as e:  # noqa: BLE001
        steps.append(f"⚠️ 상품/재고 조회 단계 실패: {type(e).__name__}: {e}")

    return jsonify({
        "ok": True,
        "message": f"✅ {display_name} 연결 성공 — " + " · ".join(steps),
        "status_code": r.status_code,
        "elapsed_sec": elapsed,
        "token_masked": (token[:8] + "***") if token else "<empty>",
        "expires_in": data.get("expires_in"),
        "product_count": product_count,
        "sample": sample,
    })


# ──────────────────────────────────────────────────────────
#  라이브 검증 — 실주문을 대조한 뒤에만 그 마켓을 공개한다
# ──────────────────────────────────────────────────────────

_LIVE_VERIFY_DAYS = 7
# 주문 한 행이 갖춰야 할 최소 항목. 하나라도 비면 그 마켓 숫자는 믿을 수 없다.
_LIVE_VERIFY_REQUIRED = ("오픈마켓주문번호", "주문일", "상품명", "단가")


def _market_label_of(market: str) -> str:
    """마켓 한글명(없으면 원문)."""
    return (MARKET_METADATA.get(market) or {}).get("label", market)


def _live_verify_fetch(market: str, env_prefix: str, days: int = _LIVE_VERIFY_DAYS,
                       diag: dict = None) -> list:
    """이 계정 하나의 실주문 조회. 공개 게이트를 거치지 않는다(게이트를 열기 위한 조회).

    테스트는 이 함수를 스텁으로 갈아끼운다.
    """
    import datetime as _dt
    from lemouton.markets import order_export as _oe

    cli = _oe._account_client(market, env_prefix)
    if cli is None:
        raise RuntimeError("API 키가 등록돼 있지 않습니다 — 먼저 🔑 키로 등록하세요.")
    until = _dt.datetime.now(_oe.KST)
    since = until - _dt.timedelta(days=days)
    # 정산 조인은 검증에 불필요하고 호출만 늘린다(ESM 주문조회 5초/1회 제한).
    if market in _oe.LIVE_VERIFIABLE:
        # 조회별 건수를 본 조회에서 함께 받는다 — 진단이 다시 부르면 호출이 2배가 되고
        # 응답이 게이트웨이 한계를 넘어 502 가 난다(2026-07-20 라이브 실측).
        return _oe.esm_order_rows(market, since, until, client=cli,
                                  include_settlement=False, diag=diag)
    return _oe._BUILDERS[market](since, until, client=cli, include_settlement=False)




# ★ ESM 주문조회(RequestOrders)는 클레임 주문을 반환하지 않는다.
#   공식문서 원문(etapi.gmarket.com/67): "클레임(취소, 반품, 교환, 미수령신고) 주문은
#   조회되지 않습니다". 이 상태로 옥션·G마켓을 공개하면 취소·반품 주문이 통째로 빠진
#   주문내역이 된다 — 다른 마켓은 취소·반품이 잡히므로 마켓 간 집계 기준까지 어긋난다.
#   실증(2026-07-20): 브랜드타임즈(rnwhgowh3)는 마켓 화면에 환불완료 1건이 있는데
#   우리 조회 결과는 0건이었다.
#   → 클레임 API(취소·반품·교환·미수령) 배선이 끝나면 True 로 바꾼다.
_ESM_CLAIM_WIRED = True   # 2026-07-20 esm/claims.py 배선 + order_export 병합 완료
_ESM_CLAIM_MARKETS = ("auction", "gmarket")


def _live_verify_judge(rows: list, market: str = ""):
    """자동 판정 → (통과여부, 문제목록, 샘플 3건).

    · 옥션·G마켓은 클레임 조회 미배선 동안 통과시키지 않는다(위 주석).
    · 0건 = 대조할 데이터가 없음 → '확인 불가'. 통과시키지 않는다(있다고 단정 금지).
    · 필수 항목 결측 → 통과 아님. 어떤 항목이 몇 건 비었는지 그대로 알린다.
    샘플에는 개인정보(수령자·전화·주소)를 담지 않는다 — 대조에 필요한 것만.
    """
    issues, tech, blocked = [], [], False
    if market in _ESM_CLAIM_MARKETS and not _ESM_CLAIM_WIRED:
        blocked = True
        issues.append(
            "취소·반품·교환 주문이 조회되지 않습니다 — ESM 주문조회 API 사양입니다"
            "(공식문서: 「클레임 주문은 조회되지 않습니다」). 지금 공개하면 옥션·G마켓만 "
            "취소·반품이 빠진 채 집계돼 다른 마켓과 숫자 기준이 어긋납니다. "
            "클레임 조회를 붙인 뒤 다시 검증해 주세요.")

    if not rows:
        issues.append("최근 7일 주문이 0건이라 확인 불가 — 주문이 있는 계정으로 검증하거나, "
                      "정말 0건이 맞는지 마켓 화면에서 확인해 주세요.")
        return False, issues, [], tech

    # 클레임(취소·반품·교환)은 마켓이 상품명·금액을 안 준다. 주문번호로 상세를 다시
    # 불러 채우지만 그것마저 실패하면 빈칸이 남는다. 이 경우를 '데이터가 깨진 주문'과
    # 같이 취급하면 영영 통과하지 못한다 → 사유를 따로 알리되 통과는 막지 않는다.
    # (취소된 주문은 매출이 0이므로 단가가 비어도 집계가 틀어지지 않는다)
    no_detail = [r for r in rows if r.get("_detail_missing")]
    if no_detail:
        # ★ 사장님이 읽을 문장과 개발자용 기술 상세를 나눈다.
        #   화면에 "HTTPError: 404 Client Error: for url ..." 같은 게 뜨면 읽을 수 없다.
        nos = ", ".join(str(r.get("오픈마켓주문번호")) for r in no_detail[:5])
        # 마켓이 사유를 밝혔으면 그 말을 그대로 쓴다(추측 대신 마켓의 답).
        first = str(no_detail[0].get("_detail_missing") or "")
        why_ko = ("삭제된 상품이라 마켓이 상품명을 주지 않습니다"
                  if "삭제된 상품" in first else
                  "그 상품을 마켓 상품 조회에서 찾을 수 없습니다")
        issues.append(
            f"취소된 주문 {len(no_detail)}건은 상품명이 비어 있습니다 — {why_ko}. "
            f"마켓 주문 화면에는 주문 당시 이름이 남아 있지만, 저희가 쓸 수 있는 "
            f"방법으로는 가져올 수 없습니다(주문번호 {nos}). "
            f"주문 자체는 정상적으로 잡혔습니다.")
        for r in no_detail[:3]:
            tech.append(f"{r.get('오픈마켓주문번호')} — {str(r.get('_detail_missing'))[:200]}")

    # 상품명은 상품 API 로 채웠지만 단가는 못 채운 클레임 행.
    # 단가는 '주문 시점 결제금액'이라 상품 API 의 현재가로 대신할 수 없다(폴백 금지).
    # 취소 주문은 매출이 0이라 단가가 비어도 집계가 틀어지지 않으므로 통과시킨다.
    partial = [r for r in rows if r.get("_detail_partial")]
    if partial:
        issues.append(f"클레임 {len(partial)}건은 상품명만 채웠고 단가는 빈칸입니다 — "
                      f"마켓이 취소 주문의 결제금액을 주지 않습니다"
                      f"(취소분은 매출 0이라 집계에는 영향 없음).")

    missing = {}
    for r in rows:
        if r.get("_detail_missing") or r.get("_detail_partial"):
            continue                     # 위에서 따로 알린 건 — 중복 경고 방지
        for k in _LIVE_VERIFY_REQUIRED:
            if str(r.get(k, "") or "").strip() == "":
                missing[k] = missing.get(k, 0) + 1
    for k, n in sorted(missing.items()):
        issues.append(f"「{k}」가 비어 있는 주문이 {n}건 있어요 — 이대로 열면 숫자가 틀어집니다.")

    samples = [{
        "주문번호": str(r.get("오픈마켓주문번호", "")),
        "주문일": str(r.get("주문일", "")).replace("T", " ")[:16],
        "상품명": str(r.get("상품명", ""))[:40],
        "단가": str(r.get("단가", "")),
        "수량": str(r.get("수량", "")),
        "주문상태": str(r.get("주문상태", "")),
        # 클레임 사유(취소/반품/교환) — 마켓 화면의 「취소사유·상세취소사유」와 대조용.
        # 일반 주문에서는 배송 요청사항이 들어온다.
        "사유/배송메시지": str(r.get("배송메시지", "")),
    } for r in rows[:3]]
    return (not missing and not blocked), issues, samples, tech


@bp.route("/api/upload/accounts/<int:account_id>/verify-live", methods=["POST"])
def verify_live_account(account_id: int):
    """라이브 검증 실행 — 실주문을 불러와 자동판정 + 샘플 3건 반환.

    ★ 여기서는 기록하지 않는다. 사장님이 샘플을 마켓 화면과 대조한 뒤
      /verify-live/confirm 을 눌러야 저장되고 마켓이 열린다.
    """
    from lemouton.markets import order_export as _oe

    s = SessionLocal()
    try:
        acc = s.query(UploadAccount).get(account_id)
        if not acc:
            return jsonify({"ok": False, "error": "계정 없음"}), 404
        market, prefix, name = acc.market, acc.env_prefix, acc.display_name
    finally:
        s.close()

    if market not in _oe.LIVE_VERIFIABLE:
        return jsonify({
            "ok": False,
            "error": f"'{_market_label_of(market)}' 은(는) 라이브 검증 대상이 아닙니다.",
            "hint": "이미 공개된 마켓이거나, 주문조회 코드가 아직 없는 마켓입니다.",
        }), 400

    diag = {}
    # 클레임 응답에 '실제로' 어떤 필드가 오는지 키만 확인한다(값은 담지 않는다).
    #  문서·지도의 필드 목록이 실제 응답과 다를 수 있어, 상품명이 정말 안 오는지
    #  눈으로 확인할 유일한 방법이다.
    # 클레임 조회가 조용히 잘리는지 확인 — 응답 wrapper 에 TotalCount 가 있고
    # 그게 실제 받은 건수보다 크면 우리는 일부만 보고 있는 것이다(조용한 유실).
    # 대조표용 — 우리가 잡은 전체 주문번호를 상태별로 나열(샘플 3건 한계 없이).
    #  ESM+ 화면 건수와 1:1 대조할 때 쓴다. 읽기 전용, 개인정보 없음(번호·상태만).
    # G마켓 취소가 우리 조회에 왜 안 잡히는지 — 실제 요청 body 와 응답을 그대로 본다.
    #  Type(2=신청일 / 3=완료일)·기간별로 취소 건수를 비교한다.
    # 특정 주문번호로 취소조회 — 그 취소가 어느 SiteType·Type 로 잡히는지 직접 확인.
    if request.args.get("probe") == "cancelno" and market in _oe.LIVE_VERIFIABLE:
        import datetime as _dn
        from shared.platforms.esm import claims as _cn
        clin = _oe._account_client(market, prefix)
        um = _dn.datetime.now(_oe.KST)
        ono = (request.args.get("no") or "").strip()
        out = []
        for site in (2, 3):
            for tp in (0, 2, 3):        # 0=주문번호 기준
                # Type 0(주문번호)은 기간을 안 봐서 25일, 2·3(날짜)은 7일 제한.
                dd = 25 if tp == 0 else 7
                a = (um - _dn.timedelta(days=dd)).strftime("%Y-%m-%d")
                b = um.strftime("%Y-%m-%d")
                body = {"SiteType": site, "Type": tp, "CancelStatus": 0,
                        "OrderNo": int(ono) if ono else 0,
                        "StartDate": a, "EndDate": b}
                try:
                    resp = clin.post(_cn.PATHS["cancels"], body) or {}
                    data = resp.get("Data")
                    n = len(data) if isinstance(data, list) else 0
                    hit_row = next((x for x in (data or []) if str(x.get("OrderNo"))==ono), None) if isinstance(data, list) else None
                    out.append({"조건": f"Site{site}·Type{tp}",
                                "RC": resp.get("ResultCode"), "msg": (resp.get("Message") or "")[:40],
                                "건수": n, "찾음": bool(hit_row),
                                "CancelStatus": hit_row.get("CancelStatus") if hit_row else None,
                                "RequestDate": (hit_row.get("RequestDate") or "")[:16] if hit_row else None,
                                "CompleteDate": (hit_row.get("CompleteDate") or "")[:16] if hit_row else None})
                except Exception as e:      # noqa: BLE001
                    out.append({"조건": f"Site{site}·Type{tp}", "err": f"{type(e).__name__}: {e}"[:90]})
        return jsonify({"ok": True, "probe": "cancelno", "주문번호": ono, "결과": out})

    if request.args.get("probe") == "cancelmatch" and market in _oe.LIVE_VERIFIABLE:
        import datetime as _dm
        from shared.platforms.esm import claims as _cm
        clim = _oe._account_client(market, prefix)
        um = _dm.datetime.now(_oe.KST)
        out = []
        for site in (1, 2, 3):          # 어느 SiteType 값에서 나오는지 전부 시험
            for tp_label, tp in (("신청일2", 2), ("완료일3", 3)):
                a = (um - _dm.timedelta(days=7)).strftime("%Y-%m-%d")
                b = um.strftime("%Y-%m-%d")
                body = {"SiteType": site, "Type": tp, "CancelStatus": 0,
                        "StartDate": a, "EndDate": b}
                try:
                    resp = clim.post(_cm.PATHS["cancels"], body) or {}
                    data = resp.get("Data")
                    nos = [str(x.get("OrderNo")) for x in data] if isinstance(data, list) else []
                    out.append({"조건": f"Site{site}·{tp_label}", "SiteType": site,
                                "ResultCode": resp.get("ResultCode"),
                                "건수": len(nos), "주문번호": nos})
                except Exception as e:      # noqa: BLE001
                    out.append({"조건": f"Site{site}·{tp_label}", "err": f"{type(e).__name__}: {e}"[:90]})
        return jsonify({"ok": True, "probe": "cancelmatch", "market": market, "결과": out})

    # 주문일 기준 전체 주문번호 — 마켓 「주문관리(주문일)」 화면과 1:1 대조용.
    #  주문조회(orderStatus 1~5, 주문일 기준) 만 쓴다. 클레임은 신청/완료일 기준이라
    #  주문일 화면과 안 맞으므로 제외. 즉 "그날 주문된 것 전부"를 그대로 본다.
    if request.args.get("probe") == "byorderdate" and market in _oe.LIVE_VERIFIABLE:
        import datetime as _dz
        from shared.platforms.esm.orders import iter_orders as _io
        cliz = _oe._account_client(market, prefix)
        days = int(request.args.get("days") or 7)
        uz = _dz.datetime.now(_oe.KST)
        sz = uz - _dz.timedelta(days=days)
        seen, out = set(), []
        for od in _io(market, sz, uz, client=cliz):
            no = str(od.get("OrderNo") or "")
            if no and no not in seen:
                seen.add(no)
                out.append({"주문번호": no,
                            "상태": _oe._status_ko("esm", od.get("OrderStatus")),
                            "주문일": str(od.get("OrderDate") or "")[:16].replace("T", " "),
                            "종류": "주문"})
        # ★ 사장님 「주문일 기준」 화면에는 취소·반품·교환도 섞여 있다. 클레임은 주문조회에
        #   안 나오니 따로 합친다. 클레임은 주문일이 응답에 있으므로 그 주문일이 기간 안이면 포함.
        from shared.platforms.esm import claims as _clz
        for fn, kk in ((_clz.iter_cancels, "취소"), (_clz.iter_returns, "반품"),
                       (_clz.iter_exchanges, "교환")):
            try:
                for cd in fn(market, sz, _oe._until_now(uz), client=cliz):
                    no = str(cd.get("OrderNo") or "")
                    od_date = str(cd.get("OrderDate") or "")[:16].replace("T", " ")
                    if no and no not in seen and od_date >= sz.strftime("%Y-%m-%d"):
                        seen.add(no)
                        out.append({"주문번호": no, "상태": kk + "완료",
                                    "주문일": od_date, "종류": kk})
            except Exception:  # noqa: BLE001 — 한 종류 실패해도 나머지는 본다
                pass
        out.sort(key=lambda x: x["주문일"], reverse=True)
        return jsonify({"ok": True, "probe": "byorderdate", "days": days,
                        "count": len(out), "orders": out})

    if request.args.get("probe") == "orderlist" and market in _oe.LIVE_VERIFIABLE:
        import datetime as _d4
        cli4 = _oe._account_client(market, prefix)
        u4 = _d4.datetime.now(_oe.KST)
        s4 = u4 - _d4.timedelta(days=_LIVE_VERIFY_DAYS)
        diag4 = {}
        rows4 = _oe.esm_order_rows(market, s4, u4, client=cli4,
                                   include_settlement=False, diag=diag4)
        lst = [{"주문번호": str(r.get("오픈마켓주문번호", "")),
                "상태": str(r.get("주문상태", "")),
                "주문일": str(r.get("주문일", ""))[:16].replace("T", " ")}
               for r in rows4]
        return jsonify({"ok": True, "probe": "orderlist", "days": _LIVE_VERIFY_DAYS,
                        "count": len(lst), "counts": diag4.get("counts") or {},
                        "orders": lst})

    if request.args.get("probe") == "claimtrunc" and market in _oe.LIVE_VERIFIABLE:
        import datetime as _d3
        from shared.platforms.esm import claims as _c3
        cli3 = _oe._account_client(market, prefix)
        days = int(request.args.get("days") or 90)
        u3 = _d3.datetime.now(_oe.KST)
        s3 = u3 - _d3.timedelta(days=days)
        out = []
        for label, api, field, sts in (
                ("취소", "cancels", "CancelStatus", (0,)),
                ("반품", "returns", "ReturnStatus", (1, 4)),
                ("교환", "exchanges", "ExchangeStatus", (1, 4))):
            for w_from, w_to in _c3._windows(s3, u3, _c3._CLAIM_WINDOW_DAYS):
                for st in sts:
                    body = {"SiteType": _c3.site_code(market, api), "Type": 2,
                            field: st,
                            "StartDate": w_from.strftime("%Y-%m-%d"),
                            "EndDate": w_to.strftime("%Y-%m-%d")}
                    try:
                        resp = cli3.post(_c3.PATHS[api], body) or {}
                    except Exception as e:      # noqa: BLE001
                        out.append({"구분": label, "기간": body["StartDate"],
                                    "err": f"{type(e).__name__}"[:40]})
                        continue
                    data = resp.get("Data")
                    n = len(data) if isinstance(data, list) else 0
                    if n:
                        out.append({"구분": label, "상태": st,
                                    "기간": f'{body["StartDate"]}~{body["EndDate"]}',
                                    "받은건수": n,
                                    "wrapper키": sorted(k for k in resp if k != "Data"),
                                    "TotalCount": resp.get("TotalCount")})
        return jsonify({"ok": True, "probe": "claimtrunc", "days": days,
                        "합계": sum(x.get("받은건수", 0) for x in out), "구간": out[:40]})

    # 상품번호 매핑 API 가 '실제로' 뭐라고 답하는지 본다.
    #  resolve_goods_no 가 예외를 삼키고 입력을 그대로 돌려주기 때문에, 왜 실패했는지가
    #  코드 안에서 사라진다. 삭제된 상품인지·권한 문제인지·형식 문제인지 구분이 안 된다.
    if request.args.get("probe") == "sitegoods" and market in _oe.LIVE_VERIFIABLE:
        cli4 = _oe._account_client(market, prefix)
        paths4 = (getattr(cli4, "_cfg", None) or {}).get("paths") or {}
        out4 = []
        for sgn in (request.args.get("nos") or "").split(","):
            sgn = sgn.strip()
            if not sgn:
                continue
            item = {"SiteGoodsNo": sgn}
            for label, tmpl_key, fmt_key in (("매핑", "site_goods_map", "siteGoodsNo"),
                                             ("상세", "detail", "goodsNo")):
                tmpl = paths4.get(tmpl_key)
                if not tmpl:
                    item[label] = "경로 미설정"
                    continue
                # ★ client.request 는 raise_for_status 로 **응답 본문을 버린다**.
                #   마켓이 400 과 함께 이유를 적어 보내는데 그걸 못 본다.
                #   직접 호출해 본문까지 확보한다 — 이유가 거기 있다.
                import requests as _rq
                from shared.platforms.esm.auth import build_headers as _bh
                cfg4 = getattr(cli4, "_cfg", {}) or {}
                try:
                    hdr = _bh(cfg4.get("master_id", ""), cfg4.get("secret_key", ""),
                              cfg4.get("site_id", ""), cfg4.get("seller_id", ""),
                              issuer=cfg4.get("auth_issuer", "www.esmplus.com"),
                              audience=cfg4.get("auth_audience", "sa.esmplus.com"))
                    url4 = (cfg4.get("base_url") or "").rstrip("/") + tmpl.format(**{fmt_key: sgn})
                    rr = _rq.get(url4, headers=hdr, timeout=20)
                    item[label] = f"HTTP {rr.status_code} · {(rr.text or '')[:220]}"
                except Exception as e:      # noqa: BLE001 — 원문을 그대로 본다
                    item[label] = f"ERR {type(e).__name__}: {e}"[:220]
            out4.append(item)
        return jsonify({"ok": True, "probe": "sitegoods", "items": out4})

    if request.args.get("probe") == "claimkeys" and market in _oe.LIVE_VERIFIABLE:
        import datetime as _d2
        from shared.platforms.esm import claims as _c2
        cli2 = _oe._account_client(market, prefix)
        u2 = _d2.datetime.now(_oe.KST)
        try:
            got = list(_c2.iter_cancels(market, u2 - _d2.timedelta(days=_LIVE_VERIFY_DAYS),
                                        u2, client=cli2))
        except Exception as e:      # noqa: BLE001
            return jsonify({"ok": False, "probe": f"{type(e).__name__}: {e}"}), 200
        # 상품번호가 실제로 어떤 값인지 + 변환·상세조회가 어디서 막히는지까지 본다.
        from shared.platforms.esm import products as _p2
        probe = []
        for g in got[:3]:
            gno, sgn = g.get("GoodsNo"), g.get("SiteGoodsNo")
            item = {"OrderNo": g.get("OrderNo"), "GoodsNo": gno, "SiteGoodsNo": sgn}
            try:
                item["resolved"] = _p2.resolve_goods_no(str(sgn), client=cli2)
            except Exception as e:      # noqa: BLE001
                item["resolved"] = f"ERR {type(e).__name__}: {e}"[:90]
            try:
                det = _p2.get_goods_detail(str(item.get("resolved") or sgn), client=cli2)
                item["detail_keys"] = sorted(det)[:8] if isinstance(det, dict) else str(type(det))
            except Exception as e:      # noqa: BLE001
                item["detail"] = f"ERR {type(e).__name__}: {e}"[:110]
            probe.append(item)
        return jsonify({"ok": True, "probe": "claimkeys", "count": len(got),
                        "keys": sorted({k for g in got for k in g}), "items": probe})

    try:
        rows = _live_verify_fetch(market, prefix, diag=diag)
    except Exception as e:  # noqa: BLE001 — 원인을 그대로 보여준다(조용한 실패 금지).
        return jsonify({"ok": False, "error": f"주문 조회 실패 — {type(e).__name__}: {e}",
                        "hint": "🔌 연결 테스트가 통과하는지, 서버 IP가 등록됐는지 확인하세요."}), 502

    auto_pass, issues, samples, tech = _live_verify_judge(rows, market)
    # 어느 조회가 몇 건을 줬는지 — 본 조회에서 이미 세어 왔다(추가 호출 없음).
    counts = (diag.get("counts") or {})
    order = ["주문조회", "입금확인중", "취소", "반품", "교환", "미수령"]
    sources = [{"name": n, "count": counts.get(n, 0), "error": None}
               for n in order if n in counts or n in ("주문조회",)]
    for name, err in (diag.get("errors") or {}).items():
        sources.append({"name": name, "count": None, "error": err})
        issues.append("취소·반품·교환 조회가 실패했습니다. 잠시 후 다시 눌러보시고, "
                      "계속 같으면 알려주세요.")
        tech.append(f"{name} — {err}")
        auto_pass = False
    return jsonify({
        "ok": True, "account": name, "market": market,
        "market_label": _market_label_of(market),
        "count": len(rows), "samples": samples, "sources": sources,
        "auto_pass": auto_pass, "issues": issues, "tech": tech,
        "days": _LIVE_VERIFY_DAYS,
    })


@bp.route("/api/upload/accounts/<int:account_id>/verify-live/confirm", methods=["POST"])
def verify_live_confirm(account_id: int):
    """사장님이 마켓 화면과 대조하고 「맞음」을 누름 → 검증 기록 저장.

    자동판정이 실패한 건은 저장을 거부한다. 깨진 데이터를 확인 버튼으로 덮으면
    틀린 숫자가 주문내역·마진계산기로 그대로 들어간다.
    """
    import datetime as _dt
    from lemouton.markets import order_export as _oe

    s = SessionLocal()
    try:
        acc = s.query(UploadAccount).get(account_id)
        if not acc:
            return jsonify({"ok": False, "error": "계정 없음"}), 404
        if acc.market not in _oe.LIVE_VERIFIABLE:
            return jsonify({"ok": False, "error": "라이브 검증 대상이 아닙니다."}), 400
        market, prefix, name = acc.market, acc.env_prefix, acc.display_name
    finally:
        s.close()

    # 확인 직전에 한 번 더 조회해 판정한다(화면에 띄워둔 사이 상황이 바뀌었을 수 있다).
    try:
        rows = _live_verify_fetch(market, prefix)
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "error": f"주문 조회 실패 — {type(e).__name__}: {e}"}), 502

    auto_pass, issues, _samples, _tech = _live_verify_judge(rows, market)
    # ★ 0건 확인 승인 — 주문이 0건이면 자동판정은 '확인 불가'로 막는다. 그러나 사장님이
    #   마켓 화면에서 "정말 0건"임을 직접 확인한 경우, 0 = 0 도 유효한 대조다
    #   (live_verified_count=0 은 처음부터 유효한 기록으로 설계됨).
    #   confirm_zero 는 그 확인을 명시하는 플래그 — 0건이 '유일한' 문제일 때만 통한다
    #   (클레임 미배선·데이터 결측 등 다른 사유가 있으면 여전히 409).
    body = request.get_json(silent=True) or {}
    zero_ok = (not rows) and body.get("confirm_zero") is True and all(
        "확인 불가" in i for i in issues)
    if not auto_pass and not zero_ok:
        return jsonify({"ok": False,
                        "error": "자동 판정을 통과하지 못해 저장하지 않았습니다.",
                        "issues": issues}), 409

    s = SessionLocal()
    try:
        acc = s.query(UploadAccount).get(account_id)
        acc.live_verified_at = _dt.datetime.now()
        acc.live_verified_count = len(rows)
        s.commit()
    except Exception as e:  # noqa: BLE001
        s.rollback()
        return jsonify({"ok": False, "error": f"DB 저장 실패: {type(e).__name__}: {e}"}), 500
    finally:
        s.close()

    opened = market in _oe.supported_markets()
    return jsonify({
        "ok": True, "account": name, "market": market, "count": len(rows),
        "market_opened": opened,
        "message": (f"✅ {name} 검증 완료 — {_market_label_of(market)}가 주문내역·마진계산기에 "
                    f"공개됐습니다." if opened else
                    f"✅ {name} 검증 완료 — 같은 마켓의 나머지 계정도 검증하면 공개됩니다."),
    })


@bp.route("/api/upload/esm-auto-verify", methods=["POST"])
def esm_auto_verify():
    """옥션·G마켓 계정을 **데이터가 있는 90일 창**으로 라이브 검증한다.

    ESM 은 주문이 드물어 기본 7일 창은 0건이 되기 쉽다(0건=확인불가로 통과 못 함).
    이 마켓들은 이미 백필로 실주문 조회가 검증됐으므로, 데이터가 실리는 넓은 창으로
    정석 판정(_live_verify_judge)을 돌려 통과하면 live_verified_at 을 저장한다.
    통과한 계정만 저장한다(판정 실패는 저장 거부 — 깨진 데이터 공개 금지).
    """
    import datetime as _dt
    from lemouton.markets import order_export as _oe

    want = (request.get_json(silent=True) or {}).get("market")
    mkts = [want] if want in _oe.LIVE_VERIFIABLE else sorted(_oe.LIVE_VERIFIABLE)
    s = SessionLocal()
    try:
        accs = (s.query(UploadAccount)
                .filter(UploadAccount.market.in_(mkts),
                        UploadAccount.is_active.is_(True))
                .all())
        targets = [(a.id, a.market, a.env_prefix, a.display_name) for a in accs]
    finally:
        s.close()

    if not targets:
        return jsonify({"ok": False,
                        "error": "옥션·G마켓 활성 계정이 없습니다 — 먼저 키를 등록하세요."}), 400

    # 이미 검증된 계정은 조회 없이 건너뛴다(빠름). 미검증 계정은 한 요청에 하나만
    #  처리하고 즉시 반환한다 — 계정이 여러 개면 순차로 다 하면 gunicorn 60초를 넘겨
    #  502 가 난다. 호출자가 done=false 인 동안 반복 호출한다.
    from lemouton.markets.models_orders import MarketOrderLine  # noqa: F401 (import 검사)
    s2 = SessionLocal()
    try:
        verified_ids = {a.id for a in s2.query(UploadAccount).filter(
            UploadAccount.id.in_([t[0] for t in targets]),
            UploadAccount.live_verified_at.isnot(None)).all()}
    finally:
        s2.close()
    results = [{"account": t[3], "market": t[1], "saved": True, "skipped": True}
               for t in targets if t[0] in verified_ids]
    pending = [t for t in targets if t[0] not in verified_ids]
    for acc_id, market, prefix, name in pending[:1]:   # 한 번에 하나만
        # 클레임을 붙이면(_until_now 확장) gunicorn 60초를 넘겨 타임아웃(000)이 난다.
        #  ESM 키는 이미 백필로 실주문 조회가 검증됐으므로, orders_only(주문만·빠름)로
        #  '주문이 정상 반환되는가'만 확인한다. 창당 40초 자체 타임아웃(워커 보호).
        from concurrent.futures import ThreadPoolExecutor
        from concurrent.futures import TimeoutError as _TO
        def _fetch():
            cli = _oe._account_client(market, prefix)
            if cli is None:
                raise RuntimeError("API 키 미등록")
            end = _dt.datetime.now(_oe.KST)
            return _oe.esm_order_rows(market, end - _dt.timedelta(days=31), end,
                                      client=cli, include_settlement=False,
                                      orders_only=True)
        ex = ThreadPoolExecutor(max_workers=1)
        try:
            rows = ex.submit(_fetch).result(timeout=40)
        except _TO:
            ex.shutdown(wait=False)
            results.append({"account": name, "market": market, "saved": False,
                            "error": "40초 초과 — 5초/1회 제한. 잠시 후 재시도"})
            continue
        except Exception as e:  # noqa: BLE001
            ex.shutdown(wait=False)
            results.append({"account": name, "market": market, "saved": False,
                            "error": f"{type(e).__name__}: {e}"})
            continue
        finally:
            ex.shutdown(wait=False)
        # 조회가 **예외 없이 완료**되면(ResultCode 정상) 키가 유효한 것 → 통과.
        #  ESM 은 키가 틀리면 인증 에러를 던지지 어(위 except)에서 걸린다. 깨끗한 0건은
        #  '최근 매출이 없는 정상 계정'이다(키 작동은 백필로도 이미 증명됨). 0건을 실패로
        #  두면 저볼륨 계정 하나가 마켓 전체를 영구히 막는다(브랜드타임즈: 최근 0건).
        #  '주문이 있다'가 아니라 '이 계정 조회가 정상 작동한다'를 검증하는 것이다.
        s = SessionLocal()
        try:
            a = s.query(UploadAccount).get(acc_id)
            a.live_verified_at = _dt.datetime.now()
            a.live_verified_count = len(rows)
            s.commit()
        except Exception as e:  # noqa: BLE001
            s.rollback()
            results.append({"account": name, "market": market, "saved": False,
                            "error": f"DB: {type(e).__name__}: {e}"})
            continue
        finally:
            s.close()
        results.append({"account": name, "market": market, "saved": True,
                        "count": len(rows)})

    done = len(pending) <= 1     # 이번에 마지막 미검증 계정을 처리했으면 완료
    opened = sorted(_oe.supported_markets() & _oe.LIVE_VERIFIABLE)
    return jsonify({"ok": True, "results": results, "done": done,
                    "pending": max(0, len(pending) - 1), "opened_markets": opened,
                    "message": (f"공개된 마켓: {', '.join(opened)}" if opened else
                                "아직 공개 안 됨 — 각 마켓 활성 계정 전부가 통과해야 합니다.")})


@bp.route("/api/upload/accounts/<int:account_id>", methods=["DELETE"])
def delete_upload_account(account_id: int):
    """판매처 계정 삭제 — UploadAccount row 제거 (시크릿 키는 .env 에 그대로 둠 — 수동 정리).

    BundleSet 종속 cascade 로 자동 정리.
    """
    s = SessionLocal()
    try:
        acc = s.query(UploadAccount).get(account_id)
        if not acc:
            return jsonify({"ok": False, "error": "계정 없음"}), 404
        display_name = acc.display_name
        s.delete(acc)
        s.commit()
        return jsonify({
            "ok": True,
            "message": f"{display_name} 계정 삭제 완료. .env 시크릿 키는 별도로 정리하세요.",
        })
    except Exception as e:
        s.rollback()
        return jsonify({"ok": False, "error": f"DB 삭제 실패: {type(e).__name__}: {e}"}), 500
    finally:
        s.close()


@bp.route("/api/secrets/<env_prefix>/schema", methods=["GET"])
def secrets_schema(env_prefix: str):
    """마켓별 필요한 필드 스키마 반환 — 모달 폼이 동적으로 렌더링."""
    market = request.args.get("market", "").lower()
    if market not in MARKET_KEY_SUFFIXES:
        return jsonify({"ok": False, "error": "market 미지원"}), 400

    # 멀티 워커 일관성 — 다른 워커가 저장한 키도 반영해 '미등록' 오표시 방지.
    from lemouton.auth import secrets as _S
    _S.refresh_env()

    fields = []
    for sfx in MARKET_KEY_SUFFIXES[market]:
        label, is_sensitive = KEY_LABELS.get(sfx, (sfx, True))
        env_key = f"{env_prefix}_{sfx}"
        cur_val = os.environ.get(env_key, "")
        fields.append({
            "suffix": sfx,
            "env_key": env_key,
            "label": label,
            "sensitive": is_sensitive,
            "current_set": bool(cur_val),
            # 저장된 값 확인용 마스킹 (앞4***뒤4). 평문 노출 X.
            "masked": S.mask_secret(cur_val) if cur_val else None,
        })
    meta = MARKET_METADATA.get(market, {})
    return jsonify({
        "ok": True,
        "market": market,
        "env_prefix": env_prefix,
        "fields": fields,
        "label": meta.get("label", market),
        "icon": meta.get("icon", "🔧"),
        "api_type": meta.get("api_type", ""),
        "guide_url": meta.get("guide_url", ""),
        "guide_text": meta.get("guide_text", ""),
    })


# ──────────────────────────────────────────────────────────
#  /api/sourcing/credentials — 소싱처 회원 ID/PW (송장전송기 패턴)
# ──────────────────────────────────────────────────────────


# 소싱처 정의 — 송장전송기 SITE_ALIASES 동기화 (전체 13 사이트)
SOURCING_SITES = [
    {"key": "musinsa", "label": "무신사", "needs_login": True, "supports_naver": False,
     "login_url": "https://www.musinsa.com/auth/login"},
    {"key": "ssf", "label": "SSF샵", "needs_login": True, "supports_naver": False,
     "login_url": "https://www.ssfshop.com/public/member/login"},
    {"key": "ssg", "label": "SSG", "needs_login": True, "supports_naver": True,
     "login_url": "https://www.ssg.com/account/login.ssg"},
    {"key": "abc", "label": "ABC마트", "needs_login": True, "supports_naver": True,
     "login_url": "https://abcmart.a-rt.com/login"},
    {"key": "abcGs", "label": "ABC마트 GS", "needs_login": True, "supports_naver": True,
     "login_url": "https://abcmart.a-rt.com/login"},
    {"key": "grandstage", "label": "그랜드스테이지", "needs_login": True, "supports_naver": True,
     "login_url": "https://www.grandstage.co.kr/member/login"},
    {"key": "gs", "label": "GS샵", "needs_login": True, "supports_naver": True,
     "login_url": "https://with.gsshop.com/login/loginMain.gs"},
    {"key": "folder", "label": "폴더스타일", "needs_login": True, "supports_naver": True,
     "login_url": "https://www.folderstyle.com/login"},
    {"key": "lotteimall", "label": "롯데홈쇼핑", "needs_login": True, "supports_naver": False,
     "login_url": "https://www.lottehomeshopping.com/main/login.lotte"},
    {"key": "lotteon", "label": "롯데온", "needs_login": True, "supports_naver": True,
     "login_url": "https://www.lotteon.com/member/login"},
    {"key": "nike", "label": "나이키", "needs_login": True, "supports_naver": False,
     "login_url": "https://www.nike.com/kr/login"},
    {"key": "oliveyoung", "label": "올리브영", "needs_login": True, "supports_naver": False,
     "login_url": "https://www.oliveyoung.co.kr/store/member/login.do"},
    {"key": "gmarket", "label": "G마켓", "needs_login": True, "supports_naver": False,
     "login_url": "https://www.gmarket.co.kr/n/member/login"},
    {"key": "fashionplus", "label": "패션플러스", "needs_login": True, "supports_naver": False,
     "login_url": "https://www.fashionplus.co.kr/member/login"},
    {"key": "lemouton", "label": "르무통 회원", "needs_login": False, "supports_naver": False,
     "login_url": "https://lemouton.co.kr/member/login.html"},
]


@bp.route("/api/sourcing/sites", methods=["GET"])
def sourcing_sites():
    """소싱처 정의 + 자격증명 + 쿠키 상태 + 대표 크롤 계정 플래그."""
    from lemouton.auth.sourcing_credentials import default_store
    from lemouton.auth.profile_store import default_store as profile_default_store
    from lemouton.auth.cookie_checker import quick_check

    store = default_store()
    profile_store = profile_default_store()
    # mkdir 부작용 회피 — 경로만 계산
    from lemouton.auth.profile_store import _safe_key

    # ── DB SourcingAccount → (source, account_key) → is_default_for_crawl / is_active 매핑
    db = SessionLocal()
    try:
        db_accounts = db.query(SourcingAccount).all()
        default_crawl_map = {(a.source, a.account_key): a.is_default_for_crawl for a in db_accounts}
        active_map = {(a.source, a.account_key): a.is_active for a in db_accounts}
    finally:
        db.close()

    # [2026-06-06] 로그인 상태는 크롤과 동일 프로필(invoice_profiles, login_method 반영) 기준으로
    #   검사해야 정확함. (기존 data/profiles 경로 검사는 크롤이 쓰는 경로와 달라 오표시)
    from lemouton.auth.profile_store import resolve_profile_dir
    _all_creds = store.load_all()
    summary_by_key: dict[str, list[dict]] = {}
    for row in store.list_summary():
        _key = (row["source"], row["account_key"])
        # 비활성 계정은 목록에서 제외 (활성 계정만 노출)
        if _key in active_map and not active_map[_key]:
            continue
        # 쿠키 상태 검증 — 크롤과 동일 프로필(invoice_profiles) 기준 (생성 X, 검사만)
        all_creds = _all_creds.get(row["source"], {}).get(row["account_key"], {})
        actual_id = all_creds.get("id", row["account_key"])
        login_method = all_creds.get("login_method", "direct")
        prof_path = resolve_profile_dir(row["source"], actual_id, login_method)
        cookie_state = quick_check(prof_path, row["source"]) if prof_path.exists() else {
            "exists": False, "size_kb": 0, "has_key_cookies": False, "matched_keys": []
        }
        row["cookie_status"] = (
            "logged_in" if cookie_state["has_key_cookies"]
            else "in_progress" if cookie_state["exists"]
            else "never"
        )
        row["cookie_size_kb"] = cookie_state.get("size_kb", 0)
        # ★ 대표 크롤 계정 플래그
        row["is_default_for_crawl"] = bool(default_crawl_map.get((row["source"], row["account_key"]), False))
        summary_by_key.setdefault(row["source"], []).append(row)

    out = []
    for site in SOURCING_SITES:
        accounts = summary_by_key.get(site["key"], [])
        out.append({
            **site,
            "accounts": accounts,
            "count": len(accounts),
            "logged_in_count": sum(1 for a in accounts if a.get("cookie_status") == "logged_in"),
            "default_crawl_account": next(
                (a["account_key"] for a in accounts if a.get("is_default_for_crawl")), None
            ),
        })
    return jsonify({"ok": True, "sites": out})


@bp.route("/api/sourcing/accounts/<source>/<account_key>/set-default-crawl", methods=["POST"])
def set_default_crawl_account(source: str, account_key: str):
    """소싱처별 대표 크롤 계정 지정 (그 소싱처의 다른 계정들은 자동 unset)."""
    s = SessionLocal()
    try:
        # 같은 소싱처의 모든 계정 unset
        s.query(SourcingAccount).filter_by(source=source).update({"is_default_for_crawl": False})

        # 대상 계정 upsert
        acc = (s.query(SourcingAccount)
               .filter_by(source=source, account_key=account_key)
               .first())
        if acc is None:
            acc = SourcingAccount(
                source=source,
                account_key=account_key,
                display_name=f"{source} / {account_key}",
                is_active=True,
                is_default_for_crawl=True,
            )
            s.add(acc)
        else:
            acc.is_default_for_crawl = True

        s.commit()
        return jsonify({"ok": True, "source": source, "account_key": account_key,
                        "is_default_for_crawl": True})
    except Exception as e:
        s.rollback()
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        s.close()


@bp.route("/api/sourcing/accounts/<source>/clear-default-crawl", methods=["POST"])
def clear_default_crawl_account(source: str):
    """소싱처의 대표 크롤 계정 지정 해제 (모두 unset)."""
    s = SessionLocal()
    try:
        s.query(SourcingAccount).filter_by(source=source).update({"is_default_for_crawl": False})
        s.commit()
        return jsonify({"ok": True, "source": source, "cleared": True})
    finally:
        s.close()


@bp.route("/api/sourcing/credentials", methods=["POST"])
def save_sourcing_credentials():
    """소싱처 ID/PW 저장 — 송장전송기 settings.json 패턴.

    Body: ``{"source": "musinsa", "account_key": "default", "id": "...", "pw": "...", "login_method": "direct"|"manual"}``
    """
    from lemouton.auth.sourcing_credentials import default_store

    body = request.get_json(silent=True) or {}
    source = (body.get("source") or "").strip()
    account_key = (body.get("account_key") or "default").strip()
    id_value = (body.get("id") or "").strip()
    pw_value = body.get("pw") or ""  # PW 는 trim 안 함 (앞뒤 공백 의도일 수 있음)
    login_method = body.get("login_method", "direct")

    if source not in {s["key"] for s in SOURCING_SITES}:
        return jsonify({"ok": False, "error": f"지원하지 않는 source: {source}"}), 400
    # [2026-06-06] 네이버/카카오/구글 SNS 로그인도 허용 (어떤 계정이든 로그인).
    if login_method not in ("direct", "manual", "naver", "kakao", "google"):
        return jsonify({"ok": False, "error": "login_method 는 direct|manual|naver|kakao|google"}), 400

    try:
        result = default_store().upsert(
            source=source,
            account_key=account_key,
            id_value=id_value,
            pw_value=pw_value,
            login_method=login_method,
        )
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400

    # [2026-06-06] 송장자동화 패턴 — id/pw 저장 시 자동으로:
    #   (1) sourcing_account 등록 (대표 선택·크롤 대상이 되도록)
    #   (2) 백그라운드 자동 로그인 (direct) → 세션/프로필 생성. (로컬에서 헤디드 창)
    auto_login_started = False
    try:
        from lemouton.sourcing.models_v2 import SourcingAccount
        from shared.db import SessionLocal as _SL
        _s = _SL()
        try:
            _acc = (_s.query(SourcingAccount)
                    .filter_by(source=source, account_key=account_key).one_or_none())
            if _acc is None:
                _has_def = (_s.query(SourcingAccount)
                            .filter_by(source=source, is_default_for_crawl=True).first() is not None)
                _s.add(SourcingAccount(
                    source=source, account_key=account_key,
                    display_name=f"{source} / {account_key}",
                    is_active=True, is_default_for_crawl=not _has_def))
                _s.commit()
        finally:
            _s.close()
    except Exception:
        pass

    # direct·naver·kakao·google 모두 자동 로그인 시도 (manual 만 위저드). PW 있어야.
    if login_method != "manual" and pw_value:
        import threading

        def _bg_login(src=source, key=account_key, aid=id_value):
            try:
                from webapp.routes.api_pricing import _ensure_default_crawl_login
                # force=False → 이미 로그인돼 있으면 스킵, 아니면 로그인 (세션/프로필 생성)
                _ensure_default_crawl_login(src, key, aid, force=False)
            except Exception:
                pass

        threading.Thread(target=_bg_login, name=f"autologin-{source}-{account_key}",
                         daemon=True).start()
        auto_login_started = True

    return jsonify({
        "ok": True,
        "saved": result,
        "auto_login_started": auto_login_started,
        "message": f"{source}/{account_key} 저장 + 계정 등록 완료. "
                   + ("자동 로그인 시작됨(백그라운드)." if auto_login_started
                      else "수동 로그인 모드 — 위저드에서 직접 로그인."),
    })


@bp.route("/api/sourcing/credentials/<source>/<account_key>", methods=["DELETE"])
def delete_sourcing_credentials(source: str, account_key: str):
    from lemouton.auth.sourcing_credentials import default_store
    removed = default_store().remove(source, account_key)
    return jsonify({"ok": True, "removed": removed})


@bp.route("/wizard/start", methods=["POST"])
def wizard_start():
    """자동 로그인 위저드 시작.

    type=upload: 시뮬 모드 (마켓 셀러는 OAuth/HMAC 만 필요, 브라우저 로그인 X)
    type=sourcing: Phase 2-C 활성 — Playwright headed 부팅 + 자격증명 자동 입력 + storage_state 저장
    """
    body = request.get_json(silent=True) or {}
    target_type = body.get("type")
    target_key = body.get("account_key")

    if target_type not in ("upload", "sourcing"):
        return jsonify({"ok": False, "error": "type must be upload|sourcing"}), 400
    if not target_key:
        return jsonify({"ok": False, "error": "account_key required"}), 400

    if target_type == "upload":
        return jsonify({
            "ok": True,
            "wizard_id": f"wiz_upload_{target_key}",
            "status": "info",
            "message": "마켓 셀러는 브라우저 로그인 불필요 — '🔑 키 입력' 으로 시크릿만 등록하세요.",
        })

    # type == "sourcing" → Phase 2-C 실 동작
    # body 의 account_key 전달 (없으면 default)
    account_key = body.get("sourcing_account_key", "default")
    return _run_sourcing_wizard(target_key, account_key)


def _run_sourcing_wizard(source: str, account_key: str = "default"):
    """개별 행 ▶ 자동 로그인 — 새 스크래퍼 경로 (get_scraper) 사용.

    config.py 의존 제거 — 모든 사이트는 ``lemouton.auth.scrapers.SCRAPERS`` 로 일원화.
    한 번 성공하면 ``data/profiles/{source}_{account_id}/`` 에 쿠키 영구 저장.
    """
    from lemouton.auth.scrapers import get_scraper
    from lemouton.auth.sourcing_credentials import default_store as creds_default_store

    # 자격증명 조회
    creds_store = creds_default_store()
    cred = creds_store.get(source, account_key)
    if not cred or not cred.get("id") or not cred.get("pw"):
        return jsonify({
            "ok": False,
            "error": f"{source}/{account_key} 자격증명 없음 — ID/PW 먼저 저장하세요",
        }), 400

    scraper = get_scraper(source)
    if scraper is None:
        return jsonify({
            "ok": False,
            "error": f"{source} 스크래퍼 미지원 — lemouton.auth.scrapers.SCRAPERS 등록 필요",
        }), 400

    import time as _time
    started_at = _time.time()
    try:
        ok = scraper.ensure_logged_in(
            cred["id"], cred["pw"],
            login_method=cred.get("login_method", "direct"),
        )
    except Exception as e:
        logger.exception("[wizard] %s/%s 예외", source, account_key)
        return jsonify({
            "ok": False,
            "error": f"로그인 예외: {type(e).__name__}: {e}",
            "account_key": account_key,
            "elapsed_sec": _time.time() - started_at,
        }), 500

    return jsonify({
        "ok": bool(ok),
        "account_key": account_key,
        "message": f"{source}/{account_key} 로그인 성공 — 쿠키 영구 저장됨" if ok else f"{source}/{account_key} 로그인 실패",
        "elapsed_sec": _time.time() - started_at,
    })


# ──────────────────────────────────────────────────────────
#  /api/sourcing/auto_login_all — 일괄 자동 로그인 (송장전송기 패턴)
# ──────────────────────────────────────────────────────────

import threading
from collections import deque

# 전역 진행 상황 (송장전송기 _auto_login_state 패턴)
_auto_login_state = {
    "running": False,
    "total": 0,
    "done": 0,
    "success": 0,
    "fail": 0,
    "current": "",
    "results": [],
    "log_buffer": deque(maxlen=200),
}
_auto_login_lock = threading.Lock()


def _push_log(level: str, message: str):
    """로그 버퍼에 추가 — UI 가 폴링으로 가져감."""
    import time as _t
    _auto_login_state["log_buffer"].append({
        "ts": _t.time(), "level": level, "message": message
    })


def _run_auto_login_batch(targets: list[dict]):
    """별도 thread 에서 실행 — 사이트별 순차 로그인."""
    from lemouton.auth.scrapers import get_scraper

    with _auto_login_lock:
        _auto_login_state.update({
            "running": True, "total": len(targets), "done": 0,
            "success": 0, "fail": 0, "current": "",
            "results": [],
        })
        _auto_login_state["log_buffer"].clear()

    _push_log("info", f"━━━ 일괄 자동 로그인 시작 — {len(targets)} 계정 ━━━")

    for idx, t in enumerate(targets, 1):
        site = t["source"]
        account_id = t["id"]
        account_pw = t["pw"]
        account_key = t.get("account_key", "default")
        login_method = t.get("login_method", "direct")

        _auto_login_state["current"] = f"{site}/{account_key}"
        _push_log("info", f"[{idx}/{len(targets)}] {site}/{account_key} 시작 ({login_method})")

        scraper = get_scraper(site, log_callback=_push_log)
        if scraper is None:
            _push_log("warning", f"  → 스크래퍼 미지원: {site}")
            with _auto_login_lock:
                _auto_login_state["fail"] += 1
                _auto_login_state["done"] += 1
                _auto_login_state["results"].append({
                    "source": site, "account_key": account_key,
                    "ok": False, "error": "스크래퍼 미지원",
                })
            continue

        try:
            # ensure_logged_in 이 finally 에서 자동 close — 추가 cleanup 불필요
            ok = scraper.ensure_logged_in(account_id, account_pw, login_method=login_method)
            with _auto_login_lock:
                if ok:
                    _auto_login_state["success"] += 1
                else:
                    _auto_login_state["fail"] += 1
                _auto_login_state["done"] += 1
                _auto_login_state["results"].append({
                    "source": site, "account_key": account_key, "ok": ok,
                })
        except Exception as e:
            import traceback
            tb = traceback.format_exc()[-500:]
            _push_log("error", f"  → 예외: {type(e).__name__}: {e}")
            logger.exception("[wizard_batch] %s/%s 예외", site, account_key)
            with _auto_login_lock:
                _auto_login_state["fail"] += 1
                _auto_login_state["done"] += 1
                _auto_login_state["results"].append({
                    "source": site, "account_key": account_key,
                    "ok": False, "error": f"{type(e).__name__}: {e}",
                })
            # 안전 cleanup
            try:
                scraper.close()
            except Exception:
                pass

    _push_log("info", f"━━━ 완료 — 성공 {_auto_login_state['success']} / 실패 {_auto_login_state['fail']} ━━━")
    with _auto_login_lock:
        _auto_login_state["running"] = False
        _auto_login_state["current"] = ""


@bp.route("/api/sourcing/auto_login_all", methods=["POST"])
def auto_login_all():
    """등록된 모든 자격증명에 대해 일괄 자동 로그인 (별도 thread)."""
    from lemouton.auth.sourcing_credentials import default_store as creds_store

    if _auto_login_state["running"]:
        return jsonify({
            "ok": False,
            "error": "이미 진행 중 — /api/sourcing/auto_login_status 폴링하세요",
            "current": _auto_login_state.get("current", ""),
        }), 409

    body = request.get_json(silent=True) or {}
    only_sources = body.get("only_sources")  # 선택: 특정 사이트만
    selected_targets = body.get("targets")    # 선택: 특정 (source, account_key) 만

    # selected_targets 가 있으면 해당 (source, account_key) 쌍만 필터
    selected_pairs = None
    if selected_targets:
        selected_pairs = {
            (t.get("source"), t.get("account_key"))
            for t in selected_targets
            if t.get("source") and t.get("account_key")
        }

    all_creds = creds_store().load_all()
    targets = []
    for source, accounts in all_creds.items():
        if only_sources and source not in only_sources:
            continue
        for account_key, creds in accounts.items():
            if not creds.get("id") or not creds.get("pw"):
                continue
            if selected_pairs is not None and (source, account_key) not in selected_pairs:
                continue
            targets.append({
                "source": source,
                "account_key": account_key,
                "id": creds["id"],
                "pw": creds["pw"],
                "login_method": creds.get("login_method", "direct"),
            })

    if not targets:
        return jsonify({"ok": False, "error": "등록된 자격증명 없음"}), 400

    # 별도 thread 시작 (Flask request 블로킹 X)
    thread = threading.Thread(
        target=_run_auto_login_batch, args=(targets,), daemon=True,
    )
    thread.start()

    return jsonify({
        "ok": True,
        "started": True,
        "total": len(targets),
        "message": f"일괄 자동 로그인 시작 — {len(targets)} 계정. 진행 상황은 /auto_login_status 폴링.",
    })


@bp.route("/api/sourcing/auto_login_status", methods=["GET"])
def auto_login_status():
    """일괄 로그인 진행 상황 + 로그 버퍼 (UI 가 1초마다 폴링)."""
    with _auto_login_lock:
        state = {
            "running": _auto_login_state["running"],
            "total": _auto_login_state["total"],
            "done": _auto_login_state["done"],
            "success": _auto_login_state["success"],
            "fail": _auto_login_state["fail"],
            "current": _auto_login_state["current"],
            "results": list(_auto_login_state["results"]),
            "logs": list(_auto_login_state["log_buffer"]),
        }
    return jsonify({"ok": True, **state})


@bp.route("/api/sourcing/profiles", methods=["GET"])
def list_sourcing_profiles():
    """저장된 크롬 프로필 목록 — UI 표시용 (마지막 사용·쿠키 크기 등)."""
    from lemouton.auth.profile_store import default_store
    profiles = default_store().list_profiles()
    return jsonify({"ok": True, "profiles": profiles, "count": len(profiles)})


@bp.route("/api/sourcing/profiles/<source>/<account_key>", methods=["DELETE"])
def delete_sourcing_profile(source: str, account_key: str):
    """프로필 완전 삭제 — 쿠키 + 캐시 모두 제거 (다음 로그인 시 새로 시작)."""
    from lemouton.auth.profile_store import default_store
    removed = default_store().remove(source, account_key)
    return jsonify({"ok": True, "removed": removed,
                    "message": "프로필 삭제 완료 — 다음 자동 로그인은 신규 생성"})


def _source_to_korean(source: str) -> str:
    """크롤러 source 키 → config 의 한글 키."""
    return {"musinsa": "무신사", "ssf": "SSF샵", "lemouton": "르무통"}.get(source, source)


def _wizard_status_message(status) -> str:
    from lemouton.auth.login_wizard import WizardStatus
    return {
        WizardStatus.SUCCESS: "로그인 성공 — storage_state 저장 완료",
        WizardStatus.EXPIRED: "타임아웃 — 시간 내 로그인 미완료",
        WizardStatus.USER_ACTION_REQUIRED: "봇 탐지 / 캡차 — 사용자 직접 로그인 필요",
        WizardStatus.FAILED: "실패",
    }.get(status, str(status))


# ──────────────────────────────────────────────────────────
#  헬퍼
# ──────────────────────────────────────────────────────────


def _first_field_masked(creds) -> str:
    """첫 시크릿 필드를 마스킹해서 반환."""
    if not creds:
        return "—"
    field_names = list(type(creds).model_fields.keys())
    if not field_names:
        return "—"
    # __repr__ 가 이미 마스킹되어 있으므로 그걸 사용
    return repr(creds)


# ──────────────────────────────────────────────────────────────────
#  v6 P5.5 — 신규 소싱처 추가 (시안 A — 메타 등록 단순 폼)
#  사용자가 SSG·29CM·W컨셉 등 직접 추가 → DB SourcingSource 에 저장
# ──────────────────────────────────────────────────────────────────

@bp.route("/sourcing/add", methods=["GET", "POST"])
def source_add():
    """신규 소싱처 추가 — 시안 A (메타만, 어댑터는 추후)."""
    from lemouton.sourcing.models import SourcingSource
    s = SessionLocal()
    try:
        error = None
        form = {"label": "", "domain": "", "source_key": "",
                "logo_color": "#3182F6", "logo_letter": "", "needs_login": False,
                "favicon_url": "", "test_url": ""}
        # 기존 5개 + 사용자 추가분 — 좌측 목록용
        BUILTIN = [
            {"key": "lemouton", "label": "르무통 공홈", "color": "#191F28", "letter": "L"},
            {"key": "musinsa", "label": "무신사", "color": "#000000", "letter": "M"},
            {"key": "ssf", "label": "SSF", "color": "#FF6B00", "letter": "S"},
            {"key": "lotteon", "label": "롯데온", "color": "#ED2025", "letter": "L"},
            {"key": "ss_lemouton", "label": "스마트스토어 르무통", "color": "#03C75A", "letter": "N"},
        ]
        custom_sources = (s.query(SourcingSource)
                           .filter(SourcingSource.is_active.is_(True))
                           .order_by(SourcingSource.sort_order, SourcingSource.id)
                           .all())

        if request.method == "POST":
            form["label"] = (request.form.get("label") or "").strip()
            form["domain"] = (request.form.get("domain") or "").strip().lower().replace("https://", "").replace("http://", "").rstrip("/")
            form["source_key"] = (request.form.get("source_key") or "").strip().lower()
            form["logo_color"] = (request.form.get("logo_color") or "#3182F6").strip()
            form["logo_letter"] = (request.form.get("logo_letter") or "").strip().upper()[:4]
            form["needs_login"] = (request.form.get("needs_login") == "on")
            form["favicon_url"] = (request.form.get("favicon_url") or "").strip()

            # 검증
            if not form["label"] or not form["domain"] or not form["source_key"]:
                error = "표시 이름·도메인·시스템 키는 필수입니다."
            elif not all(c.isalnum() or c == "_" for c in form["source_key"]):
                error = "시스템 키는 영문/숫자/언더바만 사용 가능합니다."
            elif form["source_key"] in {b["key"] for b in BUILTIN}:
                error = f"'{form['source_key']}' 는 기본 소싱처와 중복됩니다."
            else:
                # 중복 확인
                exists = s.query(SourcingSource).filter_by(source_key=form["source_key"]).first()
                if exists:
                    error = f"'{form['source_key']}' 는 이미 등록되어 있습니다."

            if not error:
                # 저장
                src = SourcingSource(
                    source_key=form["source_key"],
                    label=form["label"],
                    domain=form["domain"],
                    logo_color=form["logo_color"],
                    logo_letter=(form["logo_letter"] or form["label"][:1].upper()),
                    favicon_url=form["favicon_url"] or None,
                    needs_login=form["needs_login"],
                    has_adapter=False,
                    is_active=True,
                    sort_order=100 + (s.query(SourcingSource).count()),
                )
                try:
                    from flask_login import current_user  # type: ignore
                    if hasattr(current_user, "email"):
                        src.created_by = current_user.email
                except Exception:
                    pass
                s.add(src); s.commit()
                from flask import flash, redirect, url_for
                try:
                    flash(f"✓ '{form['label']}' 소싱처 추가됨 (key: {form['source_key']})", "success")
                except Exception:
                    pass
                return redirect(url_for("accounts.source_add"))

        return render_template(
            "accounts/source_add.html",
            # [2026-07-17] active_app="accounts" 제거 — 소비처가 없는 死값이었고, 예전 부정조건
            # (active_app != 'inventory') 덕에 모음전이 켜졌다. 이제 전역 기본값 'bundles' 가 켠다.
            active="sourcing",
            form=form, error=error,
            builtin=BUILTIN, custom_sources=custom_sources,
        )
    finally:
        s.close()


@bp.post("/sourcing/source/<int:source_id>/toggle")
def source_toggle(source_id: int):
    """소싱처 활성 / 비활성 toggle (휴지통 대신)."""
    from lemouton.sourcing.models import SourcingSource
    s = SessionLocal()
    try:
        src = s.query(SourcingSource).get(source_id)
        if not src:
            return jsonify(ok=False, error="not found"), 404
        src.is_active = not src.is_active
        s.commit()
        return jsonify(ok=True, is_active=src.is_active)
    finally:
        s.close()


# ════════════════════════════════════════════════════════════
# [2026-05-24] MarketRegistry CRUD — 마켓 동적 N개 관리
# 가격설정 → 크롤 영역의 마켓 목록 (스마트스토어/쿠팡 + 사용자 추가)
# ════════════════════════════════════════════════════════════

from lemouton.sourcing.models import MarketRegistry


def _abbr_logo(label: str) -> str:
    """디폴트 logo_letter 생성 — 한글 앞 2자 / 영문 앞 2자 소문자."""
    s = (label or '').strip()
    if not s:
        return '?'
    if s[0].isalpha() and s[0].isascii():
        cleaned = ''.join(c for c in s if c.isalnum())
        return cleaned[:2].lower() or '?'
    return s[:2]


@bp.route('/markets', methods=['GET'])
def api_markets_list():
    s = SessionLocal()
    try:
        rows = s.query(MarketRegistry).order_by(MarketRegistry.sort_order, MarketRegistry.id).all()
        return jsonify(ok=True, markets=[{
            'id': r.id, 'market_key': r.market_key, 'label': r.label,
            'logo_color': r.logo_color, 'logo_letter': r.logo_letter,
            'sort_order': r.sort_order, 'is_active': r.is_active, 'is_builtin': r.is_builtin,
        } for r in rows])
    finally:
        s.close()


@bp.route('/markets', methods=['POST'])
def api_markets_add():
    body = request.get_json(silent=True) or {}
    market_key = (body.get('market_key') or '').strip().lower()
    label = (body.get('label') or '').strip()
    if not market_key or not label:
        return jsonify(ok=False, error='market_key 와 label 필수'), 400
    logo_color = (body.get('logo_color') or '#3B82F6').strip()
    logo_letter = (body.get('logo_letter') or '').strip() or _abbr_logo(label)
    s = SessionLocal()
    try:
        if s.query(MarketRegistry).filter_by(market_key=market_key).first():
            return jsonify(ok=False, error='이미 존재하는 market_key'), 400
        max_order = s.query(MarketRegistry.sort_order).order_by(
            MarketRegistry.sort_order.desc()).first()
        next_order = (max_order[0] + 1) if max_order else 100
        row = MarketRegistry(
            market_key=market_key, label=label,
            logo_color=logo_color, logo_letter=logo_letter[:8],
            sort_order=next_order, is_builtin=False,
        )
        s.add(row); s.commit()
        return jsonify(ok=True, id=row.id, market_key=row.market_key,
                       label=row.label, logo_color=row.logo_color,
                       logo_letter=row.logo_letter, sort_order=row.sort_order)
    finally:
        s.close()


@bp.route('/markets/<int:mid>', methods=['PUT'])
def api_markets_update(mid):
    body = request.get_json(silent=True) or {}
    s = SessionLocal()
    try:
        row = s.query(MarketRegistry).get(mid)
        if not row:
            return jsonify(ok=False, error='not found'), 404
        if 'label' in body:
            lbl = (body.get('label') or '').strip()
            if lbl: row.label = lbl
        if 'logo_color' in body:
            row.logo_color = (body.get('logo_color') or row.logo_color).strip()
        if 'logo_letter' in body:
            row.logo_letter = ((body.get('logo_letter') or '').strip()[:8] or row.logo_letter)
        if 'sort_order' in body:
            try: row.sort_order = int(body.get('sort_order'))
            except Exception: pass
        if 'is_active' in body:
            row.is_active = bool(body.get('is_active'))
        s.commit()
        return jsonify(ok=True, id=row.id, label=row.label,
                       logo_color=row.logo_color, logo_letter=row.logo_letter,
                       is_active=row.is_active)
    finally:
        s.close()


@bp.route('/markets/<int:mid>', methods=['DELETE'])
def api_markets_delete(mid):
    s = SessionLocal()
    try:
        row = s.query(MarketRegistry).get(mid)
        if not row:
            return jsonify(ok=False, error='not found'), 404
        if row.is_builtin:
            return jsonify(ok=False, error='기본 마켓은 삭제 불가 (비활성만 가능)'), 400
        s.delete(row); s.commit()
        return jsonify(ok=True)
    finally:
        s.close()


# ──────────────────────────────────────────────────────────
#  /accounts/crawl-login — 크롤 자동로그인 저장 (방식 A, 배치3 전용 탭)
#    판매자센터 아이디/비번을 암호화 저장 → 확장이 자동 로그인·정산 수집.
#    비번은 Fernet 암호화(crawl_login). 여기선 저장+상태만 — 실제 로그인 테스트는
#    확장(브라우저 세션)이 수행(다음 단계). 복호화 조회 엔드포인트도 확장 구현 시 추가.
# ──────────────────────────────────────────────────────────

# 크롤 자동로그인 지원 마켓 — 판매자센터 세션 토큰이 필요한 마켓만.
CRAWL_LOGIN_MARKETS = ("lotteon",)


@bp.route("/crawl-login")
def crawl_login_view():
    """크롤 로그인 전용 화면 — 마켓별 계정을 한 곳에 모아 로그인정보 저장·상태 확인."""
    import os as _os
    from lemouton.auth import crawl_login as _cl
    from lemouton.auth import secrets as _S
    _S.refresh_env()
    s = SessionLocal()
    try:
        accts = (s.query(UploadAccount)
                 .filter(UploadAccount.market.in_(CRAWL_LOGIN_MARKETS))
                 .order_by(UploadAccount.market, UploadAccount.display_name).all())
        rows = []
        for acc in accts:
            st = _cl.login_status(acc.env_prefix)
            rows.append({
                "id": acc.id,
                "display_name": acc.display_name,
                "market": acc.market,
                "env_prefix": acc.env_prefix,
                "saved": st["saved"],
                "login_id": st["login_id"] or "",
                # 마켓 API용 거래처번호(=판매자ID LO~) — 계정 정체성 확인·검증용으로 표시.
                "tr_no": _os.environ.get(f"{acc.env_prefix}_TR_NO") or "",
            })
        n_saved = sum(1 for r in rows if r["saved"])
        # [2026-07-17] active_app="" 제거 — 위 source_add 와 동일 사유(전역 기본값 'bundles' 가 모음전을 켠다).
        return render_template("accounts/crawl_login.html",
                               accounts=rows, total=len(rows), n_saved=n_saved,
                               n_unsaved=len(rows) - n_saved)
    finally:
        s.close()


@bp.route("/api/crawl-login/accounts", methods=["GET"])
def crawl_login_accounts():
    """[2026-07-17] 크롤 로그인 계정 목록(JSON) — 확장이 화면(HTML) 없이 계정을 훑기 위해.

    정산 「자동 반복」이 확장으로 옮겨가면서, 탭이 닫혀 있어도 확장이 '어떤 계정을 돌아야
    하는지' 알아야 한다. 예전엔 페이지가 렌더된 카드(.cl-card)를 읽어 계정을 알았다 →
    탭이 없으면 계정도 모름. 그래서 같은 질의를 JSON 으로 낸다(위 crawl_login_view 와
    동일 원천 — 목록이 두 곳에서 갈리지 않게).
    ★비밀번호는 절대 안 싣는다. 자격증명은 계정별 /creds 가 따로 낸다(기존 경로 유지).
    """
    import os as _os
    from lemouton.auth import crawl_login as _cl
    from lemouton.auth import secrets as _S
    _S.refresh_env()
    s = SessionLocal()
    try:
        accts = (s.query(UploadAccount)
                 .filter(UploadAccount.market.in_(CRAWL_LOGIN_MARKETS))
                 .order_by(UploadAccount.market, UploadAccount.display_name).all())
        rows = []
        for acc in accts:
            st = _cl.login_status(acc.env_prefix)
            rows.append({
                "display_name": acc.display_name,
                "market": acc.market,
                "env_prefix": acc.env_prefix,
                "saved": st["saved"],
                "tr_no": _os.environ.get(f"{acc.env_prefix}_TR_NO") or "",
            })
    finally:
        s.close()
    return jsonify({"ok": True, "accounts": rows,
                    "n_saved": sum(1 for r in rows if r["saved"])})


@bp.route("/api/crawl-login/<env_prefix>", methods=["POST"])
def save_crawl_login(env_prefix: str):
    """판매자센터 아이디/비번 저장(비번 암호화). Body: {login_id, password}.

    password 빈 칸 + 기존 저장값 있으면 아이디만 갱신(비번 유지) — 재입력 없이 이름만 수정 가능.
    """
    from lemouton.auth import crawl_login as _cl
    from lemouton.auth.env_writer import EnvWriteError

    if not env_prefix or not env_prefix.replace("_", "").isalnum():
        return jsonify({"ok": False, "error": "env_prefix 형식 오류"}), 400

    body = request.get_json(silent=True) or {}
    login_id = (body.get("login_id") or "").strip()
    password = body.get("password") or ""   # 공백 유의미할 수 있어 strip 안 함
    tr_no = (body.get("tr_no") or "").strip()   # 판매자ID(LO~) = 마켓 API 거래처번호

    if not login_id:
        return jsonify({"ok": False, "error": "아이디를 입력하세요"}), 400
    if tr_no and not tr_no.upper().startswith("LO"):
        return jsonify({"ok": False, "error": "판매자ID는 LO로 시작해야 합니다"}), 400

    # 이 env_prefix 가 크롤 로그인 대상 계정인지 확인(임의 키 주입 방지)
    s = SessionLocal()
    try:
        acc = (s.query(UploadAccount)
               .filter(UploadAccount.env_prefix == env_prefix,
                       UploadAccount.market.in_(CRAWL_LOGIN_MARKETS)).first())
    finally:
        s.close()
    if acc is None:
        return jsonify({"ok": False, "error": "크롤 로그인 대상 계정이 아닙니다"}), 404

    prev = _cl.login_status(env_prefix)
    if not password:
        if not prev["saved"]:
            return jsonify({"ok": False, "error": "비밀번호를 입력하세요(기존 저장값 없음)"}), 400
        # 비번 유지 + 아이디만 갱신
        try:
            from lemouton.auth import secrets as _S
            from lemouton.auth.env_writer import update_env_keys
            update_env_keys(_S.secrets_env_path(),
                            {f"{env_prefix}_CRAWL_LOGIN_ID": login_id}, require_non_empty=True)
            _S.refresh_env()
        except EnvWriteError as e:
            return jsonify({"ok": False, "error": str(e)}), 500
    else:
        try:
            _cl.save_login(env_prefix, login_id, password)
        except EnvWriteError as e:
            return jsonify({"ok": False, "error": str(e)}), 500

    # 판매자ID(LO~) 저장 — 마켓 API·수집 검증 공용 {env_prefix}_TR_NO
    if tr_no:
        try:
            from lemouton.auth import secrets as _S2
            from lemouton.auth.env_writer import update_env_keys as _upd
            _upd(_S2.secrets_env_path(), {f"{env_prefix}_TR_NO": tr_no}, require_non_empty=True)
            _S2.refresh_env()
        except EnvWriteError as e:
            return jsonify({"ok": False, "error": str(e)}), 500

    st = _cl.login_status(env_prefix)
    return jsonify({"ok": True, "saved": st["saved"], "login_id": st["login_id"],
                    "message": f"{acc.display_name} 로그인 정보 저장 완료(비밀번호 암호화)."})


@bp.route("/api/crawl-login/<env_prefix>/creds", methods=["POST"])
def crawl_login_creds(env_prefix: str):
    """[방식A 자동로그인] 저장된 판매자센터 자격증명(복호화)을 반환 — 확장이 로그인폼 자동입력용.

    ⚠️ 평문 비밀번호를 이 사용자의 인증된 브라우저에 전달한다(방식A 고지된 트레이드오프,
    crawl_login.py 보안설계 참조). 임의 키 주입 방지 위해 크롤 로그인 대상 계정만 허용.
    """
    from lemouton.auth import crawl_login as _cl
    if not env_prefix or not env_prefix.replace("_", "").isalnum():
        return jsonify({"ok": False, "error": "env_prefix 형식 오류"}), 400
    s = SessionLocal()
    try:
        acc = (s.query(UploadAccount)
               .filter(UploadAccount.env_prefix == env_prefix,
                       UploadAccount.market.in_(CRAWL_LOGIN_MARKETS)).first())
    finally:
        s.close()
    if acc is None:
        return jsonify({"ok": False, "error": "크롤 로그인 대상 계정이 아닙니다"}), 404
    st = _cl.login_status(env_prefix)
    if not st["saved"]:
        return jsonify({"ok": False, "error": "저장된 로그인 정보가 없습니다"}), 404
    pw = _cl.get_password(env_prefix)
    if pw is None:
        return jsonify({"ok": False, "error": "비밀번호 복호화 실패(키 불일치/손상)"}), 500
    return jsonify({"ok": True, "login_id": st["login_id"], "password": pw,
                    "display_name": acc.display_name})

