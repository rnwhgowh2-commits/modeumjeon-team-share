"""
사용자·역할 모델 — 팀공유 모드 전용 (ENVIRONMENT=team-share-dev).
"""
from __future__ import annotations

import datetime as dt
import secrets
from typing import Optional

import bcrypt
from sqlalchemy import String, DateTime, Integer, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.db import Base


class User(Base):
    """팀공유 사용자.

    역할:
      - admin: 모든 기능 + 사용자 관리 + 시크릿·계정 설정
      - member: 일반 사용 (재고·모음전·발주 등)
    """
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    # admin / member — Day 3 권한 분리 기준
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="member")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # 메타
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)
    last_login_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime, nullable=True)

    # ─── 비밀번호 ───
    def set_password(self, raw: str) -> None:
        salt = bcrypt.gensalt(rounds=12)
        self.password_hash = bcrypt.hashpw(raw.encode("utf-8"), salt).decode("utf-8")

    def check_password(self, raw: str) -> bool:
        try:
            return bcrypt.checkpw(raw.encode("utf-8"), self.password_hash.encode("utf-8"))
        except (ValueError, AttributeError):
            return False

    # ─── Flask-Login 인터페이스 ───
    @property
    def is_authenticated(self) -> bool:
        return True

    @property
    def is_anonymous(self) -> bool:
        return False

    def get_id(self) -> str:
        return str(self.id)

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    def __repr__(self) -> str:
        return f"<User {self.email} role={self.role}>"


class LoginSession(Base):
    """로그인 세션 감사 로그 (선택 — 단순 로그용)."""
    __tablename__ = "login_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    logged_in_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)
    logged_out_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime, nullable=True)

    user: Mapped[User] = relationship("User", lazy="joined")


class PasswordResetToken(Base):
    """비밀번호 재설정 토큰 — 1시간 유효, 단발성.

    보안 정책:
      - 토큰: secrets.token_urlsafe(32) → 43자 URL-safe
      - 만료: 발급 1시간 후
      - 단발성: 사용 시 used_at 기록 → 재사용 차단
      - 이메일 enumeration 방지: 미가입 이메일도 동일 응답
    """
    __tablename__ = "password_reset_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False)
    used_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime, nullable=True)

    user: Mapped[User] = relationship("User", lazy="joined")

    @classmethod
    def new_for_user(cls, user_id: int, ttl_hours: int = 1) -> "PasswordResetToken":
        return cls(
            user_id=user_id,
            token=secrets.token_urlsafe(32),
            expires_at=dt.datetime.utcnow() + dt.timedelta(hours=ttl_hours),
        )

    @property
    def is_valid(self) -> bool:
        return self.used_at is None and dt.datetime.utcnow() < self.expires_at

    def mark_used(self) -> None:
        self.used_at = dt.datetime.utcnow()
