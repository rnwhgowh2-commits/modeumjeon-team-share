"""[연결] 마켓 상품번호 → 공통 MarketOption 목록 (소싱처별 어댑터).

smartstore 는 Task 3 에서 실 API 연결. 본 파일의 FetchResult 는 link_service·
테스트가 공유하는 공통 반환형이다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .linker import MarketOption


@dataclass
class FetchResult:
    success: bool
    product_name: Optional[str]
    options: list[MarketOption]
    error: Optional[str] = None


def fetch_market_options(market: str, product_id: str) -> FetchResult:
    """마켓 상품번호로 옵션 목록 조회. (smartstore 본체는 Task 3)"""
    if market == "smartstore":
        return _fetch_smartstore(product_id)
    return FetchResult(False, None, [], f"아직 지원하지 않는 마켓: {market}")


def _fetch_smartstore(product_id: str) -> FetchResult:
    from shared.platforms.smartstore.get_options import fetch_product_options
    try:
        pid = int(product_id)
    except (TypeError, ValueError):
        return FetchResult(False, None, [], f"상품번호가 숫자가 아니에요: {product_id!r}")
    r = fetch_product_options(pid)
    if not r.success:
        return FetchResult(False, None, [], r.error or "옵션 조회 실패")
    opts = [
        MarketOption(option_id=str(o.option_id), color=o.name1, size=o.name2,
                     stock=o.stock, price=o.add_price, usable=o.usable)
        for o in r.options
    ]
    return FetchResult(True, r.product_name, opts)
