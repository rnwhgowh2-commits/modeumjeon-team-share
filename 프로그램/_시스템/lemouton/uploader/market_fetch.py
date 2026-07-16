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
    if market == "lotteon":
        return _fetch_lotteon(product_id, env_prefix)
    if market == "eleven11":
        return _fetch_eleven11(product_id, env_prefix)
    if market in ("auction", "gmarket"):
        return _fetch_esm(market, product_id, env_prefix)
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


def _lotteon_client(env_prefix: Optional[str]):
    """env_prefix 계정 키로 LotteonClient 생성. 없으면 None(=전역 기본)."""
    if not env_prefix:
        return None
    from lemouton.auth import secrets as S
    from shared.platforms import LOTTEON
    from shared.platforms.lotteon.client import LotteonClient
    c = S.load_credentials(market="lotteon", env_prefix=env_prefix)
    return LotteonClient(config={**LOTTEON,
                                 "api_key": c.api_key,
                                 "tr_no": c.tr_no})


def _fetch_lotteon(product_id: str, env_prefix: Optional[str] = None) -> FetchResult:
    from shared.platforms.lotteon.products import get_product_detail, extract_items
    if not str(product_id).strip():
        return FetchResult(False, None, [], "상품번호(spdNo)가 비어있어요")
    try:
        client = _lotteon_client(env_prefix)
        detail = get_product_detail(str(product_id), client=client)
    except Exception as e:  # noqa: BLE001 — 조회 실패는 명시 표면화(폴백 금지)
        return FetchResult(False, None, [], f"옵션 조회 실패: {e}")
    items = extract_items(detail)
    # 롯데온: 단품(sitmNo)=옵션. 재고 미관리(stkMgtYn=N)면 stock=None(센티넬 노출 금지).
    #         판매가 없으면 None(0 붕괴 금지 — 미상 표면화).
    opts = [
        MarketOption(option_id=str(it["sitm_no"]), color=it.get("color"),
                     size=it.get("size"), stock=it.get("stock"),
                     price=it.get("sale_price"))
        for it in items
    ]
    name = detail.get("spdNm") or detail.get("pdNm")
    return FetchResult(True, name, opts)


def _eleven11_client(env_prefix: Optional[str]):
    """env_prefix 계정 키로 Eleven11Client 생성. 없으면 None(=전역 기본)."""
    if not env_prefix:
        return None
    from lemouton.auth import secrets as S
    from shared.platforms import ELEVEN11
    from shared.platforms.eleven11.client import Eleven11Client
    c = S.load_credentials(market="eleven11", env_prefix=env_prefix)
    return Eleven11Client(config={**ELEVEN11, "openapi_key": c.openapi_key})


def _esm_client(market: str, env_prefix: Optional[str]):
    """env_prefix 계정 키로 EsmClient(옥션·G마켓) 생성. 없으면 None(=전역 기본).

    옥션·G마켓은 같은 ESM 스키마(master_id·secret_key·seller_id). site_id 는 config 고정(A/G).
    """
    if not env_prefix:
        return None
    from lemouton.auth import secrets as S
    from shared.platforms import AUCTION, GMARKET
    from shared.platforms.esm.client import EsmClient
    base = AUCTION if market == "auction" else GMARKET
    c = S.load_credentials(market=market, env_prefix=env_prefix)
    return EsmClient(config={**base,
                             "master_id": c.master_id,
                             "secret_key": c.secret_key,
                             "seller_id": c.seller_id})


def _auction_client(env_prefix: Optional[str]):
    return _esm_client("auction", env_prefix)


def _gmarket_client(env_prefix: Optional[str]):
    return _esm_client("gmarket", env_prefix)


def _fetch_esm(market: str, product_id: str, env_prefix: Optional[str] = None) -> FetchResult:
    """옥션·G마켓(ESM 2.0) 기존 상품 연동 — 사이트상품번호→goodsNo→옵션 조회.

    입력=옥션/G마켓 사이트 상품번호. resolve_goods_no 로 마스터 goodsNo 변환 후 상세조회.
    옵션 재고는 해당 마켓 사이트 값(gmkt/iac). 미상은 None(0/센티넬 금지 — 미상 표면화).
    """
    from shared.platforms.esm.products import (resolve_goods_no, get_goods_detail,
                                               extract_options, _ci_get)
    if not str(product_id).strip():
        return FetchResult(False, None, [], "상품번호가 비어있어요")
    try:
        client = _esm_client(market, env_prefix)
        if client is None:
            return FetchResult(False, None, [], "계정 키가 없어요 (env_prefix 필요)")
        goods_no = resolve_goods_no(str(product_id), client=client)
        detail = get_goods_detail(str(goods_no), client=client)
    except Exception as e:  # noqa: BLE001 — 조회 실패는 명시 표면화(폴백 금지)
        return FetchResult(False, None, [], f"옵션 조회 실패: {e}")
    opts = [
        MarketOption(option_id=str(o["option_id"]), color=o.get("color"),
                     size=o.get("size"), stock=o.get("stock"), price=None)
        for o in extract_options(detail, market)
    ]
    basic = _ci_get(detail, "itemBasicInfo") or {}
    gname = _ci_get(basic, "goodsName")
    if isinstance(gname, dict):
        gname = _ci_get(gname, "kor") or _ci_get(gname, "eng")
    name = gname or _ci_get(detail, "goodsName")
    return FetchResult(True, name, opts)


def _fetch_eleven11(product_id: str, env_prefix: Optional[str] = None) -> FetchResult:
    # 11번가는 상품 상세조회 스펙은 미확보지만, 재고조회(stocks_query)로 옵션 전체를
    #   얻는다(mixOptNo·옵션명·재고). 이걸로 옵션 목록·현재재고를 채운다.
    #   ⚠️판매가는 상품(prdNo) 단위라 재고조회 응답에 없다 → price=None(직접 입력).
    #   조회 실패는 명시 표면화(추측·폴백 금지).
    from shared.platforms.eleven11.stocks_query import get_stocks
    if not str(product_id).strip():
        return FetchResult(False, None, [], "상품번호가 비어있어요")
    try:
        client = _eleven11_client(env_prefix)
        rows = get_stocks(str(product_id), client=client)
    except Exception as e:  # noqa: BLE001 — 조회 실패 명시 표면화(추측·폴백 금지)
        return FetchResult(False, None, [], f"옵션 조회 실패: {e}")
    opts = [
        # market_option_id = prdStckNo(재고번호) — 재고 변경 키(PUT stockqty). 라벨은 옵션명.
        MarketOption(option_id=str(r.get("prd_stck_no")),
                     color=r.get("dtl_opt_nm") or r.get("opt_nm"), size=None,
                     stock=r.get("stock"), price=None)
        for r in rows if r.get("prd_stck_no") is not None
    ]
    return FetchResult(True, None, opts,
                       None if opts else "옵션이 없어요(상품번호·계정 확인)")


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
