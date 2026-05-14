"""[D] 마켓 등록·동기화 추적 테이블."""
from sqlalchemy import (
    Column, String, Integer, DateTime, Text, PrimaryKeyConstraint,
)
from datetime import datetime, timezone

from shared.db import Base


class MarketRegistration(Base):
    """옵션 × 마켓 단위 등록·동기화 추적."""
    __tablename__ = "market_registrations"

    canonical_sku = Column(String(128), nullable=False)
    market = Column(String(16), nullable=False)  # 'smartstore' | 'coupang'
    market_product_id = Column(String(64))
    market_option_id = Column(String(128))
    last_synced_price = Column(Integer)
    last_synced_stock = Column(Integer)
    status = Column(String(16), default="pending", nullable=False)
    last_attempt_at = Column(DateTime)
    last_success_at = Column(DateTime)
    sync_error = Column(String(500))
    sync_attempts = Column(Integer, default=0, nullable=False)
    next_retry_at = Column(DateTime)
    pricing_reason = Column(String(64))

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        PrimaryKeyConstraint("canonical_sku", "market"),
    )
