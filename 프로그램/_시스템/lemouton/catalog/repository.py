# -*- coding: utf-8 -*-
"""캐시 읽기·쓰기.

★ 지운 상품을 진짜로 지우지 않는다 — 마켓에서 사라진 것도 이력이다.
  deleted_at 만 찍고, 되살아나면 푼다.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Optional

from .fetchers import CatalogRow
from .models import MarketProduct, MarketProductCount
from .status import UNIFIED


def _now():
    return datetime.now(timezone.utc)


def upsert_rows(session, market: str, account_key: str,
                rows: Iterable[CatalogRow]) -> int:
    """마켓 상품 머리글을 넣거나 갱신. 돌려주는 값 = 처리한 건수.

    같은 (마켓, 계정, 상품번호)면 갱신한다 — 중복 행이 생기면 건수가 부푼다.
    """
    rows = list(rows)
    if not rows:
        return 0

    ids = [r.market_product_id for r in rows]
    existing = {
        m.market_product_id: m
        for m in session.query(MarketProduct).filter(
            MarketProduct.market == market,
            MarketProduct.account_key == account_key,
            MarketProduct.market_product_id.in_(ids)).all()
    }
    now = _now()
    for r in rows:
        m = existing.get(r.market_product_id)
        if m is None:
            m = MarketProduct(market=market, account_key=account_key,
                              market_product_id=r.market_product_id)
            session.add(m)
            existing[r.market_product_id] = m   # 같은 배치에 중복이 와도 한 줄
        m.name = r.name
        m.status = r.status
        m.raw_status = r.raw_status
        m.sale_price = r.sale_price
        m.synced_at = now
        m.deleted_at = None      # 되살아났으면 지움 표시를 푼다
        if r.brand:
            m.brand = r.brand
        if r.site_product_id:
            m.site_product_id = r.site_product_id
        if r.registered_at:
            m.registered_at = r.registered_at
    session.commit()
    return len(rows)


def mark_missing(session, market: str, account_key: str,
                 seen_ids: set) -> int:
    """이번 훑기에서 안 보인 상품에 지움 표시. 행은 남긴다."""
    q = session.query(MarketProduct).filter(
        MarketProduct.market == market,
        MarketProduct.account_key == account_key,
        MarketProduct.deleted_at.is_(None))
    if seen_ids:
        q = q.filter(~MarketProduct.market_product_id.in_(seen_ids))
    now = _now()
    n = 0
    for m in q.all():
        m.deleted_at = now
        n += 1
    session.commit()
    return n


def set_count(session, market: str, account_key: str, status: str,
              count: int, *, source: str = 'cache') -> None:
    """건수 스냅샷 1칸을 쓴다. 같은 칸은 덮어쓴다."""
    row = session.query(MarketProductCount).filter_by(
        market=market, account_key=account_key, status=status).one_or_none()
    if row is None:
        row = MarketProductCount(market=market, account_key=account_key,
                                 status=status)
        session.add(row)
    row.count = int(count)
    row.source = source
    row.measured_at = _now()
    session.commit()


def refresh_counts_from_cache(session, market: str, account_key: str) -> dict:
    """우리 캐시를 세어 스냅샷을 갱신(source='cache'). 지운 상품은 빼고 센다.

    ★ 이번에 0건이 된 상태도 **0 으로 눌러 쓴다.** 안 그러면 옛 숫자가 남아
      없는 상품을 있다고 보여준다(품절 0건이 됐는데 612 로 계속 뜨는 식).
    """
    from sqlalchemy import func
    rows = (session.query(MarketProduct.status, func.count(MarketProduct.id))
            .filter(MarketProduct.market == market,
                    MarketProduct.account_key == account_key,
                    MarketProduct.deleted_at.is_(None))
            .group_by(MarketProduct.status).all())
    counted = {status: n for status, n in rows}

    # 이번에 안 나온 상태 중 **이미 스냅샷에 있던 것**은 0 으로 내린다.
    stale = {c.status for c in session.query(MarketProductCount).filter_by(
        market=market, account_key=account_key).all()} - set(counted)

    for status, n in counted.items():
        set_count(session, market, account_key, status, n, source='cache')
    for status in stale:
        set_count(session, market, account_key, status, 0, source='cache')
    return counted


def dashboard_counts(session, *, market: Optional[str] = None) -> dict:
    """화면이 읽는 모양 — {마켓: {계정: {상태: 건수}}}."""
    q = session.query(MarketProductCount)
    if market:
        q = q.filter(MarketProductCount.market == market)
    out: dict = {}
    for c in q.all():
        out.setdefault(c.market, {}).setdefault(c.account_key, {})[c.status] = c.count
    return out


def account_measured_at(session) -> dict:
    """{(마켓, 계정): 마지막 확인 시각} — 화면의 「마지막 확인」 표시용."""
    out: dict = {}
    for c in session.query(MarketProductCount).all():
        key = (c.market, c.account_key)
        cur = out.get(key)
        if c.measured_at and (cur is None or c.measured_at > cur):
            out[key] = c.measured_at
        elif key not in out:
            out[key] = c.measured_at
    return out
