"""[v2] 멀티 계정 DB 모델.

핵심: 같은 모음전을 N 마켓 계정에 등록 가능.
계정마다 다른 product_id, 다른 상품명, 다른 가격, 다른 노출.

설계 문서: docs/architecture_v2.md §3.2
"""
from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Boolean, ForeignKey,
    UniqueConstraint, Index,
)

from shared.db import Base


def _utcnow():
    return datetime.now(timezone.utc)


class MarketAccount(Base):
    """마켓 계정 단위 — 사용자가 운영하는 N개 스토어 각각."""
    __tablename__ = "market_accounts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    market = Column(String(16), nullable=False)  # smartstore | coupang
    account_name = Column(String(120), nullable=False)
    credentials_encrypted = Column(Text, nullable=False)  # Fernet 암호화 JSON
    is_active = Column(Boolean, default=True, nullable=False)

    note = Column(Text)

    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)
    deleted_at = Column(DateTime)

    __table_args__ = (
        UniqueConstraint('market', 'account_name', name='uq_market_account_name'),
        Index('ix_market_accounts_market', 'market'),
    )


class BundleAccountRegistration(Base):
    """모음전 × 계정 → 마켓 상품 ID 매핑.

    1 모음전 N 계정 = N 행.
    각 행마다 자기 마켓 상품 ID + 자기 상품명·가격 override.
    """
    __tablename__ = "bundle_account_registrations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    model_code = Column(String(64), ForeignKey('models.model_code'), nullable=False)
    account_id = Column(Integer, ForeignKey('market_accounts.id'), nullable=False)

    external_product_id = Column(String(64))  # naver originProductNo or coupang sellerProductId
    display_name_override = Column(String(255))
    sale_price_override = Column(Integer)
    is_registered = Column(Boolean, default=False, nullable=False)
    registered_at = Column(DateTime)

    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint('model_code', 'account_id', name='uq_bundle_account_reg'),
        Index('ix_bundle_account_reg_model', 'model_code'),
        Index('ix_bundle_account_reg_account', 'account_id'),
    )


class OptionAccountRegistration(Base):
    """옵션 × 계정 → 마켓 옵션 ID 매핑.

    1 옵션 N 계정 = N 행.
    각 행마다 자기 마켓 옵션 ID + 노출 토글.
    """
    __tablename__ = "option_account_registrations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    canonical_sku = Column(String(128), ForeignKey('options.canonical_sku'), nullable=False)
    account_id = Column(Integer, ForeignKey('market_accounts.id'), nullable=False)

    external_option_id = Column(String(128))  # naver_option_id or coupang_option_id (vendorItemId)
    is_visible = Column(Boolean, default=True, nullable=False)

    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint('canonical_sku', 'account_id', name='uq_option_account_reg'),
        Index('ix_option_account_reg_sku', 'canonical_sku'),
        Index('ix_option_account_reg_account', 'account_id'),
    )
