"""[D] 업로더 런타임 — 실전송 게이트 + 옵션↔마켓 매핑.

안전 원칙:
  · 실제 마켓 전송은 환경변수 ``LEMOUTON_LIVE_UPLOAD`` 가 참일 때만.
  · 기본값 OFF → :class:`DryRunAdapter` (외부 호출 없음).
  · 켜더라도 shared.platforms.price_guard 가 0/비정상 가격을 전송 직전 abort.
"""
from __future__ import annotations

import logging
import os

from sqlalchemy.orm import Session

from .adapters.base import MarketAdapter, UploadResult

logger = logging.getLogger(__name__)

_TRUTHY = {"1", "true", "yes", "on"}


class DryRunAdapter(MarketAdapter):
    """외부 호출 없이 성공만 반환 — 실전송 OFF 시 기본 어댑터."""

    def __init__(self, market: str):
        self.market_name = market

    def update_price_and_stock(self, *, canonical_sku, market_product_id,
                               market_option_id, new_price, new_stock) -> UploadResult:
        return UploadResult(market=self.market_name, canonical_sku=canonical_sku,
                            success=True, http_status=200,
                            error="dry-run (외부 호출 없음)")


def live_upload_enabled() -> bool:
    """실전송 허용 여부 — 환경변수 ``LEMOUTON_LIVE_UPLOAD`` (기본 OFF)."""
    return (os.environ.get("LEMOUTON_LIVE_UPLOAD", "") or "").strip().lower() in _TRUTHY


def select_adapters(*, live: bool | None = None) -> dict[str, MarketAdapter]:
    """``{market: adapter}`` 레지스트리 반환.

    live=None → 환경변수로 판단. live=False 명시 → 무조건 드라이런.
    실전송이 켜져 있을 때만 실제 어댑터를 만들고, 그 외엔 :class:`DryRunAdapter`.

    dict 레지스트리인 이유: 마켓을 추가할 때 튜플 언패킹 지점을 매번 고칠 필요 없이
    ``adapters[market]`` 조회 한 곳으로 통일된다(orchestrator 의 마켓별 라우팅도 동일).
    """
    if live is None:
        live = live_upload_enabled()
    if not live:
        return {
            "smartstore": DryRunAdapter("smartstore"),
            "coupang": DryRunAdapter("coupang"),
            "lotteon": DryRunAdapter("lotteon"),
            "eleven11": DryRunAdapter("eleven11"),
        }
    from .adapters.coupang import CoupangAdapter
    from .adapters.smartstore import SmartStoreAdapter
    from .adapters.lotteon import LotteonAdapter
    from .adapters.eleven11 import Eleven11Adapter
    logger.warning("[uploader] LIVE 업로드 활성 — 실제 마켓 전송이 발생합니다")
    return {
        "smartstore": SmartStoreAdapter(),
        "coupang": CoupangAdapter(),
        "lotteon": LotteonAdapter(),
        "eleven11": Eleven11Adapter(),
    }


def build_sku_by_option(session: Session) -> dict:
    """matched 채널 옵션 → ``{(market, market_option_id): canonical_sku}``.

    ``_extract_uploads`` 가 C 페이로드의 option_id(= 마켓 옵션ID)로 조회하므로,
    숫자형 옵션ID는 문자열·정수 두 형태로 모두 등록해 타입 불일치를 막는다.
    matched 이면서 market_option_id 가 있는 행만 대상(폴백 금지 원칙).
    """
    from lemouton.sets.models import SetChannel, SetChannelOption

    mapping: dict = {}
    rows = (
        session.query(
            SetChannelOption.canonical_sku,
            SetChannelOption.market_option_id,
            SetChannel.market,
        )
        .join(SetChannel, SetChannelOption.channel_id == SetChannel.id)
        .filter(SetChannelOption.status == "matched")
        .filter(SetChannelOption.market_option_id.isnot(None))
        .all()
    )
    for sku, opt_id, market in rows:
        if opt_id is None or market is None:
            continue
        s_opt = str(opt_id)
        mapping[(market, s_opt)] = sku
        if s_opt.isdigit():
            mapping[(market, int(s_opt))] = sku
    return mapping
