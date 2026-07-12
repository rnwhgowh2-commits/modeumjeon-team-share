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


class CardKeywordConfig(Base):
    """카드별 분류 키워드 설정 — 팀 공유 단일 row (id=1 고정).

    원본(대량등록 마진계산기)은 단일 사용자 card_keywords.json 이었으나, 팀 공유
    앱에서는 DB 한 행으로 승격한다(멀티유저가 같은 설정을 본다). `config` 에 전체
    설정 JSON(top-level `cards` + `_comment`/`version` 등)을 통째로 담는다 — 원본
    계약이 top-level 키를 그대로 보존하도록 요구하므로 컬럼 분해하지 않는다.
    비어 있으면 lemouton/margin/card_keywords_seed.json 으로 시드한다.
    """

    __tablename__ = "card_keyword_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[_dt.datetime] = mapped_column(
        DateTime, default=_dt.datetime.utcnow, onupdate=_dt.datetime.utcnow)
