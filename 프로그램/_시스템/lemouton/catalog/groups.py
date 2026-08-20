# -*- coding: utf-8 -*-
"""묶기 — 흩어진 마켓 상품을 한 상품으로.

확정 시안 ⑤ 「대표를 정하고 붙이기」. 사장님이 기준 상품 하나를 세우고
나머지를 거기에 붙인다. 프로그램은 후보만 보여주고 **확정은 사장님이** 한다 —
잘못 묶으면 엉뚱한 상품끼리 붙어 가격·재고가 섞인다.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from .models import MarketProduct, MarketProductGroup
from .timefmt import iso_utc


def _now():
    return datetime.now(timezone.utc)


def _alive(session, ids: list) -> list:
    """살아있는 상품만 돌려준다. 하나라도 없으면 바로 알린다(조용한 누락 금지)."""
    ids = [int(i) for i in ids]
    rows = session.query(MarketProduct).filter(
        MarketProduct.id.in_(ids),
        MarketProduct.deleted_at.is_(None)).all()
    found = {r.id for r in rows}
    missing = [i for i in ids if i not in found]
    if missing:
        raise ValueError(f"없는 상품이 섞여 있습니다: {missing}")
    return rows


def create_group(session, *, leader_id: int, name: Optional[str] = None,
                 brand: Optional[str] = None) -> dict:
    """대표 상품 하나로 묶음을 만든다. 이름·브랜드는 대표에서 가져온다."""
    m = session.get(MarketProduct, int(leader_id))
    if m is None:
        raise ValueError(f"없는 상품입니다: {leader_id}")
    if m.deleted_at is not None:
        raise ValueError("마켓에서 사라진 상품은 대표로 세울 수 없습니다.")
    g = MarketProductGroup(
        name=(name or m.name or f'상품 {m.market_product_id}'),
        brand=(brand or m.brand))
    session.add(g)
    session.flush()
    m.group_id = g.id
    session.commit()
    return get_group(session, g.id)


def attach(session, group_id: int, ids: list, *, detail: bool = False):
    """묶음에 마켓 상품을 붙인다.

    ★ 이미 다른 묶음에 있으면 **옮기고 알려준다.** 조용히 두 곳에 속하면
      어느 쪽이 진짜인지 알 수 없다.
    """
    g = session.get(MarketProductGroup, int(group_id))
    if g is None or g.deleted_at is not None:
        raise ValueError(f"없는 묶음입니다: {group_id}")
    rows = _alive(session, ids)
    moved = []
    for m in rows:
        if m.group_id is not None and m.group_id != g.id:
            moved.append({'market_product_id': m.market_product_id,
                          'from_group_id': m.group_id})
        m.group_id = g.id
    g.updated_at = _now()
    session.commit()
    if detail:
        return {'attached': len(rows), 'moved': moved}
    return len(rows)


def detach(session, ids: list) -> int:
    """묶음에서 뗀다. ★ 상품 자체는 남는다 — 마켓엔 그대로 있다."""
    rows = session.query(MarketProduct).filter(
        MarketProduct.id.in_([int(i) for i in ids])).all()
    n = 0
    for m in rows:
        if m.group_id is not None:
            m.group_id = None
            n += 1
    session.commit()
    return n


def delete_group(session, group_id: int) -> bool:
    """묶음을 지운다. ★ 붙었던 상품은 풀어줄 뿐 지우지 않는다."""
    g = session.get(MarketProductGroup, int(group_id))
    if g is None:
        return False
    for m in session.query(MarketProduct).filter_by(group_id=g.id).all():
        m.group_id = None
    g.deleted_at = _now()
    session.commit()
    return True


def get_group(session, group_id: int) -> Optional[dict]:
    """묶음 1건 — 마켓별 카드에 필요한 것까지(확정 시안 ⑥)."""
    g = session.get(MarketProductGroup, int(group_id))
    if g is None or g.deleted_at is not None:
        return None
    members = session.query(MarketProduct).filter(
        MarketProduct.group_id == g.id,
        MarketProduct.deleted_at.is_(None)).order_by(
            MarketProduct.market, MarketProduct.account_key).all()
    return {
        'id': g.id, 'name': g.name, 'brand': g.brand,
        'member_count': len(members),
        'markets': sorted({m.market for m in members}),
        'members': [{
            'id': m.id, 'market': m.market, 'account_key': m.account_key,
            'market_product_id': m.market_product_id,
            'site_product_id': m.site_product_id,
            'name': m.name, 'status': m.status, 'sale_price': m.sale_price,
            'synced_at': iso_utc(m.synced_at),
        } for m in members],
    }


def list_groups(session, *, q: str = '', limit: int = 50,
                offset: int = 0) -> dict:
    """담아둔 모음전 상품 목록."""
    from .search import _escape_like

    base = session.query(MarketProductGroup).filter(
        MarketProductGroup.deleted_at.is_(None))
    qq = (q or '').strip()
    if qq:
        like = f'%{_escape_like(qq)}%'
        base = base.filter(MarketProductGroup.name.ilike(like, escape='\\'))
    total = base.count()
    limit = max(1, int(limit or 50))
    offset = max(0, int(offset or 0))
    gs = (base.order_by(MarketProductGroup.id.desc())
          .offset(offset).limit(limit).all())

    ids = [g.id for g in gs]
    members: dict = {}
    if ids:
        for m in session.query(MarketProduct).filter(
                MarketProduct.group_id.in_(ids),
                MarketProduct.deleted_at.is_(None)).all():
            members.setdefault(m.group_id, []).append(m)

    rows = []
    for g in gs:
        ms = members.get(g.id, [])
        prices = [m.sale_price for m in ms if m.sale_price is not None]
        rows.append({
            'id': g.id, 'name': g.name, 'brand': g.brand,
            'member_count': len(ms),
            'markets': sorted({m.market for m in ms}),
            # ★ 마켓마다 값이 다르다 — 한 값으로 뭉개면 어느 마켓 값인지 알 수 없다.
            'price_min': min(prices) if prices else None,
            'price_max': max(prices) if prices else None,
            'has_soldout': any(m.status == 'soldout' for m in ms),
            'has_stopped': any(m.status == 'stopped' for m in ms),
        })
    return {'total': total, 'rows': rows}
