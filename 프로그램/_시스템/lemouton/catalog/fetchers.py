# -*- coding: utf-8 -*-
"""마켓별 상품 목록 페이징 — 6마켓의 차이를 여기 한 곳에 가둔다.

바깥(sync·repository·화면)은 CatalogRow 만 본다.

실측 근거(2026-07-23 · GitHub Actions 「상품관리 실측(수동)」 script=1/2/3):
    마켓          총건수필드        페이지크기   상품명검색
    스마트스토어   totalElements    100         ✗ (후보 16종 전부 실패)
    롯데온        dataCount        100(상한)    ✗ (파라미터 없음)
    옥션·G마켓     totalItems       500(상한)    ✓ query.keyword
    쿠팡          없음(nextToken)   100(상한)    ✓ sellerProductName
    11번가        없음(start/end)   100         ✓ prdNm

검색이 안 되는 마켓이 있어서 **머리글 캐시는 선택이 아니라 필수**다.
"""
from __future__ import annotations

import html
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .status import unify_status

logger = logging.getLogger(__name__)

#: 마켓별 한 번에 가져올 건수. 마켓 문서 상한을 넘기면 거부되거나 잘린다.
PAGE_SIZE = {
    'smartstore': 100, 'lotteon': 100, 'coupang': 100, 'eleven11': 100,
    'auction': 500, 'gmarket': 500,
}


@dataclass
class CatalogRow:
    """마켓 상품 1건의 머리글 — 마켓이 달라도 모양이 같다."""
    market_product_id: str
    name: Optional[str]
    status: str
    raw_status: Optional[str] = None
    sale_price: Optional[int] = None
    #: 고객 표면노출가(할인 적용가). 주는 마켓만(지금은 스스 discountedPrice).
    exposed_price: Optional[int] = None
    #: 기본 배송비. 주는 마켓만(지금은 스스 deliveryFee). 없으면 None — 0 은 무료란 뜻.
    delivery_fee: Optional[int] = None
    #: 마켓에 **실제로 등록된** 카테고리. 주는 마켓만(롯데온은 목록에 아예 없다).
    #: 이름을 안 주는 마켓(쿠팡·11번가)은 code 만 채운다 — 이름을 지어내지 않는다.
    category_code: Optional[str] = None
    category_name: Optional[str] = None
    brand: Optional[str] = None
    site_product_id: Optional[str] = None
    registered_at: Optional[datetime] = None


@dataclass
class CatalogPage:
    """한 페이지 결과.

    total     : 마켓이 알려준 전체 건수. **안 주면 None**(0 아님 — 0 은 '없다'는 뜻).
    next_token: 쿠팡처럼 다음 페이지 열쇠를 주는 마켓만.
    raw_count : ★ 마켓이 이 페이지에 **준** 건수(거르기 전). rows 는 거른 뒤라 더 적을 수 있다.
                ESM 은 그 사이트에 없는 상품이 섞여 오므로 한 페이지가 통째로 걸러질 수 있는데,
                rows 가 비었다고 「마지막 페이지」로 보면 나머지를 통째로 잃는다(조용한 손실).
                안 주는 마켓은 None — 그때는 예전처럼 rows 개수로 판단한다.
    """
    rows: list = field(default_factory=list)
    total: Optional[int] = None
    next_token: Optional[str] = None
    raw_count: Optional[int] = None


def _int(v) -> Optional[int]:
    """숫자로 못 바꾸면 None — 0 으로 떨어뜨리지 않는다.

    ★ ESM 가격은 70600.0 처럼 소수점으로 온다 — float 를 거쳐야 한다.
    """
    try:
        return int(float(str(v).strip()))
    except (TypeError, ValueError):
        return None


def _text(v) -> Optional[str]:
    """HTML 이스케이프를 푼 문자열. ★ 롯데온이 &lt;매장정품&gt; 으로 준다."""
    if v is None:
        return None
    return html.unescape(str(v)).strip() or None


def _code(v) -> Optional[str]:
    """카테고리 코드 — 숫자로 와도 문자열로. 0·빈값은 None(코드로 못 쓴다).

    🔴 `str(v)` 만 하면 None 이 '"None"' 이라는 **가짜 코드**가 되어 화면에 뜬다.
    """
    if v is None:
        return None
    s = str(v).strip()
    if not s or s in ('0', 'None', 'null'):
        return None
    return s[:64]


