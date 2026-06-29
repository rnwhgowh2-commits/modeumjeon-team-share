"""변동 기록 서비스 — 판매처 채널 옵션의 stock/price 변동을 이력 테이블에 기록한다."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from lemouton.sets.models import ChannelChangeEvent


def record_change(
    session: Session,
    *,
    set_id: int,
    market: str,
    canonical_sku: str,
    field: str,
    source: str,
    prev_value: Optional[int],
    next_value: Optional[int],
    at: Optional[datetime] = None,
) -> bool:
    """prev_value == next_value 면 아무것도 하지 않고 False 반환.

    다르면 ChannelChangeEvent 를 session 에 추가하고 True 반환.
    호출자가 commit 해야 영속된다.
    """
    if prev_value == next_value:
        return False

    event = ChannelChangeEvent(
        set_id=set_id,
        market=market,
        canonical_sku=canonical_sku,
        field=field,
        source=source,
        prev_value=prev_value,
        next_value=next_value,
        at=at or datetime.now(timezone.utc),
    )
    session.add(event)
    return True
