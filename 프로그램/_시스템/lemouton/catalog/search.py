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
from .timefmt import iso_utc

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


#: 자동완성이 한 번에 돌려줄 최대 건수. 드롭다운에 그 이상은 어차피 안 보인다.
SUGGEST_LIMIT = 10


def suggest(session, q: str, *, market: Optional[str] = None,
            account_key: Optional[str] = None,
            limit: int = SUGGEST_LIMIT) -> dict:
    """자동완성 — 글자를 치는 동안 부르는 **가벼운** 창구.

    ★ search() 와 다른 점 = **전체 건수를 세지 않는다.**
      search() 는 `count()` 로 표 전체를 세는데, 자동완성은 글자마다 부르므로
      28만 건을 매 글자마다 세면 화면이 멈춘다. 몇 개만 집어 오면 충분하다.

    ★ 두 글자 미만이면 **아무것도 안 돌려준다.** 한 글자로 찾으면 거의 전부가
      걸려 색인이 소용없고, 사장님께도 쓸모없는 목록이 뜬다.
    """
    qq = (q or '').strip()
    if len(qq) < 2:
        return {'rows': [], 'q': qq, 'reason': '두 글자 이상 적어주세요'}
    limit = max(1, min(int(limit or SUGGEST_LIMIT), 25))

    base = session.query(MarketProduct).filter(
        MarketProduct.deleted_at.is_(None))
    if market:
        base = base.filter(MarketProduct.market == market)
    if account_key:
        base = base.filter(MarketProduct.account_key == account_key)
    like = f'%{_escape_like(qq)}%'
    base = base.filter(or_(
        MarketProduct.name.ilike(like, escape='\\'),
        MarketProduct.brand.ilike(like, escape='\\'),
    ))
    rows = base.order_by(MarketProduct.id.desc()).limit(limit).all()
    return {'rows': [_row(r) for r in rows], 'q': qq, 'reason': ''}


def index_status(session) -> dict:
    """찾기 색인이 실제로 깔려 있나 — **조용한 실패를 막는 창구**.

    색인 생성은 실패해도 프로그램이 돈다(그냥 느려진다). 그래서 「빠른 줄 알았는데
    아니었다」가 생긴다. 여기서 눈으로 확인한다.
    SQLite 는 이 색인이 없는 게 정상이라 `해당없음` 으로 답한다.
    """
    from sqlalchemy import text
    dialect = session.bind.dialect.name if session.bind is not None else '?'
    if dialect != 'postgresql':
        return {'dialect': dialect, 'applicable': False,
                'note': '이 색인은 PostgreSQL 전용입니다 (로컬 SQLite 는 해당 없음)'}
    out = {'dialect': dialect, 'applicable': True}
    try:
        out['pg_trgm'] = bool(session.execute(text(
            "SELECT 1 FROM pg_extension WHERE extname='pg_trgm'")).first())
    except Exception as e:      # noqa: BLE001
        out['pg_trgm'] = None
        out['error'] = str(e)[:200]
    try:
        rows = session.execute(text(
            "SELECT indexname FROM pg_indexes WHERE tablename='market_products'"
        )).all()
        names = {r[0] for r in rows}
        out['indexes'] = sorted(names)
        out['name_trgm'] = 'ix_mp_name_trgm' in names
        out['brand_trgm'] = 'ix_mp_brand_trgm' in names
    except Exception as e:      # noqa: BLE001
        out['error'] = str(e)[:200]
    out['ok'] = bool(out.get('pg_trgm') and out.get('name_trgm'))
    return out


def _row(m: MarketProduct) -> dict:
    return {
        'id': m.id, 'market': m.market, 'account_key': m.account_key,
        'market_product_id': m.market_product_id,
        'site_product_id': m.site_product_id,
        'name': m.name, 'brand': m.brand, 'status': m.status,
        'sale_price': m.sale_price, 'exposed_price': m.exposed_price,
        'delivery_fee': m.delivery_fee,
        'group_id': m.group_id,
        'synced_at': iso_utc(m.synced_at),
    }
