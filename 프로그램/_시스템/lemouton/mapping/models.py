"""맵핑 사전 DB 모델 — 차원·캐노니컬·별칭 3 테이블.

사용자가 직접 추가/수정/삭제 — 차원은 모델/색상/사이즈에 고정 안 됨.
"""
from sqlalchemy import (
    Column, Integer, String, Boolean, ForeignKey, DateTime, UniqueConstraint, Index,
)
from sqlalchemy.orm import relationship
from datetime import datetime, timezone

from shared.db import Base


class AliasDimension(Base):
    """사용자 정의 차원 — 예: 모델/색상/사이즈/재질/두께/패턴.

    매칭 점수 가중치 합 = 100 권장 (사용자가 조정). UI에 점수 숫자는 노출 안 함.
    """
    __tablename__ = "alias_dimensions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(64), nullable=False, unique=True)
    weight = Column(Integer, nullable=False, default=0)
    sort_order = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    canonicals = relationship(
        "AliasCanonical", back_populates="dimension",
        cascade="all, delete-orphan", order_by="AliasCanonical.sort_order",
    )


class AliasCanonical(Base):
    """차원 안의 캐노니컬 값 — 예: '블루', '230', '르무통 클래식'.

    재고관리 마스터에 존재하는 정식 표기.
    """
    __tablename__ = "alias_canonicals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    dimension_id = Column(
        Integer, ForeignKey("alias_dimensions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    value = Column(String(128), nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    dimension = relationship("AliasDimension", back_populates="canonicals")
    aliases = relationship(
        "AliasMapping", back_populates="canonical",
        cascade="all, delete-orphan", order_by="AliasMapping.id",
    )

    __table_args__ = (
        UniqueConstraint("dimension_id", "value", name="uq_canonical_dim_val"),
    )


class AliasMapping(Base):
    """캐노니컬의 별칭 — 예: '파랑' → 캐노니컬 '블루'.

    source: 'manual' = 사용자가 사전 페이지에서 직접 입력
            'learned' = 모음전 옵션 inline picker 매핑 후 자동 학습
    """
    __tablename__ = "alias_mappings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    canonical_id = Column(
        Integer, ForeignKey("alias_canonicals.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    alias = Column(String(128), nullable=False)
    source = Column(String(16), nullable=False, default="manual")
    learned_at = Column(DateTime)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    canonical = relationship("AliasCanonical", back_populates="aliases")

    __table_args__ = (
        UniqueConstraint("canonical_id", "alias", name="uq_mapping_canonical_alias"),
        Index("ix_mapping_alias_lookup", "alias"),
    )
