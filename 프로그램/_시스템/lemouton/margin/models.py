# -*- coding: utf-8 -*-
"""마진 분석 세션 영속화.

Alembic 없음 — shared/db.py:init_db() 의 Base.metadata.create_all 이 생성한다.
등록 조건: app.py 가 이 모듈을 import 할 것.
"""
from __future__ import annotations

import datetime as _dt

from sqlalchemy import Date, DateTime, Integer, JSON, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from shared.db import Base


class MarginAnalysis(Base):
    """분석 1회 = 레코드 1개. 팀 전체가 같은 목록을 본다. 최근 20건 보관."""

    __tablename__ = "margin_analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # webapp/auth/models.py 와 동일하게 utcnow — 저장소 표준(naive UTC)에 맞춘다.
    created_at: Mapped[_dt.datetime] = mapped_column(
        DateTime, default=_dt.datetime.utcnow, index=True)
    created_by: Mapped[str | None] = mapped_column(String(120), nullable=True)

    period_from: Mapped[_dt.date] = mapped_column(Date)
    period_to: Mapped[_dt.date] = mapped_column(Date)

    buy_file_key: Mapped[str] = mapped_column(String(512))
    buy_filename: Mapped[str] = mapped_column(String(255))
    shopmine_file_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    shopmine_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)

    markets_fetched: Mapped[list] = mapped_column(JSON, default=list)
    markets_failed: Mapped[list] = mapped_column(JSON, default=list)
    counts: Mapped[dict] = mapped_column(JSON, default=dict)

    result_blob: Mapped[bytes] = mapped_column(LargeBinary)
