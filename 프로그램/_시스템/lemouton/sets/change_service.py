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


def list_changes(session, *, set_id, market=None, field=None, limit=200):
    """구성의 변동 이벤트를 최신순(at desc)으로 반환. market/field 선택 필터.

    source 필드로 소싱처('source')·판매처('market') 변동을 구분해 호출자가 2열 표시.
    """
    q = session.query(ChannelChangeEvent).filter(ChannelChangeEvent.set_id == set_id)
    if market:
        q = q.filter(ChannelChangeEvent.market == market)
    if field:
        q = q.filter(ChannelChangeEvent.field == field)
    q = q.order_by(ChannelChangeEvent.at.desc(), ChannelChangeEvent.id.desc()).limit(limit)
    out = []
    for e in q.all():
        out.append({
            "at": e.at.isoformat() if e.at else None,
            "source": e.source,
            "market": e.market,
            "canonical_sku": e.canonical_sku,
            "field": e.field,
            "prev_value": e.prev_value,
            "next_value": e.next_value,
        })
    return out
