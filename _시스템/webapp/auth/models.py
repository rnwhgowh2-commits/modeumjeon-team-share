"""
사용자·역할 모델 — 팀공유 모드 전용 (ENVIRONMENT=team-share-dev).

기존 시스템엔 이 파일이 존재하지 않음 → 동기화 시에도 신규에만 유지 (.sync-ignore 보호).
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
