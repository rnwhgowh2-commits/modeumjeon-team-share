"""옵션 소싱처 URL 관리 서비스 (Phase 3).

ai-workflow cycle 20260521

⑤ 결정: 소싱처 URL = 옵션 단위로 일원화 + 한 소싱처에 URL 여러 개.
OptionSourceUrl 의 (canonical_sku, source_id) UniqueConstraint 를 제거해
같은 소싱처에 URL 을 여러 개 등록할 수 있다.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from .models_pricing import OptionSourceUrl


def add_source_url(session: Session, canonical_sku: str, source_id: int,
                   product_url: str) -> OptionSourceUrl:
    """옵션에 소싱처 URL 추가. 같은 소싱처에 URL 여러 개 허용 (Phase 3)."""
    row = OptionSourceUrl(
        canonical_sku=canonical_sku,
        source_id=source_id,
        product_url=product_url,
    )
    session.add(row)
    session.flush()
    return row


def list_source_urls(session: Session, canonical_sku: str) -> list:
    """옵션의 모든 소싱처 URL — source_id · id 순."""
    return (session.query(OptionSourceUrl)
            .filter_by(canonical_sku=canonical_sku)
            .order_by(OptionSourceUrl.source_id, OptionSourceUrl.id)
            .all())


def count_urls_by_source(session: Session, canonical_sku: str) -> dict:
    """옵션의 소싱처별 URL 개수 — {source_id: count}."""
    counts: dict[int, int] = {}
    for row in list_source_urls(session, canonical_sku):
        counts[row.source_id] = counts.get(row.source_id, 0) + 1
    return counts


def delete_source_url(session: Session, url_id: int) -> int:
    """소싱처 URL 1개 삭제 (id 기준). 삭제된 행 수 반환."""
    return session.query(OptionSourceUrl).filter_by(id=url_id).delete()
