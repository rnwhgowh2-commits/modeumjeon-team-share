# -*- coding: utf-8 -*-
"""소싱처 가격·재고 이력 남기기 — 노션 ④「가격변동은 그래프」의 데이터를 모은다.

사장님 확정 (2026-07-31):
    · 가격·재고가 **바뀌면 항상** 남긴다
    · 안 바뀌면 **하루 2회까지만** 남긴다

안 바뀐 값을 크롤할 때마다 쌓으면 표만 커지고 그래프는 같은 선이 된다.
그렇다고 아예 안 남기면 「그동안 안 바뀌었다」는 사실 자체가 사라져,
그래프에 구멍이 뚫리고 그게 「크롤을 안 돌았다」로 읽힌다. 그래서 하루 2회.

🔴 표면가를 남긴다(혜택 차감 **전**). 최종매입가는 혜택 템플릿이 바뀌면 과거 시점
   값도 달라져 「그때 얼마였나」의 답이 못 된다. 화면이 기준을 밝힌다.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

#: 값이 안 바뀐 날 남기는 최대 횟수 (사장님 확정)
DAILY_NO_CHANGE_CAP = 2


def _utcnow():
    return datetime.now(timezone.utc)


def _day_bounds(now):
    """그 날의 [00:00, 24:00) — 날짜 경계는 UTC 기준(저장 시각과 같은 기준)."""
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start.replace(hour=23, minute=59, second=59, microsecond=999999)


def no_change_count_today(session, source_product_id, now=None) -> int:
    """오늘 이 URL 을 **안 바뀐 채로** 몇 번 남겼나.

    한 번의 크롤 = 한 captured_at (옵션마다 1행이라 행 수로 세면 안 된다).
    """
    from sqlalchemy import distinct, func

    from lemouton.sources.models import SourcePriceHistory as H
    now = now or _utcnow()
    lo, hi = _day_bounds(now)
    return (session.query(func.count(distinct(H.captured_at)))
            .filter(H.source_product_id == source_product_id,
                    H.changed.is_(False),
                    H.captured_at >= lo, H.captured_at <= hi).scalar() or 0)


def record(session, *, source_product, snapshot, changed: bool, now=None) -> int:
    """이력 한 번분을 남긴다 — 남긴 행 수(0 이면 오늘 한도를 채워 건너뜀).

    Args:
        source_product: SourceProduct (id·site 를 읽는다)
        snapshot: [{'color_text','size_text','price','stock'}] — **실제로 저장되는 값**
            (`service._record_crawl_delta` 가 만든 new_snapshot 을 그대로 받는다.
             들어온 raw 가 아니라 DB 에 남는 값이어야 그래프가 화면과 맞는다.)
        changed: 이번 크롤에서 가격이나 재고가 바뀌었나

    ★ 값이 하나도 없는 크롤(전부 price·stock None)은 남기지 않는다 — 빈 점이
      그래프에 찍히면 「그날 0원이었다」로 읽힌다.
    """
    from lemouton.sources.models import SourcePriceHistory as H

    rows = [r for r in (snapshot or [])
            if r.get('price') is not None or r.get('stock') is not None]
    if not rows:
        return 0

    now = now or _utcnow()
    if not changed and no_change_count_today(session, source_product.id, now) \
            >= DAILY_NO_CHANGE_CAP:
        return 0

    site = getattr(source_product, 'site', '') or ''
    for r in rows:
        session.add(H(source_product_id=source_product.id, site=site,
                      color_text=(r.get('color_text') or '')[:64],
                      size_text=(r.get('size_text') or '')[:32],
                      captured_at=now,
                      surface_price=r.get('price'), stock=r.get('stock'),
                      changed=bool(changed)))
    return len(rows)


def series_for(session, *, source_product_ids, color=None, size=None, days=30,
               now=None) -> list[dict]:
    """그래프용 점들 — [{site, captured_at, surface_price, stock, changed}].

    소싱처별로 선을 나눠 그릴 수 있게 site 를 함께 준다(노션 「여러 소싱처면 소싱처별」).
    옵션(색상·사이즈)을 주면 그 옵션만, 안 주면 그 URL 전체.
    """
    from datetime import timedelta

    from lemouton.sources.models import SourcePriceHistory as H
    ids = [i for i in (source_product_ids or []) if i]
    if not ids:
        return []
    now = now or _utcnow()
    q = (session.query(H)
         .filter(H.source_product_id.in_(ids),
                 H.captured_at >= now - timedelta(days=max(1, int(days or 30)))))
    if color:
        q = q.filter(H.color_text == color)
    if size:
        q = q.filter(H.size_text == size)
    return [{'site': h.site, 'captured_at': h.captured_at.isoformat(),
             'surface_price': h.surface_price, 'stock': h.stock,
             'changed': bool(h.changed)}
            for h in q.order_by(H.captured_at.asc()).all()]
