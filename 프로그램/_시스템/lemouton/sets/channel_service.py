"""[구성 레이어] 구성 × 판매처 채널 CRUD 서비스."""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from lemouton.sets.models import SetChannel


def add_channel(session: Session, *, set_id: int, market: str,
                account_key: Optional[str] = None) -> SetChannel:
    # account_key 는 nullable=False — None/빈값이면 'default' 로 보정(유니크 제약 보존).
    c = SetChannel(set_id=set_id, market=market,
                   account_key=account_key or "default")
    session.add(c)
    session.flush()
    return c


def set_channel_product(session: Session, *, channel_id: int,
                        market_product_id: str,
                        api_fields: Optional[dict] = None) -> Optional[SetChannel]:
    c = session.get(SetChannel, channel_id)
    if c is None:
        return None
    c.market_product_id = market_product_id
    if api_fields is not None:
        c.api_fields = api_fields
    c.status = "linked" if market_product_id else "pending"
    session.flush()
    return c


def list_channels(session: Session, set_id: int) -> list[SetChannel]:
    return list(
        session.query(SetChannel).filter_by(set_id=set_id)
        .order_by(SetChannel.id).all()
    )


def remove_channel(session: Session, channel_id: int) -> bool:
    c = session.get(SetChannel, channel_id)
    if c is None:
        return False
    session.delete(c)
    return True
