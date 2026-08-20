"""CS 클레임 처리상태(팀 공유). Alembic 불요 — shared/db.py:init_db()의 create_all이 생성.

단계(신규요청/대응중/대응완료)는 저장하지 않고 매번 파생(service.derive_stage).
저장하는 것은 ①확인 시각 ②간단메모 둘뿐.
"""
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, DateTime
from shared.db import Base


def _now():
    return datetime.now(timezone.utc)


class ClaimHandling(Base):
    __tablename__ = "claim_handling"

    id = Column(Integer, primary_key=True, autoincrement=True)
    claim_key = Column(String(128), unique=True, nullable=False, index=True)  # market:order_no:type
    market = Column(String(32))
    order_no = Column(String(64), index=True)
    claim_type = Column(String(8))              # 취소/교환/반품
    acknowledged_at = Column(DateTime)          # 「확인」 누른 시각(있으면 대응중)
    memo = Column(Text)                         # 간단메모
    dismissed_at = Column(DateTime)             # 수기 삭제(있으면 목록서 숨김)
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)
