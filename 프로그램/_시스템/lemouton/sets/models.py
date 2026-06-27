"""[구성 레이어] V1 경량 구성(세트) 모델 — 모음전 1 : 구성 N : 판매처 상품 N.

V1 Model/Option(canonical_sku) 위에 얹는 경량 레이어(전면 V2 전환 회피).
V2 BundleSet 의 검증된 모양(set→product→option)을 차용하되 V1 옵션을 참조한다.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Integer, Boolean, ForeignKey, Text, DateTime, JSON,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from shared.db import Base


class ProductSet(Base):
    """구성(세트) — 한 모음전에서 나눈 1 판매 단위."""
    __tablename__ = "product_sets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    model_code = Column(String(64), ForeignKey("models.model_code"),
                        nullable=False, index=True)
    name = Column(String(255), nullable=False)
    note = Column(Text)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    products = relationship("SetProduct", back_populates="product_set",
                            cascade="all, delete-orphan")
    channels = relationship("SetChannel", back_populates="product_set",
                            cascade="all, delete-orphan")


class SetProduct(Base):
    """구성 내 상품 — 다품이면 N개, 수량(quantity) 보유."""
    __tablename__ = "set_products"

    id = Column(Integer, primary_key=True, autoincrement=True)
    set_id = Column(Integer, ForeignKey("product_sets.id"),
                    nullable=False, index=True)
    model_code = Column(String(64), ForeignKey("models.model_code"),
                        nullable=False)
    quantity = Column(Integer, default=1, nullable=False)
    sort_order = Column(Integer, default=0)

    product_set = relationship("ProductSet", back_populates="products")
    options = relationship("SetOption", back_populates="set_product",
                           cascade="all, delete-orphan")


class SetOption(Base):
    """구성 상품의 선택 옵션(부분집합) — 행 존재 = 포함."""
    __tablename__ = "set_options"

    id = Column(Integer, primary_key=True, autoincrement=True)
    set_product_id = Column(Integer, ForeignKey("set_products.id"),
                            nullable=False, index=True)
    canonical_sku = Column(String(128), ForeignKey("options.canonical_sku"),
                           nullable=False)
    sort_order = Column(Integer, default=0)

    set_product = relationship("SetProduct", back_populates="options")

    __table_args__ = (
        UniqueConstraint("set_product_id", "canonical_sku",
                         name="uq_set_options_product_sku"),
    )


class SetChannel(Base):
    """구성 × 판매처 연동 — 마켓 상품번호·전송필드·상태."""
    __tablename__ = "set_channels"

    id = Column(Integer, primary_key=True, autoincrement=True)
    set_id = Column(Integer, ForeignKey("product_sets.id"),
                    nullable=False, index=True)
    market = Column(String(20), nullable=False)
    # nullable=False + 'default' 센티넬 — NULL 이면 유니크 제약이 무력화(NULL≠NULL)되어
    # '기본 계정' 중복 채널이 막히지 않으므로. (models_v2 SourcingAccount 관례 동일)
    account_key = Column(String(64), nullable=False, default="default")
    market_product_id = Column(String(64))
    api_fields = Column(JSON, default=dict)
    status = Column(String(16), default="pending", nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    product_set = relationship("ProductSet", back_populates="channels")
    link_results = relationship("SetChannelOption", back_populates="channel",
                                cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("set_id", "market", "account_key",
                         name="uq_set_channels_set_market_account"),
    )


class SetChannelOption(Base):
    """채널 × 옵션 연동 결과 — 옵션이 어느 마켓 옵션ID에 매칭됐는지."""
    __tablename__ = "set_channel_options"

    id = Column(Integer, primary_key=True, autoincrement=True)
    channel_id = Column(Integer, ForeignKey("set_channels.id"),
                        nullable=False, index=True)
    canonical_sku = Column(String(128), nullable=False)
    market_option_id = Column(String(128))            # matched 만 채움
    status = Column(String(16), nullable=False)        # matched|unmatched|ambiguous|duplicate
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    channel = relationship("SetChannel", back_populates="link_results")

    __table_args__ = (
        UniqueConstraint("channel_id", "canonical_sku",
                         name="uq_set_channel_options_channel_sku"),
    )
