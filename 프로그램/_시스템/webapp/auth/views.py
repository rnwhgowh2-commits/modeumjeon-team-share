"""인증 라우트 (Blueprint) — /login, /logout, /me, /change-password, /forgot-password, /reset-password, admin: /users."""
from __future__ import annotations

import datetime as dt
import logging

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from shared.db import SessionLocal
from webapp.auth.forms import (
    ChangePasswordForm,
    ForgotPasswordForm,
    InviteUserForm,
    LoginForm,
    ResetPasswordForm,
)
from webapp.auth.models import LoginSession, PasswordResetToken, User
from webapp.auth.permissions import admin_required

bp = Blueprint("auth", __name__, url_prefix="/auth")
_log = logging.getLogger(__name__)


# ─── 로그인 ───
@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("auth.me"))

    form = LoginForm()
    if form.validate_on_submit():
        with SessionLocal() as s:
            user = s.query(User).filter_by(email=form.email.data.strip().lower()).first()
            if user and user.is_active and user.check_password(form.password.data):
                login_user(user, remember=form.remember.data)
                user.last_login_at = dt.datetime.utcnow()
                s.add(LoginSession(
                    user_id=user.id,
                    ip_address=request.remote_addr,
                    user_agent=(request.user_agent.string or "")[:500],
                ))
                s.commit()
                nxt = request.args.get("next") or url_for("auth.me")
                return redirect(nxt)
            flash("이메일 또는 비밀번호가 올바르지 않습니다.", "error")

    return render_template("auth/login.html", form=form)


# ─── 로그아웃 ───
@bp.route("/logout", methods=["GET", "POST"])
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))


# ─── 내 프로필 ───
@bp.route("/me")
@login_required
def me():
    return render_template("auth/me.html", user=current_user)


# ─── 비밀번호 변경 ───
@bp.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    form = ChangePasswordForm()
    if form.validate_on_submit():
        with SessionLocal() as s:
            user = s.get(User, current_user.id)
            if not user or not user.check_password(form.current_password.data):
                flash("현재 비밀번호가 올바르지 않습니다.", "error")
            else:
                user.set_password(form.new_password.data)
                s.commit()
                flash("비밀번호가 변경되었습니다.", "success")
                return redirect(url_for("auth.me"))
    return render_template("auth/change_password.html", form=form)


# ─── 비밀번호 찾기 (이메일 reset 링크) ───
@bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for("auth.me"))

    form = ForgotPasswordForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()

        with SessionLocal() as s:
            user = s.query(User).filter_by(email=email, is_active=True).first()
            if user:
                # 기존 미사용 토큰 무효화 (혹시 모를 재발급 충돌 방지)
                s.query(PasswordResetToken).filter_by(user_id=user.id, used_at=None).update(
                    {"used_at": dt.datetime.utcnow()}
                )
                tok = PasswordResetToken.new_for_user(user.id)
                s.add(tok)
                s.commit()

                # 메일 발송 (실패해도 사용자 응답은 동일 — enumeration 방지)
                try:
                    from webapp.auth.mailer import send_password_reset_email
                    send_password_reset_email(user.email, user.name, tok.token)
                    _log.info(f"[auth] reset 메일 발송 OK: user_id={user.id}")
                except Exception as e:
                    _log.error(f"[auth] reset 메일 발송 실패: {e!r}", exc_info=True)
            else:
                _log.info(f"[auth] forgot-password 요청 (미가입): {email}")

        return redirect(url_for("auth.reset_sent"))

    return render_template("auth/forgot_password.html", form=form)


@bp.route("/reset-sent")
def reset_sent():
    """forgot-password 후 안내 페이지 — 가입 여부 노출 안 함."""
    return render_template("auth/reset_sent.html")


@bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token: str):
    if current_user.is_authenticated:
        return redirect(url_for("auth.me"))

    with SessionLocal() as s:
        tok = s.query(PasswordResetToken).filter_by(token=token).first()
        if not tok or not tok.is_valid:
            return render_template("auth/reset_password.html", form=None, token_error=True)

        form = ResetPasswordForm()
        if form.validate_on_submit():
            user = s.get(User, tok.user_id)
            if not user or not user.is_active:
                return render_template("auth/reset_password.html", form=None, token_error=True)

            user.set_password(form.new_password.data)
            tok.mark_used()
            s.commit()

            flash("비밀번호가 재설정되었습니다. 새 비밀번호로 로그인해 주세요.", "success")
            return redirect(url_for("auth.login"))

        return render_template("auth/reset_password.html", form=form, token_error=False)


# ─── admin: 팀원 관리 ───
@bp.route("/users")
@admin_required
def users_list():
    with SessionLocal() as s:
        users = s.query(User).order_by(User.created_at.desc()).all()
    return render_template("auth/users.html", users=users)


@bp.route("/users/invite", methods=["GET", "POST"])
@admin_required
def invite_user():
    form = InviteUserForm()
    if form.validate_on_submit():
        with SessionLocal() as s:
            email = form.email.data.strip().lower()
            if s.query(User).filter_by(email=email).first():
                flash("이미 가입된 이메일입니다.", "error")
            elif form.role.data not in ("admin", "member"):
                flash("역할은 admin 또는 member 만 가능합니다.", "error")
            else:
                u = User(
                    email=email,
                    name=form.name.data.strip(),
                    role=form.role.data,
                    is_active=True,
                )
                u.set_password(form.temp_password.data)
                s.add(u)
                s.commit()
                flash(f"{u.email} 초대 완료. 임시 비번 전달 후 변경 요청하세요.", "success")
                return redirect(url_for("auth.users_list"))
    return render_template("auth/invite.html", form=form)


@bp.route("/users/<int:user_id>/toggle-active", methods=["POST"])
@admin_required
def toggle_active(user_id: int):
    with SessionLocal() as s:
        u = s.get(User, user_id)
        if not u:
            flash("사용자 없음", "error")
        elif u.id == current_user.id:
            flash("본인은 비활성화할 수 없습니다.", "error")
        else:
            u.is_active = not u.is_active
            s.commit()
            flash(f"{u.email} → {'활성' if u.is_active else '비활성'}", "success")
    return redirect(url_for("auth.users_list"))
