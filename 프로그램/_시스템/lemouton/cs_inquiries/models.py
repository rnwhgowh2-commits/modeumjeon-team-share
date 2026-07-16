"""CS 고객문의 처리상태(팀 공유). create_all 자동생성(Alembic 불요). 삭제(정리) 플래그만 저장."""
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime
from shared.db import Base


class InquiryHandling(Base):
    __tablename__ = "inquiry_handling"
    id = Column(Integer, primary_key=True, autoincrement=True)
    inquiry_key = Column(String(128), unique=True, nullable=False, index=True)  # market:inquiry_id
    market = Column(String(32))
    dismissed_at = Column(DateTime)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))
