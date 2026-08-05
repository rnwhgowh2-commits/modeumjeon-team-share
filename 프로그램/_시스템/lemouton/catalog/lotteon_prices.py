# -*- coding: utf-8 -*-
"""롯데온 판매가 채우기 — 목록엔 가격이 아예 없다(2026-08-06 프로브 실측).

실측 근거 (probe run 31024768904 · 라이브 응답 그대로):
  · 목록(product/list): spdNo·spdNm·slStatCd·승인상태뿐 — 가격·배송비 필드 0개.
  · 상세(product/detail, 이미 옵션 매칭에서 라이브 사용 중):
      data.itmLst[].slPrc = 옵션 판매가 → 상품 줄엔 **최저값**.
  · 배송비: 상세엔 정책번호(dvCstPolNo)만 있고 금액이 없다 → NULL 유지(날조 금지).
  · 노출가(할인 적용가): 실측 못 함 → NULL 유지. 마켓별 실측 후 하나씩.

쿠팡(coupang_coupon.enrich_prices)과 같은 규약 —
  빈 것(sale_price NULL) 먼저 + 남는 자리는 오래된 것 재확인(진짜 누적),
  50건마다 중간 커밋(도중에 죽어도 그만큼 생존), 상한 걸리면 로그로 말함.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def enrich_prices(session, client, *, account_key: str,
                  limit: int | None = None) -> dict:
    """그 계정의 롯데온 캐시 상품에 판매가(옵션 최저)를 채운다."""
    from shared.platforms.lotteon.products import get_product_detail
    from .models import MarketProduct

    if limit is None:
        try:
            limit = int(os.environ.get('MOUM_LOTTEON_PRICE_LIMIT') or '500')
        except ValueError:
            limit = 500

    base = (session.query(MarketProduct)
            .filter_by(market='lotteon', account_key=account_key)
            .filter(MarketProduct.deleted_at.is_(None)))
    total_rows = base.count()
    rows = (base.filter(MarketProduct.sale_price.is_(None))
            .order_by(MarketProduct.id.desc()).limit(limit).all())
    if len(rows) < limit:
        rows += (base.filter(MarketProduct.sale_price.isnot(None))
                 .order_by(MarketProduct.id.asc())
                 .limit(limit - len(rows)).all())
    truncated = total_rows > limit
    if truncated:
        logger.warning('[롯데온가격] %s 상품 %d개 중 %d개만 가격을 채움 '
                       '(MOUM_LOTTEON_PRICE_LIMIT) — 나머지는 다음 훑기에',
                       account_key, total_rows, limit)

    filled = failed = 0
    for m in rows:
        try:
            detail = get_product_detail(m.market_product_id, client=client)
        except Exception as e:                          # noqa: BLE001
            failed += 1
            logger.warning('[롯데온가격] 상세 실패 %s: %s',
                           m.market_product_id, str(e)[:120])
            continue
        sales = [it.get('slPrc') for it in (detail.get('itmLst') or [])
                 if isinstance(it.get('slPrc'), (int, float))]
        if not sales:
            continue                                    # 값 없으면 NULL 유지(날조 금지)
        m.sale_price = int(min(sales))
        filled += 1
        if filled % 50 == 0:
            session.commit()
    session.commit()
    return {'filled': filled, 'failed': failed,
            'truncated': truncated, 'total_rows': total_rows}
