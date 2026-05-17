"""미매핑 큐 — 자동 디스커버리에서 발견된 신규 후보."""
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import select

from .models import DiscoveryQueueItem


def enqueue(
    session: Session, *,
    source: str,
    raw_text: str,
    raw_payload_json: str | None = None,
    suggested_model_code: str | None = None,
    suggested_color_code: str | None = None,
    suggested_size_code: str | None = None,
    confidence: float | None = None,
) -> DiscoveryQueueItem:
    # dedup: same source + same raw_text + status pending
    existing = session.scalars(
        select(DiscoveryQueueItem).where(
            DiscoveryQueueItem.source == source,
            DiscoveryQueueItem.raw_text == raw_text,
            DiscoveryQueueItem.status == "pending",
        )
    ).first()
    if existing:
        return existing

    item = DiscoveryQueueItem(
        source=source,
        raw_text=raw_text,
        raw_payload_json=raw_payload_json,
        suggested_model_code=suggested_model_code,
        suggested_color_code=suggested_color_code,
        suggested_size_code=suggested_size_code,
        confidence=confidence,
        status="pending",
    )
    session.add(item)
    return item


def list_pending(session: Session) -> list[DiscoveryQueueItem]:
    stmt = select(DiscoveryQueueItem).where(DiscoveryQueueItem.status == "pending")
    return list(session.scalars(stmt).all())


def resolve(session: Session, item_id: int, *, canonical_sku: str) -> DiscoveryQueueItem:
    item = session.get(DiscoveryQueueItem, item_id)
    if item is None:
        raise ValueError(f"queue item {item_id} not found")
    item.status = "resolved"
    item.resolved_canonical_sku = canonical_sku
    item.resolved_at = datetime.now(timezone.utc)
    return item


def ignore(session: Session, item_id: int) -> DiscoveryQueueItem:
    item = session.get(DiscoveryQueueItem, item_id)
    if item is None:
        raise ValueError(f"queue item {item_id} not found")
    item.status = "ignored"
    item.resolved_at = datetime.now(timezone.utc)
    return item
