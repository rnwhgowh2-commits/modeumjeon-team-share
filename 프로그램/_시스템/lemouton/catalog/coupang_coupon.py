# -*- coding: utf-8 -*-
"""쿠팡 고객 노출가 = 옵션 판매가 − 즉시할인쿠폰 (사장님 확정 「쿠폰적용가」).

실측 근거 (2026-08-05 · 읽기 전용 프로브 run 30960940495 — 라이브 응답 그대로):
  · 쿠폰:  {couponId, status:'APPLIED', type:'PRICE', discount:1400.0, …}
    — type='PRICE' = **정액(원)**. 다른 type 은 실측에서 안 나왔다 →
    🔴 모르는 type 은 계산하지 않고 로그만 남긴다(추측 = 날조).
  · 대상:  쿠폰마다 items[] = {vendorItemId, status:'APPLIED', …}
    — 쿠폰은 상품이 아니라 **옵션(vendorItemId) 단위**로 붙는다.
  · 목록 훑기(seller-products)엔 가격이 아예 없다 → 상품 상세(get_product)의
    items[].salePrice / items[].vendorItemId 로 옵션별 판매가를 얻는다(지도 확인).

상품 한 줄에 담는 값:
  sale_price    = 옵션 판매가의 **최저** (여태 쿠팡은 이 값도 비어 있었다)
  exposed_price = (옵션 판매가 − 그 옵션 쿠폰 정액할인) 의 **최저**
  쿠폰 없는 옵션의 노출가 = 판매가 그대로(그게 고객이 보는 값 — 날조 아님).
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

#: 쿠폰/아이템 페이지 크기·상한. 실측 계정은 쿠폰 0~1개였지만 상한 없이 돌리지 않는다.
_PAGE_SIZE = 50
_MAX_COUPON_PAGES = 10
_MAX_ITEM_PAGES = 40


def _content(resp) -> list:
    """실측 응답 꼴: {code, data:{content:[…]}, …} — 방어적으로 꺼낸다."""
    if not isinstance(resp, dict):
        return []
    data = resp.get('data')
    if isinstance(data, dict) and isinstance(data.get('content'), list):
        return data['content']
    if isinstance(resp.get('content'), list):
        return resp['content']
    return []


def fetch_coupon_discounts(client, vendor_id: str) -> dict[str, int]:
    """적용 중(APPLIED) 즉시할인쿠폰 → {vendorItemId(str): 정액할인(원)}.

    한 옵션에 쿠폰이 여러 개면 **큰 할인 하나**만 쓴다 — 겹침 규칙은 실측 못 했고,
    작게 잡는 쪽이 노출가를 낮게 즉 고객에게 보이는 값보다 싸게 만들 위험이 없다.
    """
    out: dict[str, int] = {}
    for page in range(1, _MAX_COUPON_PAGES + 1):
        resp = client.request(
            'GET',
            f'/v2/providers/fms/apis/api/v2/vendors/{vendor_id}/coupons',
            query=f'status=APPLIED&page={page}&size={_PAGE_SIZE}&sort=desc')
        coupons = _content(resp)
        if not coupons:
            break
        for c in coupons:
            ctype = c.get('type')
            disc = c.get('discount')
            cid = c.get('couponId')
            if ctype != 'PRICE' or not isinstance(disc, (int, float)) or cid is None:
                # 실측에 없던 모양 — 계산에 넣지 않고 크게 남긴다(조용한 날조 금지).
                logger.warning('[쿠팡쿠폰] 모르는 쿠폰 모양이라 건너뜀: '
                               'couponId=%s type=%r discount=%r', cid, ctype, disc)
                continue
            for ip in range(1, _MAX_ITEM_PAGES + 1):
                r2 = client.request(
                    'GET',
                    f'/v2/providers/fms/apis/api/v1/vendors/{vendor_id}'
                    f'/coupons/{cid}/items',
                    query=f'status=APPLIED&page={ip}&size={_PAGE_SIZE}&sort=desc')
                items = _content(r2)
                if not items:
                    break
            # ↑ break 는 빈 페이지에서만 — 아래에서 채운다
                for it in items:
                    vid = it.get('vendorItemId')
                    if vid is None:
                        continue
                    key = str(vid)
                    out[key] = max(out[key], int(disc)) if key in out else int(disc)
        if len(coupons) < _PAGE_SIZE:
            break
    return out


def enrich_prices(session, client, *, account_key: str, vendor_id: str,
                  limit: int | None = None) -> dict:
    """그 계정의 캐시 상품에 판매가·쿠폰적용 노출가를 채운다.

    상품마다 상세 1회 호출이라 상한을 둔다(기본 500 · MOUM_COUPANG_PRICE_LIMIT).
    🔴 상한에 걸리면 **로그로 말한다** — 조용한 절반 채움은 「다 됐다」로 읽힌다.
    """
    from shared.platforms.coupang.products import get_product
    from .models import MarketProduct

    if limit is None:
        try:
            limit = int(os.environ.get('MOUM_COUPANG_PRICE_LIMIT') or '500')
        except ValueError:
            limit = 500

    discounts = fetch_coupon_discounts(client, vendor_id)
    base = (session.query(MarketProduct)
            .filter_by(market='coupang', account_key=account_key)
            .filter(MarketProduct.deleted_at.is_(None)))
    total_rows = base.count()
    # 🔴 아직 없는 것 먼저 — 최신순으로만 뽑으면 밤마다 **같은 500개**만 다시 채우고
    #   나머지는 영영 안 채워진다(누적이 안 되는 실결함). 빈 것부터 채우고,
    #   자리가 남으면 오래 전에 채운 것부터 다시 확인한다(가격 갱신).
    rows = (base.filter(MarketProduct.sale_price.is_(None))
            .order_by(MarketProduct.id.desc()).limit(limit).all())
    if len(rows) < limit:
        rows += (base.filter(MarketProduct.sale_price.isnot(None))
                 .order_by(MarketProduct.id.asc())
                 .limit(limit - len(rows)).all())
    truncated = total_rows > limit
    if truncated:
        logger.warning('[쿠팡쿠폰] %s 상품 %d개 중 %d개만 가격을 채움 '
                       '(MOUM_COUPANG_PRICE_LIMIT) — 나머지는 다음 훑기에',
                       account_key, total_rows, limit)

    filled = failed = couponed = 0
    for m in rows:
        try:
            detail = get_product(m.market_product_id, client=client)
        except Exception as e:                          # noqa: BLE001
            failed += 1
            logger.warning('[쿠팡쿠폰] 상세 실패 %s: %s',
                           m.market_product_id, str(e)[:120])
            continue
        # ⚠️ 상세는 **두 모양**이다(2026-08-06 프로브 실측 · registrationType 따라 다름):
        #   신형 = items[].salePrice/vendorItemId 최상위 + 최상위 deliveryCharge
        #   구형 = items[].marketplaceItemData.priceData.salePrice 중첩
        #         + marketplaceShippingAndReturnInfo.deliveryCharge
        #   신형만 읽던 탓에 세소쿠팡 63개 중 60개가 통째로 NULL 이었다.
        sales, exposed = [], []
        for it in (detail.get('items') or []):
            mp = it.get('marketplaceItemData') or {}
            sp = it.get('salePrice')
            if not isinstance(sp, (int, float)):
                sp = (mp.get('priceData') or {}).get('salePrice')
            if not isinstance(sp, (int, float)):
                continue
            sales.append(int(sp))
            vid = it.get('vendorItemId') or mp.get('vendorItemId')
            disc = discounts.get(str(vid))
            if disc:
                couponed += 1
                # 정액이 판매가보다 큰 이상값은 0 으로 두지 않고 그대로 뺀 뒤 바닥 0
                exposed.append(max(int(sp) - disc, 0))
            else:
                exposed.append(int(sp))
        # 기본 배송비 — 신형 최상위, 구형은 배송 묶음 안. 없으면 NULL 유지.
        dc = detail.get('deliveryCharge')
        if not isinstance(dc, (int, float)):
            dc = (detail.get('marketplaceShippingAndReturnInfo') or {}) \
                .get('deliveryCharge')
        if isinstance(dc, (int, float)):
            m.delivery_fee = int(dc)
        if not sales:
            continue                                    # 값 없으면 NULL 유지(날조 금지)
        m.sale_price = min(sales)
        m.exposed_price = min(exposed)
        filled += 1
        # 🔴 여기서 직접 커밋한다 — 밖(수동 스크립트·야간 훑기)엔 커밋이 없어서
        #   안 하면 마지막 계정 몫이 세션 닫힐 때 통째로 증발한다(실사고:
        #   2026-08-05 훑기가 137(메모리 죽음)로 끊겨 3계정 몫 전부 유실).
        #   50건마다 중간 커밋 → 도중에 죽어도 그만큼은 살아남는다.
        if filled % 50 == 0:
            session.commit()
    session.commit()
    return {'accounts_coupons': len(discounts), 'filled': filled,
            'failed': failed, 'couponed_items': couponed,
            'truncated': truncated, 'total_rows': total_rows}
