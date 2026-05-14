"""권한 데코레이터 — 팀공유 모드 전용.

기존 시스템 (no Flask-Login) 에서 import 되어도 안전하도록 lazy.
"""
from __future__ import annotations

import functools
import os
from typing import Callable, TypeVar

from flask import jsonify, redirect, request, url_for

F = TypeVar("F", bound=Callable)


def is_team_share_mode() -> bool:
    return os.environ.get("ENVIRONMENT") == "team-share-dev"


def admin_required(f: F) -> F:
    """admin 역할 사용자만 접근 가능. member 는 403.

    팀공유 모드 아닐 때 (기존 시스템) 는 통과 — 단일 사용자 가정.
    """
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if not is_team_share_mode():
            return f(*args, **kwargs)

        from flask_login import current_user
        if not current_user.is_authenticated:
            if request.path.startswith("/api/"):
                return jsonify(error="unauthorized", message="로그인 필요"), 401
            return redirect(url_for("auth.login", next=request.url))

        if not getattr(current_user, "is_admin", False):
            if request.path.startswith("/api/"):
                return jsonify(error="forbidden", message="admin 권한 필요"), 403
            from flask import render_template
            return render_template("auth/403.html"), 403

        return f(*args, **kwargs)
    return wrapper  # type: ignore[return-value]


def enforce_admin():
    """Blueprint-level admin 게이트.

    사용법:
        bp = Blueprint("accounts", __name__)

        @bp.before_request
        def _admin_only():
            from webapp.auth.permissions import enforce_admin
            return enforce_admin()

    Returns:
        None: 허가 (정상 진행)
        Response: 차단 (redirect/JSON 401·403)

    팀공유 모드 아닐 때 (기존) 는 항상 None (통과).
    """
    if not is_team_share_mode():
        return None

    from flask_login import current_user
    if not current_user.is_authenticated:
        if request.path.startswith("/api/"):
            return jsonify(error="unauthorized", message="로그인 필요"), 401
        return redirect(url_for("auth.login", next=request.url))

    if not getattr(current_user, "is_admin", False):
        if request.path.startswith("/api/"):
            return jsonify(error="forbidden", message="admin 권한 필요"), 403
        from flask import render_template
        return render_template("auth/403.html"), 403

    return None


def login_required_smart(f: F) -> F:
    """로그인 필요. 팀공유 모드 아닐 때는 통과.

    Flask-Login 의 login_required 는 단순 wrapper 라 동일하지만,
    이건 ENVIRONMENT 체크가 들어가서 기존 시스템에서 import 만 해도 안전.
    """
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if not is_team_share_mode():
            return f(*args, **kwargs)

        from flask_login import current_user
        if not current_user.is_authenticated:
            if request.path.startswith("/api/"):
                return jsonify(error="unauthorized"), 401
            return redirect(url_for("auth.login", next=request.url))

        return f(*args, **kwargs)
    return wrapper  # type: ignore[return-value]