# ── 마켓별 ────────────────────────────────────────────────────

def _lotteon(client, page_index, **kw) -> CatalogPage:
    from datetime import timedelta

    from shared.platforms import LOTTEON
    cfg = getattr(client, '_cfg', None) or LOTTEON
    now = datetime.now()
    body = {
        'trGrpCd': cfg.get('tr_grp_cd', 'SR'), 'trNo': cfg.get('tr_no', ''),
        'regStrtDttm': (now - timedelta(days=int(kw.get('days', 3650)))
                        ).strftime('%Y%m%d%H%M%S'),
        'regEndDttm': now.strftime('%Y%m%d%H%M%S'),
        # ★ 둘 다 필수 — 빼면 returnCode 9000('처리 중 오류'). 권한 문제로 오해하기 쉽다.
        'pageNo': int(page_index), 'rowsPerPage': PAGE_SIZE['lotteon'],
    }
    resp = client.request(method='POST', path=cfg['paths']['list'], body=body)
    if str(resp.get('returnCode')) not in ('0000', 'SUCCESS'):
        raise ValueError(f"롯데온 목록 실패 returnCode={resp.get('returnCode')} "
                         f"message={resp.get('message')}")
    data = resp.get('data')
    raw = data if isinstance(data, list) else (
        next((v for v in (data or {}).values() if isinstance(v, list)), []))
    # 🔴 카테고리는 **롯데온이 목록에서 안 준다** — 응답 필드가 spdNo·spdNm·slStatCd·
    #   승인상태뿐이다(지도 lotteon.product.list idTraps · 2026-08-06 프로브 실측
    #   run 31024768904, 가격·배송비도 0개). 그래서 category_code 를 채우지 않는다.
    #   화면은 이 사실을 「롯데온은 카테고리를 안 알려줘요」로 그대로 말한다(날조 금지).
    rows = [CatalogRow(
        market_product_id=str(d.get('spdNo') or ''),
        name=_text(d.get('spdNm')),
        raw_status=d.get('slStatCd'),
        status=unify_status('lotteon', d.get('slStatCd')),
    ) for d in raw if d.get('spdNo')]
    return CatalogPage(rows=rows, total=_int(resp.get('dataCount')))


def _site_val(v, site_key):
    """ESM 값은 사이트별 묶음으로 온다 — 그 사이트 값만 꺼낸다.

    ★ [2026-07-24 라이브 실측] 실제 응답:
        sellStatus = {'gmkt': None, 'iac': '22'}
        price      = {'gmkt': 0.0,  'iac': 70600.0}
        siteGoodsNo= {'gmkt': None, 'iac': 'F292819719'}
      통째로 문자열화했더니 1,605건이 전부 상태 unknown 으로 저장됐다.
      묶음이 아닌 평평한 값으로 와도 안 깨지게 그대로 돌려준다.
    """
    if isinstance(v, dict):
        return v.get(site_key)
    return v


