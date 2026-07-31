"""마켓별 정책 — 정책 1개 · 항목값 · 상품 적용.

값은 (정책 × 마켓 × 항목) 한 칸씩 저장한다. 항목이 늘 때마다 칼럼을 늘리면
마켓 6개 × 항목 30개 = 180칼럼이 된다 — 그래서 세로로 쌓는다.
항목표는 lemouton/policy/fields.py 가 단일 진실 원천.
"""
from datetime import datetime, timezone

from sqlalchemy import (
    Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint,
)

from shared.db import Base


def _utcnow():
    return datetime.now(timezone.utc)


class MarketPolicy(Base):
    """정책 한 벌. 여러 상품에 같은 정책을 붙일 수 있다."""
    __tablename__ = 'market_policies'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(120), nullable=False)
    memo = Column(Text)
    # 기본 정책 — 새 상품에 자동으로 붙는다(노션 「기본 셋팅 해두고 전체 적용」).
    is_default = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)
    deleted_at = Column(DateTime)


class MarketPolicyValue(Base):
    """(정책 × 마켓 × 항목) 값 한 칸. 비어 있으면 「안 정함」 — 0 이 아니다."""
    __tablename__ = 'market_policy_values'

    id = Column(Integer, primary_key=True, autoincrement=True)
    policy_id = Column(Integer, ForeignKey('market_policies.id'),
                       nullable=False, index=True)
    market = Column(String(20), nullable=False)
    field_key = Column(String(40), nullable=False)
    value = Column(Text)                       # 전부 문자열로 보관 — 화면 입력 그대로
    # 「마켓 공통」에서 받은 시각. 직접 저장하면 None 으로 돌아간다.
    #   🔴 값 비교로 「공통 따름」을 판정하면 안 된다 — 공통이 나중에 바뀌면
    #     받은 적 있는 마켓이 「직접 고침」으로 잘못 뜬다.
    from_common_at = Column(DateTime)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint('policy_id', 'market', 'field_key', name='uq_policy_value'),
        Index('ix_policy_value_lookup', 'policy_id', 'market'),
    )


class BundlePolicyLink(Base):
    """어느 모음전 상품에 어느 정책을 붙였나. 상품 하나에 정책 하나."""
    __tablename__ = 'bundle_policy_links'

    model_code = Column(String(64), ForeignKey('models.model_code'), primary_key=True)
    policy_id = Column(Integer, ForeignKey('market_policies.id'),
                       nullable=False, index=True)
    applied_at = Column(DateTime, default=_utcnow, nullable=False)
