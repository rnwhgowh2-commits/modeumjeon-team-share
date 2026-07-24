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
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .status import unify_status

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
    brand: Optional[str] = None
    site_product_id: Optional[str] = None
    registered_at: Optional[datetime] = None


@dataclass
class CatalogPage:
    """한 페이지 결과.

    total     : 마켓이 알려준 전체 건수. **안 주면 None**(0 아님 — 0 은 '없다'는 뜻).
    next_token: 쿠팡처럼 다음 페이지 열쇠를 주는 마켓만.
    """
    rows: list = field(default_factory=list)
    total: Optional[int] = None
    next_token: Optional[str] = None


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
    rows = []
    for it in (data.get('items') or []):
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
        rows.append(CatalogRow(
            market_product_id=str(gno),
            site_product_id=(str(site_no) if site_no else None),
            name=_text(it.get('goodsName') or it.get('goodsNm')),
            raw_status=(str(raw) if raw is not None else None),
            status=unify_status(market, raw),
            sale_price=_int(_site_val(it.get('price'), site_key)),
            brand=_text(brand.get('name') if isinstance(brand, dict) else brand),
        ))
    return CatalogPage(rows=rows, total=_int(data.get('totalItems')))


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
                brand=_text(cp.get('brandName')),
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