def _esm(market, client, page_index, **kw) -> CatalogPage:
    from shared.platforms import AUCTION, GMARKET
    cfg = AUCTION if market == 'auction' else GMARKET
    site_key = 'iac' if market == 'auction' else 'gmkt'
    body = {
        'pageIndex': int(page_index), 'pageSize': PAGE_SIZE[market],
        # ★ 조건은 반드시 query 안에. 밖에 두면 ESM 이 에러 없이 버리고 전체를 준다.
        'query': {'siteId': [1 if market == 'auction' else 2]},
    }
    resp = client.request(method='POST', path=cfg['paths']['search'], body=body)
    data = resp.get('data') if isinstance(resp, dict) and 'data' in resp else resp
    if not isinstance(data, dict):
        data = {}
    items = data.get('items') or []
    rows = []
    for it in items:
        gno = it.get('goodsNo')
        if not gno:
            continue
        site_no = _site_val(it.get('siteGoodsNo'), site_key)
        raw = _site_val(it.get('sellStatus'), site_key)
        # ★ 이 사이트에 없는 상품(둘 다 비었음)은 건너뛴다 — 넣으면 건수가 부푼다.
        #   옥션·G마켓은 마스터가 공용이라 한쪽에만 있는 상품이 섞여 온다.
        if site_no is None and raw is None:
            continue
        brand = it.get('brand')
        price = _int(_site_val(it.get('price'), site_key))
        # 노출가 = 판매가 − 판매자할인. [2026-08-06 실측] sellerDiscount 가 사이트별
        #   {type, discountAmt} 로 온다 — type 0:사용안함 1:정액 2:정률(지도 esm.20).
        #   🔴 정률(2)은 discountAmt 단위(원/%)를 실측 못 해 계산 안 함(추측=날조).
        exposed = None
        sd = _site_val(it.get('sellerDiscount'), site_key)
        sd = sd if isinstance(sd, dict) else {}
        sd_type, sd_amt = sd.get('type'), sd.get('discountAmt')
        if price is not None:
            if not sd_type or not sd_amt:
                exposed = price                      # 할인 없음 = 고객가 그대로
            elif sd_type == 1 and isinstance(sd_amt, (int, float)):
                exposed = max(price - int(sd_amt), 0)
            else:
                logger.warning('[catalog] ESM %s 미실측 할인타입 type=%r amt=%r '
                               '— 노출가 비움', gno, sd_type, sd_amt)
        # 배송비 — shipping.fee (사이트 공용, 0=무료. 실측 확인)
        ship = it.get('shipping')
        fee = ship.get('fee') if isinstance(ship, dict) else None
        # 카테고리 — 지도 esm.160 응답: category.site.{iac|gmkt}.{catCode,catName}
        #   + 사이트 공용 category.esm.{catCode,catName}.
        #   🔴 사이트별 값이 먼저다(옥션·G마켓 카테고리 체계가 다르다). 없을 때만 esm 공용.
        cat = it.get('category')
        cat = cat if isinstance(cat, dict) else {}
        c_site = _site_val(cat.get('site'), site_key)
        c_site = c_site if isinstance(c_site, dict) else {}
        c_esm = cat.get('esm') if isinstance(cat.get('esm'), dict) else {}
        cat_code = _code(c_site.get('catCode')) or _code(c_esm.get('catCode'))
        cat_name = _text(c_site.get('catName')) or _text(c_esm.get('catName'))
        rows.append(CatalogRow(
            market_product_id=str(gno),
            site_product_id=(str(site_no) if site_no else None),
            name=_text(it.get('goodsName') or it.get('goodsNm')),
            raw_status=(str(raw) if raw is not None else None),
            status=unify_status(market, raw),
            sale_price=price,
            exposed_price=exposed,
            delivery_fee=(int(fee) if isinstance(fee, (int, float)) else None),
            category_code=cat_code, category_name=cat_name,
            brand=_text(brand.get('name') if isinstance(brand, dict) else brand),
        ))
    # ★ 거르기 전 건수를 함께 넘긴다 — 통째로 걸러진 페이지를 마지막으로 오해하지 않게.
    return CatalogPage(rows=rows, total=_int(data.get('totalItems')),
                       raw_count=len(items))


def _smartstore(client, page_index, **kw) -> CatalogPage:
    resp = client.request('POST', '/external/v1/products/search',
                          body={'page': int(page_index),
                                'size': PAGE_SIZE['smartstore']})
    rows = []
    for item in (resp.get('contents') or []):
        for cp in (item.get('channelProducts') or []):
            # 사장님이 셀러센터에서 보는 번호 = channelProductNo
            cpn = cp.get('channelProductNo')
            if not cpn:
                continue
            rows.append(CatalogRow(
                market_product_id=str(cpn),
                name=_text(cp.get('name')),
                raw_status=cp.get('statusType'),
                status=unify_status('smartstore', cp.get('statusType')),
                sale_price=_int(cp.get('salePrice')),
                # 고객이 실제로 보는 값 — 같은 응답이 주는데 버리고 있었다(사장님 요청 2026-08-04)
                exposed_price=_int(cp.get('discountedPrice')),
                # 기본 배송비 — 같은 부류(받으면서 버리던 값 · 사장님 요청 2026-08-05)
                delivery_fee=_int(cp.get('deliveryFee')),
                # 카테고리 — 지도 smartstore.search-product 응답의 categoryId(잎)와
                #   wholeCategoryName(전체 경로명). idTraps 가 「leafCategoryId 와 같은
                #   부류 = 받아오면서 버리던 값」이라고 못 박아 둔 그 값이다.
                category_code=_code(cp.get('categoryId')
                                    or cp.get('leafCategoryId')),
                category_name=_text(cp.get('wholeCategoryName')),
            ))
    return CatalogPage(rows=rows, total=_int(resp.get('totalElements')))


