# -*- coding: utf-8 -*-
"""롯데온 판매가 **+ 카테고리** 채우기 — 목록엔 둘 다 아예 없다(2026-08-06 프로브 실측).

실측 근거 (probe run 31024768904 · 라이브 응답 그대로):
  · 목록(product/list): spdNo·spdNm·slStatCd·승인상태뿐 — 가격·배송비·카테고리 0개.
  · 상세(product/detail, 이미 옵션 매칭에서 라이브 사용 중):
      data.itmLst[].slPrc = 옵션 판매가 → 상품 줄엔 **최저값**.
      data.scatNo = 표준카테고리번호 · data.dcatLst = 전시카테고리 목록.
  · 배송비: 상세엔 정책번호(dvCstPolNo)만 있고 금액이 없다 → NULL 유지(날조 금지).
  · 노출가(할인 적용가): 실측 못 함 → NULL 유지. 마켓별 실측 후 하나씩.

[2026-08-12] **카테고리를 같은 상세 응답에서 같이 거둔다** — 호출 수가 늘지 않는다.
  근거: `shared/platforms/lotteon/products.py::_REGISTER_TEMPLATE_FIELDS` 가 상세의
  `scatNo`·`dcatLst` 를 그대로 복사해 상품을 등록하고 **라이브에서 성공했다**
  (2026-07-21 LO2729045338·LO2729068316). 즉 그 두 필드는 상세에 실제로 온다.
  🔴 예전엔 「롯데온은 카테고리를 영영 못 받는다」로 화면이 말했는데, 그건 **목록**
    이야기였다. 오는 값을 우리가 안 받고 있었을 뿐이다(메모리:
    「마켓이 그 필드를 안 준다고 말하기 전에 raw 를 봐라」와 같은 부류).

쿠팡(coupang_coupon.enrich_prices)과 같은 규약 —
  빈 것 먼저 + 남는 자리는 오래된 것 재확인(진짜 누적),
  50건마다 중간 커밋(도중에 죽어도 그만큼 생존), 상한 걸리면 로그로 말함.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

#: 전시카테고리 항목에서 **이름**을 담을 수 있는 키들. 하나도 없으면 이름은 NULL 로 둔다
#: (코드만 받은 마켓처럼 코드만 보여준다 — 🔴 이름을 지어내지 않는다).
_DCAT_NAME_KEYS = ("dcatNm", "dispCatNm", "catNm", "dcatNmPath", "fullCatNm")
#: 표준카테고리 이름이 상세에 실려 오는 경우의 키(안 오면 NULL).
_SCAT_NAME_KEYS = ("scatNm", "stdCatNm")


def _first_str(d: dict, keys) -> str | None:
    for k in keys:
        v = (d or {}).get(k)
        if v not in (None, "", []):
            s = str(v).strip()
            if s:
                return s[:255]
    return None


def category_of(detail: dict):
    """상세 응답 → (카테고리 코드, 카테고리 이름). 못 구하면 (None, None).

    · 코드는 **표준카테고리번호(scatNo)** — 롯데온 등록이 쓰는 그 번호다.
      없으면 전시카테고리(dcatLst)의 leaf 번호(lfDcatNo)라도 쓴다.
    · 이름은 응답에 실제로 실려 있을 때만. 🔴 번호를 이름처럼 꾸미지 않는다.
    """
    if not isinstance(detail, dict):
        return None, None
    code = detail.get("scatNo")
    code = str(code).strip() if code not in (None, "") else None
    name = _first_str(detail, _SCAT_NAME_KEYS)
    dlst = detail.get("dcatLst")
    if isinstance(dlst, list) and dlst:
        last = dlst[-1] if isinstance(dlst[-1], dict) else None
        if last:
            if not code:
                for k in ("lfDcatNo", "dcatNo", "dispCatNo"):
                    v = last.get(k)
                    if v not in (None, ""):
                        code = str(v).strip()
                        break
            if not name:
                name = _first_str(last, _DCAT_NAME_KEYS)
    if not code:
        code = None
    return (code[:64] if code else None), name


def enrich_prices(session, client, *, account_key: str,
                  limit: int | None = None) -> dict:
    """그 계정의 롯데온 캐시 상품에 판매가(옵션 최저) **+ 카테고리**를 채운다."""
    from sqlalchemy import or_

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
    # 🔴 「빈 것 먼저」의 빈 것은 이제 **가격 또는 카테고리**다 — 가격만 보면
    #   가격이 이미 찬 상품의 카테고리는 영영 차례가 안 온다(재확인 꼬리에서만 걸린다).
    _blank = or_(MarketProduct.sale_price.is_(None),
                 MarketProduct.category_code.is_(None))
    rows = (base.filter(_blank)
            .order_by(MarketProduct.id.desc()).limit(limit).all())
    if len(rows) < limit:
        rows += (base.filter(~_blank)
                 .order_by(MarketProduct.id.asc())
                 .limit(limit - len(rows)).all())
    truncated = total_rows > limit
    if truncated:
        logger.warning('[롯데온가격] %s 상품 %d개 중 %d개만 채움 '
                       '(MOUM_LOTTEON_PRICE_LIMIT) — 나머지는 다음 훑기에',
                       account_key, total_rows, limit)

    filled = failed = cat_filled = 0
    # 🔴 중간 커밋 기준은 **훑은 상품 수**다(바뀐 칸 수가 아니라). 칸 수로 세면 한 상품이
    #   2~3칸을 바꿔 49→51 처럼 건너뛰며 「50마다」가 영영 안 걸릴 수 있다.
    seen = 0
    for m in rows:
        seen += 1
        try:
            detail = get_product_detail(m.market_product_id, client=client)
        except Exception as e:                          # noqa: BLE001
            failed += 1
            logger.warning('[롯데온가격] 상세 실패 %s: %s',
                           m.market_product_id, str(e)[:120])
            continue
        # 🔴 카테고리를 **가격보다 먼저** 쓴다 — 아래 「가격 없으면 continue」에 걸려
        #   같은 응답에 온 카테고리를 통째로 버리던 부류의 버그를 애초에 못 만들게.
        code, name = category_of(detail)
        if code and m.category_code != code:
            m.category_code = code
            cat_filled += 1
        if name and m.category_name != name:
            m.category_name = name
        sales = [it.get('slPrc') for it in (detail.get('itmLst') or [])
                 if isinstance(it.get('slPrc'), (int, float))]
        if sales:
            m.sale_price = int(min(sales))              # 값 없으면 NULL 유지(날조 금지)
            filled += 1
        if seen % 50 == 0:
            session.commit()
    session.commit()
    return {'filled': filled, 'failed': failed, 'category_filled': cat_filled,
            'truncated': truncated, 'total_rows': total_rows}
