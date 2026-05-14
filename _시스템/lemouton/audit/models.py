"""[v2] 감사 로그 모델 — universal 변경 추적.

모든 주요 엔티티(Model/Option/SourceProduct/MarketAccount 등)의 create/update/delete를
한 테이블에서 추적. (target_table, target_id) 로 어느 행 변경인지 식별.

설계 문서: docs/architecture_v2.md §3.3
"""
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, DateTime, Index

from shared.db import Base


def _utcnow():
    return datetime.now(timezone.utc)


class AuditLog(Base):
    """범용 변경 이력. 한 행 = 한 변경 사건."""
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)

    actor = Column(String(64), default='system', nullable=False)  # 사용자 식별 또는 'system'
    target_table = Column(String(64), nullable=False)
    target_id = Column(String(128), nullable=False)
    action = Column(String(16), nullable=False)  # create | update | delete | restore

    before_json = Column(Text)  # 변경 전 (JSON)
    after_json = Column(Text)   # 변경 후 (JSON)
    reason = Column(Text)       # 사용자 입력 변경 사유 (선택)

    at = Column(DateTime, default=_utcnow, nullable=False)

    __table_args__ = (
        Index('ix_audit_target', 'target_table', 'target_id'),
        Index('ix_audit_at', 'at'),
        Index('ix_audit_actor', 'actor'),
    )
