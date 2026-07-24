# -*- coding: utf-8 -*-
"""캐시 검색 — 마켓에 묻지 않고 우리 DB 에서만 찾는다.

★ 6마켓 중 4곳이 상품명 검색을 못 한다(스마트스토어·롯데온은 파라미터가 아예 없고,
  옥션·G마켓은 조건을 조용히 무시). 그래서 캐시에서 찾는 이 길이 유일하다.
  실측 근거: docs/superpowers/specs/2026-07-23-모음전-상품관리-design.md §2-2
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import or_

from .models import MarketProduct

#: 한 번에 돌려줄 최대 건수. 28만 건을 통째로 보내면 화면이 멈춘다.
DEFAULT_LIMIT = 50
MAX_LIMIT = 200


def _escape_like(v: str) -> str:
    """LIKE 특수문자를 글자로 바꾼다.

    ★ '%' 는 SQL 에서 '아무거나'다. 그대로 넘기면 사장님이 '%' 를 쳤을 때
      28만 건 전체가 나오고, 본인은 '검색이 됐다'고 믿는다.
    """
    return (v.replace('\\', '\\\\')
             .replace('%', '\\%')
             .replace('_', '\\_'))


def search(session, q: str = '', *, market: Optional[str] = None,
           account_key: Optional[str] = None, status: Optional[str] = None,
           picked: Optional[bool] = None,
           limit: int = DEFAULT_LIMIT, offset: int = 0) -> dict:
    """캐시에서 상품을 찾는다.

    Args:
        q: 상품명·브랜드 일부, 또는 상품번호 전체. 비면 최근 것을 보여준다.
        picked: True=이미 담은 것만 · False=아직 안 담은 것만 · None=전부
    """
    limit = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))
    offset = max(0, int(offset or 0))
    qq = (q or '').strip()

    base = session.query(MarketProduct).filter(
        MarketProduct.deleted_at.is_(None))
    if market:
        base = base.filter(MarketProduct.market == market)
    if account_key:
        base = base.filter(MarketProduct.account_key == account_key)
    if status:
        base = base.filter(MarketProduct.status == status)
    if picked is True:
        base = base.filter(MarketProduct.group_id.isnot(None))
    elif picked is False:
        base = base.filter(MarketProduct.group_id.is_(None))
    if qq:
        like = f'%{_escape_like(qq)}%'
        base = base.filter(or_(
            MarketProduct.name.ilike(like, escape='\\'),
            MarketProduct.brand.ilike(like, escape='\\'),
            # 상품번호는 부분이 아니라 **정확히** 맞아야 한다 — 번호 일부가
            # 다른 상품 번호에 섞여 있으면 엉뚱한 게 나온다.
            MarketProduct.market_product_id == qq,
            MarketProduct.site_product_id == qq,
        ))

    total = base.count()
    rows = (base.order_by(MarketProduct.id.desc())
            .offset(offset).limit(limit).all())
    return {'total': total, 'rows': [_row(r) for r in rows],
            'limit': limit, 'offset': offset}


def _row(m: MarketProduct) -> dict:
    return {
        'id': m.id, 'market': m.market, 'account_key': m.account_key,
        'market_product_id': m.market_product_id,
        'site_product_id': m.site_product_id,
        'name': m.name, 'brand': m.brand, 'status': m.status,
        'sale_price': m.sale_price, 'group_id': m.group_id,
        'synced_at': m.synced_at.isoformat() if m.synced_at else None,
    }
