"""팀공유 인증 시스템 — Flask-Login 통합.

활성화 조건: ENVIRONMENT=team-share-dev (또는 그 외 비-기본값)
비활성 시 (기존 시스템): 이 모듈은 import 되지 않음 (app.py 가 조건부 import).
"""
from __future__ import annotations

import os
from typing import Optional

from flask import Flask, jsonify, redirect, request, url_for

# 화이트리스트 — 인증 없이 접근 가능
_PUBLIC_ENDPOINTS = {
    None,                # 매칭 안 된 라우트 (404 는 그냥 통과)
    "static",            # 정적 자원
    "health",            # 헬스체크
    "auth.login",        # 로그인 페이지 자체
    "auth.forgot_password",   # 비번찾기 (로그인 못 한 사용자)
    "auth.reset_sent",        # 비번찾기 안내
    "auth.reset_password",    # 토큰 기반 새 비번 설정
    "mockup",            # 디자인 시안 (개발 편의)
}

_PUBLIC_PATH_PREFIXES = (
    "/static/",
    "/health",
    "/webhook/",         # 외부 시스템 콜백 (서명 검증 별도)
)


def init_auth(app: Flask) -> None:
    """Flask 앱에 인증 시스템 통합.

    호출 시점: create_app() 의 라우트 등록 후, 단 init_db() 이후.
    """
    from flask_login import LoginManager
    from webapp.auth.models import User
    from webapp.auth.views import bp as auth_bp
    from shared.db import SessionLocal

    # 1. Blueprint 등록
    app.register_blueprint(auth_bp)

    # 2. LoginManager
    lm = LoginManager()
    lm.init_app(app)
    lm.login_view = "auth.login"
    lm.login_message = "로그인이 필요합니다."
    lm.session_protection = "strong"

    @lm.user_loader
    def _load_user(user_id: str) -> Optional[User]:
        try:
            with SessionLocal() as s:
                return s.get(User, int(user_id))
        except (ValueError, TypeError):
            return None

    @lm.unauthorized_handler
    def _unauthorized():
        if request.path.startswith("/api/"):
            return jsonify(error="unauthorized", message="로그인 필요"), 401
        return redirect(url_for("auth.login", next=request.url))

    # 3. before_request — 전체 라우트 보호 (화이트리스트 외)
    @app.before_request
    def _enforce_auth():
        # OPTIONS preflight 통과
        if request.method == "OPTIONS":
            return

        # 화이트리스트 endpoint
        if request.endpoint in _PUBLIC_ENDPOINTS:
            return

        # 화이트리스트 경로 prefix
        path = request.path
        for prefix in _PUBLIC_PATH_PREFIXES:
            if path.startswith(prefix):
                return

        # 인증 필요
        from flask_login import current_user
        if not current_user.is_authenticated:
            if path.startswith("/api/"):
                return jsonify(error="unauthorized", message="로그인 필요"), 401
            return redirect(url_for("auth.login", next=request.url))

    app.logger.info("[team-share] 인증 시스템 활성화됨 (Flask-Login)")