def _coupang(client, page_index, *, vendor_id=None, next_token=None,
             **kw) -> CatalogPage:
    vid = vendor_id or getattr(client, 'vendor_id', None) or \
        getattr(client, '_cfg', {}).get('vendor_id')
    q = f"vendorId={vid}&maxPerPage={PAGE_SIZE['coupang']}"
    if next_token:
        q += f"&nextToken={next_token}"
    resp = client.request(
        'GET',
        '/v2/providers/seller_api/apis/api/v1/marketplace/seller-products',
        query=q)
    rows = []
    for d in (resp.get('data') or []):
        pid = d.get('sellerProductId')
        if not pid:
            continue
        raw = d.get('statusName') or d.get('status')
        rows.append(CatalogRow(
            market_product_id=str(pid),
            name=_text(d.get('sellerProductName')),
            raw_status=raw,
            status=unify_status('coupang', raw),
            # 카테고리 — 지도 coupang.products.product-list-paging-query 응답 예시가
            #   displayCategoryCode(전시 카테고리 = 등록에 쓰는 코드)를 준다.
            #   🔴 이름은 안 준다 → category_name 은 비운다(코드로 이름을 지어내지 않는다).
            category_code=_code(d.get('displayCategoryCode')),
            brand=_text(d.get('brand')),
        ))
    # ★ 총건수 필드가 없다 — None 을 그대로 돌려준다(0 은 '없다'는 뜻이라 쓰면 안 된다).
    return CatalogPage(rows=rows, total=None, next_token=resp.get('nextToken'))


def _eleven11(client, page_index, **kw) -> CatalogPage:
    from shared.platforms.eleven11 import products as P
    size = PAGE_SIZE['eleven11']
    start = (int(page_index) - 1) * size + 1
    raw = P.search_products(client=client, limit=size,
                            start=start, end=start + size - 1)
    rows = []
    for d in (raw or []):
        pid = d.get('prdNo')
        if not pid:
            continue
        rows.append(CatalogRow(
            market_product_id=str(pid),
            name=_text(d.get('prdNm')),
            raw_status=(str(d.get('selStatCd'))
                        if d.get('selStatCd') is not None else None),
            status=unify_status('eleven11', d.get('selStatCd')),
            sale_price=_int(d.get('selPrc')),
            # 카테고리 — 지도 eleven11.39(다중 상품 조회) 응답의 dispCtgrNo.
            #   🔴 이 행의 prdNo 로 만든 줄에만 넣는다(같은 응답 같은 행이라 섞일 수 없다).
            #     남의 행 값을 끌어오면 「confidence 0.99 로 남의 카테고리」 사고가 난다
            #     (지도 eleven11.39 idTraps 2026-07-23 리뷰 C2).
            #   🔴 rootCtgrNo 는 「무시해도 되는 11번가 시스템 코드」라 쓰지 않는다.
            category_code=_code(d.get('dispCtgrNo')),
        ))
    return CatalogPage(rows=rows, total=None)


_FETCHERS = {
    'lotteon': _lotteon,
    'smartstore': _smartstore,
    'coupang': _coupang,
    'eleven11': _eleven11,
    'auction': lambda c, p, **kw: _esm('auction', c, p, **kw),
    'gmarket': lambda c, p, **kw: _esm('gmarket', c, p, **kw),
}


def fetch_page(market: str, client, page_index: int, **kw) -> CatalogPage:
    """마켓 상품 목록 한 페이지. 마켓을 모르면 바로 알려준다(조용한 빈 결과 금지)."""
    fn = _FETCHERS.get((market or '').strip().lower())
    if fn is None:
        raise ValueError(f"모르는 마켓입니다: {market!r}")
    return fn(client, page_index, **kw)
