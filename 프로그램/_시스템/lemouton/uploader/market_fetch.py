"""[연결] 마켓 상품번호 → 공통 MarketOption 목록 (마켓별 어댑터).

env_prefix 를 주면 그 판매처 **계정의 키**로 조회(계정별 시크릿). 없으면 전역 기본 클라이언트.
FetchResult 는 link_service·테스트가 공유하는 공통 반환형.
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


def fetch_market_options(market: str, product_id: str, *,
                         env_prefix: Optional[str] = None) -> FetchResult:
    """마켓 상품번호로 옵션 목록 조회.

    env_prefix 주면 그 계정 키로 호출(없으면 전역 기본). 마켓에 쓰지 않음(읽기).
    """
    if market == "smartstore":
        return _fetch_smartstore(product_id, env_prefix)
    if market == "coupang":
        return _fetch_coupang(product_id, env_prefix)
    return FetchResult(False, None, [], f"아직 지원하지 않는 마켓: {market}")


def _smartstore_client(env_prefix: Optional[str]):
    """env_prefix 계정 키로 SmartStoreClient 생성. 없으면 None(=전역 기본)."""
    if not env_prefix:
        return None
    from lemouton.auth import secrets as S
    from shared.platforms import SMARTSTORE
    from shared.platforms.smartstore.client import SmartStoreClient
    c = S.load_credentials(market="smartstore", env_prefix=env_prefix)
    return SmartStoreClient(config={**SMARTSTORE,
                                    "client_id": c.client_id,
                                    "client_secret": c.client_secret})


def _coupang_client(env_prefix: Optional[str]):
    """env_prefix 계정 키로 CoupangClient 생성. 없으면 None(=전역 기본)."""
    if not env_prefix:
        return None
    from lemouton.auth import secrets as S
    from shared.platforms import COUPANG
    from shared.platforms.coupang.client import CoupangClient
    c = S.load_credentials(market="coupang", env_prefix=env_prefix)
    return CoupangClient(config={**COUPANG,
                                 "access_key": c.access_key,
                                 "secret_key": c.secret_key,
                                 "vendor_id": c.vendor_id})


def _fetch_smartstore(product_id: str, env_prefix: Optional[str] = None) -> FetchResult:
    from shared.platforms.smartstore.get_options import fetch_product_options
    try:
        pid = int(product_id)
    except (TypeError, ValueError):
        return FetchResult(False, None, [], f"상품번호가 숫자가 아니에요: {product_id!r}")
    try:
        client = _smartstore_client(env_prefix)
        # input may be a channelProductNo(상품번호) not originProductNo;
        # resolve_product_ids recognizes either and returns the true origin.
        from shared.platforms.smartstore.get_channel_no import resolve_product_ids
        resolved = resolve_product_ids(pid, client=client)
        origin_pid = resolved["origin_product_no"] if resolved else pid
        r = fetch_product_options(origin_pid, client=client)
    except Exception as e:  # noqa: BLE001 — 인증/조회 실패 명시 표면화(폴백 금지)
        return FetchResult(False, None, [], f"옵션 조회 실패: {e}")
    if not r.success:
        return FetchResult(False, None, [], r.error or "옵션 조회 실패")
    # 현재가 = 기본 판매가(salePrice) + 옵션 추가금(add_price, delta).
    #   과거엔 price=o.add_price(델타만) 이라 추가금 0원 옵션이 '현재가 0원'으로 둔갑.
    #   쿠팡(_fetch_coupang)은 sale_price 를 그대로 쓰므로 두 마켓 의미를 일치시킨다.
    _base = r.sale_price or 0
    opts = [
        MarketOption(option_id=str(o.option_id), color=o.name1, size=o.name2,
                     stock=o.stock, price=_base + int(o.add_price or 0),
                     usable=o.usable)
        for o in r.options
    ]
    return FetchResult(True, r.product_name, opts)


def _fetch_coupang(product_id: str, env_prefix: Optional[str] = None) -> FetchResult:
    from shared.platforms.coupang.products import get_product, extract_vendor_items
    try:
        spid = int(product_id)
    except (TypeError, ValueError):
        return FetchResult(False, None, [], f"상품번호가 숫자가 아니에요: {product_id!r}")
    try:
        client = _coupang_client(env_prefix)
        detail = get_product(spid, client=client)
    except Exception as e:  # noqa: BLE001 — 조회 실패는 명시 표면화(폴백 금지)
        return FetchResult(False, None, [], f"옵션 조회 실패: {e}")
    items = extract_vendor_items(detail)
    # 쿠팡: 옵션별 재고 미제공 → stock=None(0 하드코딩 금지, 품절 둔갑 방지).
    #       판매가 없으면 None(0 으로 붕괴 금지 — 미상으로 표면화).
    opts = [
        MarketOption(option_id=str(it["vendor_item_id"]), color=it.get("color"),
                     size=it.get("size"), stock=None, price=it.get("sale_price"))
        for it in items
    ]
    name = detail.get("sellerProductName") or detail.get("displayProductName")
    return FetchResult(True, name, opts)
