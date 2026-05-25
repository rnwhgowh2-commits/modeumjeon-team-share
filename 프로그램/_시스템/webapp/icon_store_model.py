"""v34.11 — brand 색 override 의 DB 영속화 모델.

기존 icon_overrides.json (머신 로컬 파일) 의 문제:
  · Fly.io 멀티 인스턴스 + 머신 파일 시스템 분리 → 머신 간 데이터 불일치
  · deploy 시 새 머신 생성 → 파일 시스템 reset → 사용자 색 사라짐

해결: Supabase PostgreSQL 테이블 (또는 SQLite fallback) 로 영속화.
  · 머신 무관, deploy 무관, 영구 보존
  · icon_store.py 가 본 모델을 통해 CRUD
"""
from sqlalchemy import Column, Integer, String, UniqueConstraint, DateTime, func
from shared.db import Base


class BrandColorOverride(Base):
    """브랜드 색상 / 아이콘 사용자 커스터마이징.

    context + target_id 조합으로 unique. 한 사용자/팀이 어떤 brand/icon 을 어떤
    색으로 바꿨는지 기록.
    """
    __tablename__ = 'brand_color_overrides'

    id = Column(Integer, primary_key=True, autoincrement=True)
    context = Column(String(64), nullable=False, index=True)
    target_id = Column(String(128), nullable=False, default='')
    icon = Column(String(64), nullable=True)
    color = Column(String(32), nullable=True)
    bg_color = Column(String(16), nullable=True)
    fg_color = Column(String(16), nullable=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint('context', 'target_id', name='uq_brand_color_ctx_target'),
    )
