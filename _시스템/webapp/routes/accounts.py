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

from flask import Blueprint, jsonify, render_template, request

logger = logging.getLogger(__name__)

from lemouton.auth import secrets as S
from lemouton.sourcing.models_v2 import SourcingAccount, UploadAccount
from shared.db import SessionLocal

bp = Blueprint("accounts", __name__, url_prefix="/accounts")


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
        # ── 1) 매핑 매트릭스 — V1 Model 의 url_* 컬럼 집계
        models = s.query(Model).order_by(Model.model_code).all()
        mapping_matrix = []
        for src in SOURCES:
            attr = URL_ATTR[src["key"]]
            cells = []
            mapped_count = 0
            for m in models:
                url = getattr(m, attr, None)
                if url:
                    mapped_count += 1
                    cells.append({
                        "model_code": m.model_code,
                        "url": url,
                        "mapped": True,
                    })
                else:
                    cells.append({
                        "model_code": m.model_code,
                        "url": None,
                        "mapped": False,
                    })
            mapping_matrix.append({
                "key": src["key"],
                "label": src["label"],
                "needs_login": src["needs_login"],
                "mapped_count": mapped_count,
                "total": len(models),
                "cells": cells,
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
}

# UI 노출용 라벨 — sensitive 여부도 표시
KEY_LABELS = {
    "CLIENT_ID": ("Client ID", False),
    "CLIENT_SECRET": ("Client Secret", True),
    "ACCESS_KEY": ("Access Key", False),
    "SECRET_KEY": ("Secret Key", True),
    "VENDOR_ID": ("Vendor ID (셀러 코드)", False),
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
        "api_type": "셀러센터 API",
        "guide_url": "https://seller.lotteon.com/",
        "guide_text": "롯데온 셀러센터 API",
        "default_prefix": "LOTTEON_MAIN",
        "status": "coming_soon",
        "sort_order": 3,
    },
    "eleven11": {
        "label": "11번가",
        "icon": "🟣",
        "api_type": "OAuth (SK 쇼핑)",
        "guide_url": "https://api.11st.co.kr/",
        "guide_text": "11번가 셀러 API — 클라이언트 등록 후 Key/Secret 발급",
        "default_prefix": "ELEVEN11_MAIN",
        "status": "coming_soon",
        "sort_order": 4,
    },
    "auction": {
        "label": "옥션",
        "icon": "🟡",
        "api_type": "ESM 2.0 (이베이코리아)",
        "guide_url": "https://www.esmplus.com/",
        "guide_text": "ESM 2.0 통합 셀러 API (옥션·G마켓 통합)",
        "default_prefix": "AUCTION_MAIN",
        "status": "coming_soon",
        "sort_order": 5,
    },
    "gmarket": {
        "label": "G마켓",
        "icon": "🟡",
        "api_type": "ESM 2.0 (이베이코리아)",
        "guide_url": "https://www.esmplus.com/",
        "guide_text": "ESM 2.0 통합 셀러 API (옥션·G마켓 통합)",
        "default_prefix": "GMARKET_MAIN",
        "status": "coming_soon",
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

    # 입력 검증
    expected_suffixes = MARKET_KEY_SUFFIXES[market]
    missing = [sfx for sfx in expected_suffixes
               if not values.get(sfx) or not values.get(sfx, "").strip()]
    if missing:
        return jsonify({
            "ok": False,
            "error": f"필수 필드 누락: {missing}",
        }), 400

    # env 키 매핑: SMARTSTORE_MAIN_CLIENT_ID 등
    env_keys = {
        f"{env_prefix}_{sfx}": values[sfx].strip()
        for sfx in expected_suffixes
    }

    project_root = Path(__file__).resolve().parents[2]
    env_path = project_root / ".env"

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
        # 중복 검사
        existing = s.query(UploadAccount).filter_by(account_key=account_key).first()
        if existing:
            return jsonify({
                "ok": False,
                "error": f"account_key '{account_key}' 이미 존재 — 다른 이름 사용",
            }), 409

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
    else:
        return jsonify({"ok": False, "error": f"{market} 테스트 미구현"}), 400


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


def _test_smartstore(creds, display_name: str, env_prefix: str):
    """스마트스토어 OAuth 토큰 발급 시도 — Bcrypt 서명."""
    import time as _time
    import bcrypt
    import base64
    import requests

    started = _time.time()
    timestamp = str(int(_time.time() * 1000))
    password = f"{creds.client_id}_{timestamp}".encode("utf-8")
    hashed = bcrypt.hashpw(password, creds.client_secret.encode("utf-8"))
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
    if r.status_code == 200:
        data = r.json()
        token = data.get("access_token", "")
        return jsonify({
            "ok": True,
            "message": f"✅ {display_name} 스마트스토어 OAuth 토큰 발급 성공 ({elapsed}s)",
            "status_code": r.status_code,
            "elapsed_sec": elapsed,
            "token_masked": (token[:8] + "***") if token else "<empty>",
            "expires_in": data.get("expires_in"),
        })
    body_snippet = (r.text or "")[:300]
    return jsonify({
        "ok": False,
        "error": f"스마트스토어 OAuth 실패 — HTTP {r.status_code}",
        "status_code": r.status_code,
        "elapsed_sec": elapsed,
        "body_snippet": body_snippet,
    }), 502


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

    fields = []
    for sfx in MARKET_KEY_SUFFIXES[market]:
        label, is_sensitive = KEY_LABELS.get(sfx, (sfx, True))
        fields.append({
            "suffix": sfx,
            "env_key": f"{env_prefix}_{sfx}",
            "label": label,
            "sensitive": is_sensitive,
            "current_set": bool(os.environ.get(f"{env_prefix}_{sfx}")),
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

    # ── DB SourcingAccount → (source, account_key) → is_default_for_crawl 매핑
    db = SessionLocal()
    try:
        db_accounts = db.query(SourcingAccount).all()
        default_crawl_map = {(a.source, a.account_key): a.is_default_for_crawl for a in db_accounts}
    finally:
        db.close()

    summary_by_key: dict[str, list[dict]] = {}
    for row in store.list_summary():
        # 쿠키 상태 검증 — 실 ID 기반 프로필 디렉터리 매칭 (생성 X, 검사만)
        all_creds = store.load_all().get(row["source"], {}).get(row["account_key"], {})
        actual_id = all_creds.get("id", row["account_key"])
        prof_path = profile_store.profiles_root / f"{_safe_key(row['source'])}_{_safe_key(actual_id)}"
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
    if login_method not in ("direct", "manual"):
        return jsonify({"ok": False, "error": "login_method 는 direct|manual"}), 400

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

    return jsonify({
        "ok": True,
        "saved": result,
        "message": f"{source}/{account_key} 자격증명 저장 완료. "
                   + ("자동 로그인 가능." if login_method == "direct" else "수동 로그인 모드 — 위저드 시작 시 사용자 직접 로그인."),
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
