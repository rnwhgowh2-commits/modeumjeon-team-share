# -*- coding: utf-8 -*-
"""쿠팡 물류 조회 — 반품지·출고지 목록 (계정정보 9키 자동 수확용).

이 모듈이 있는 이유: 등록 payload 의 vendor 9키 중 7개를 사장님이 손으로 적지 않게
한다. 쿠팡이 조회 API 를 주므로, 「불러오기」 한 번이면 Wing 에 등록해 둔 값 그대로
가져온다 — 손으로 옮겨 적다 오타 난 반품지 주소로 등록되는 사고를 없앤다.

데이터 코드 지도 근거 (webapp/data/marketplace_api_map.json · 전수정독 게이트 통과):
  · coupang.logistics.query-a-list-of-return-locations  (st=code)
      GET /v2/providers/openapi/apis/api/v5/vendors/{vendorId}/returnShippingCenters
      → data.content[]: returnCenterCode, shippingPlaceName, usable,
        placeAddresses[]: returnZipCode, returnAddress, returnAddressDetail,
                          companyContactNumber
  · coupang.logistics.query-a-shipping-location         (st=code)
      GET /v2/providers/marketplace_openapi/apis/api/v2/vendor/shipping-place/outbound
      → content[]: outboundShippingPlaceCode, shippingPlaceName, usable
      ⚠ 400 「(pageNum & pageSize) or placeCodes or placeNames must be provided」 —
        목록 조회는 pageNum·pageSize 를 **반드시** 같이 보내야 한다.

⚠ 지도의 함정 하나: 반품지 목록 항목의 `example_endpoint` 는 호스트 뒤가 `/v5/providers/…`
  로 적혀 있는데 `path` 는 `/v2/providers/…` 다(쿠팡 문서 자체의 불일치). 서명은 path 로
  만들어지므로 **path 를 정본으로** 쓴다 — 다른 쿠팡 API 도 전부 `/v2/providers/` 다.

응답 shape 이 두 API 사이에 다르다(반품지는 data.content, 출고지는 최상위 content).
그래서 파서를 공유하지 않고 각각 명시적으로 판다 — 「하나로 합치기」가 곧 버그다.
"""
from __future__ import annotations

import logging
from typing import Optional

from shared.platforms.coupang.client import CoupangClient

logger = logging.getLogger(__name__)

RETURN_CENTERS_PATH = '/v2/providers/openapi/apis/api/v5/vendors/{vendorId}/returnShippingCenters'
OUTBOUND_PLACES_PATH = '/v2/providers/marketplace_openapi/apis/api/v2/vendor/shipping-place/outbound'

#: 쿠팡 문서상 pageSize 최대값 (둘 다 50).
MAX_PAGE_SIZE = 50


def _first_address(row: dict) -> dict:
    """placeAddresses[0] — 없으면 빈 dict.

    비어 오는 계정이 실제로 있다. 그때 0·'미상' 같은 값을 채우면 그 주소로 등록이
    나가버린다 — 빈칸으로 두고 화면이 「비었음」을 보이게 한다(폴백 금지).
    """
    addrs = row.get('placeAddresses')
    if isinstance(addrs, list) and addrs and isinstance(addrs[0], dict):
        return addrs[0]
    return {}


def _s(v) -> str:
    """None 을 'None' 문자열로 만들지 않는 안전 변환."""
    return '' if v is None else str(v)


def list_return_centers(vendor_id: str, *, client: Optional[CoupangClient] = None,
                        page_num: int = 1, page_size: int = MAX_PAGE_SIZE) -> list[dict]:
    """반품지 목록 → 계정정보 6키 후보 목록.

    Returns:
        [{return_center_code, return_charge_name, return_zip, return_address,
          return_address_detail, return_phone, usable}]
        · return_charge_name = shippingPlaceName. 쿠팡이 말하는 반품지'명'(사람이 읽는
          이름)이고 코드가 아니다 — compile_coupang 의 returnChargeName 이 바로 이것.
    """
    client = client or CoupangClient()
    path = RETURN_CENTERS_PATH.format(vendorId=vendor_id)
    query = f'pageNum={int(page_num)}&pageSize={int(page_size)}'
    resp = client.request(method='GET', path=path, query=query)

    data = resp.get('data') or {}
    content = data.get('content') if isinstance(data, dict) else None
    if not isinstance(content, list):
        # data 가 배열로 오는 변형(단건 조회 shape)도 받아 준다.
        content = data if isinstance(data, list) else []

    rows = []
    for r in content:
        if not isinstance(r, dict):
            continue
        a = _first_address(r)
        rows.append({
            'return_center_code': _s(r.get('returnCenterCode')),
            'return_charge_name': _s(r.get('shippingPlaceName')),
            'return_zip': _s(a.get('returnZipCode')),
            'return_address': _s(a.get('returnAddress')),
            'return_address_detail': _s(a.get('returnAddressDetail')),
            'return_phone': _s(a.get('companyContactNumber')),
            # usable=False 인 옛 반품지도 숨기지 않고 구분만 한다 — 안 보이면
            # 「내 반품지가 왜 없지?」로 헤맨다.
            'usable': bool(r.get('usable', True)),
        })
    return rows


def list_outbound_places(*, client: Optional[CoupangClient] = None,
                         page_num: int = 1, page_size: int = MAX_PAGE_SIZE) -> list[dict]:
    """출고지 목록 → outboundShippingPlaceCode 후보.

    Returns:
        [{outbound_place_code, name, usable}]
    """
    client = client or CoupangClient()
    query = f'pageNum={int(page_num)}&pageSize={int(page_size)}'
    resp = client.request(method='GET', path=OUTBOUND_PLACES_PATH, query=query)

    # 이 API 는 content 를 최상위에 준다(반품지와 다르다). data 로 감싸 오는 변형도 대비.
    content = resp.get('content')
    if not isinstance(content, list):
        data = resp.get('data') or {}
        content = data.get('content') if isinstance(data, dict) else None
    if not isinstance(content, list):
        content = []

    return [{
        'outbound_place_code': _s(r.get('outboundShippingPlaceCode')),
        'name': _s(r.get('shippingPlaceName')),
        'usable': bool(r.get('usable', True)),
    } for r in content if isinstance(r, dict)]
