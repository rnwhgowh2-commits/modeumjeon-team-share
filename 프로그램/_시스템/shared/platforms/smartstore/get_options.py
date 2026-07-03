# -*- coding: utf-8 -*-
"""
스마트스토어 — 등록 상품의 옵션 정보 조회 API.

GET /external/v2/products/origin-products/{originProductNo}
응답에서 originProduct.detailAttribute.optionInfo.optionCombinations 추출.

각 옵션:
  {
    "id": 56632587351,           # 옵션 ID (= naver_option_id)
    "optionName1": "블랙(블랙아웃솔)",  # 색상명
    "optionName2": "230mm",          # 사이즈명
    "stockQuantity": 5,
    "price": 0,                       # 옵션가 (delta)
    "sellerManagerCode": "",
    "usable": true,
  }
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class OptionRow:
    """단일 옵션 정보 (스스 API 응답)."""
    option_id: int
    name1: Optional[str]   # 보통 색상
    name2: Optional[str]   # 보통 사이즈
    stock: int = 0
    add_price: int = 0     # 옵션가 (delta, 모음전 기본가 대비)
    manager_code: Optional[str] = None
    usable: bool = True

    @property
    def display_name(self) -> str:
        parts = [p for p in (self.name1, self.name2) if p]
        return ' / '.join(parts)


@dataclass
class FetchOptionsResult:
    success: bool
    origin_product_no: Optional[int]
    product_name: Optional[str]
    sale_price: Optional[int]
    options: list[OptionRow]
    raw: Optional[dict] = None
    error: Optional[str] = None
    error_code: Optional[str] = None
    combinations_total: int = 0   # 응답에 있던 옵션 조합 수
    parse_failed: int = 0         # 파싱 실패한 옵션 수 (조용한 실패 표면화 #12)

    @property
    def partial_failure(self) -> bool:
        """일부/전부 옵션 파싱 실패 — success=True 여도 부분수집임을 알림."""
        return self.parse_failed > 0


def fetch_product_options(
    origin_product_no: int,
    *,
    client: Optional['SmartStoreClient'] = None,
) -> FetchOptionsResult:
    """모음전 1개의 옵션 list 조회.

    Args:
      origin_product_no: 스마트스토어 원상품번호 (Model.naver_product_id)
      client: 주입된 SmartStoreClient (기본 새로 생성)

    Returns:
      FetchOptionsResult — success/options/error 포함
    """
    if client is None:
        from shared.platforms.smartstore.client import SmartStoreClient
        client = SmartStoreClient()

    path = f"/external/v2/products/origin-products/{origin_product_no}"
    try:
        resp = client.request("GET", path)
    except Exception as e:
        logger.exception('fetch_product_options HTTP error')
        return FetchOptionsResult(
            success=False, origin_product_no=origin_product_no,
            product_name=None, sale_price=None, options=[],
            error=str(e),
        )

    # 응답 파싱 — 네이버 커머스 API v2 구조
    # resp 가 dict 라 가정; 실패 시 resp.json() 통과 가정.
    if isinstance(resp, dict):
        payload = resp
    else:
        try:
            payload = resp.json() if hasattr(resp, 'json') else {}
        except Exception:
            payload = {}

    origin = payload.get('originProduct') or {}
    detail = origin.get('detailAttribute') or {}
    opt_info = detail.get('optionInfo') or {}
    combinations = opt_info.get('optionCombinations') or []

    options = []
    parse_failed = 0
    for c in combinations:
        try:
            options.append(OptionRow(
                option_id=int(c.get('id') or c.get('optionId') or 0),
                name1=c.get('optionName1'),
                name2=c.get('optionName2'),
                stock=int(c.get('stockQuantity') or 0),
                add_price=int(c.get('price') or 0),
                manager_code=c.get('sellerManagerCode'),
                usable=bool(c.get('usable', True)),
            ))
        except Exception as e:
            parse_failed += 1
            logger.warning(f'option parse failed: {e} {c}')

    if parse_failed:
        # 조용한 실패 금지 — 파싱 실패를 warning 로만 삼키지 않고 결과에 표면화
        logger.error(
            'fetch_product_options(%s): 옵션 %d/%d 파싱 실패 — 부분수집',
            origin_product_no, parse_failed, len(combinations))

    return FetchOptionsResult(
        success=True,
        origin_product_no=origin_product_no,
        product_name=origin.get('name'),
        sale_price=origin.get('salePrice'),
        options=options,
        raw=payload,
        combinations_total=len(combinations),
        parse_failed=parse_failed,
    )
