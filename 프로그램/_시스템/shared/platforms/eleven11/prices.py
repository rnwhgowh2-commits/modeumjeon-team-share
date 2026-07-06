# -*- coding: utf-8 -*-
"""
11번가 가격 변경 API 래퍼.

⚠️ 스펙 미확보(로그인 게이트) — 셀러 REST 가격수정 엔드포인트·요청 XML 스키마를
   공개 문서에서 얻지 못했다. CLAUDE.md 원칙(추측·폴백 금지)에 따라 **실제 호출 로직은
   스펙 확보 후 구현**한다. 결과 dataclass 와 시그니처만 제공(롯데온 prices.py 대칭).

정책 (CLAUDE.md): 가격은 실브라우저 소싱처 URL 실값 기준·폴백 금지·실패 명시 표면화.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from shared.platforms.eleven11.client import Eleven11Client

_SPEC_NEEDED = (
    "11번가 셀러 REST 가격수정 스펙 미확보(로그인 게이트). "
    "docs/markets/eleven11.yaml 의 endpoints/fields 를 확보한 뒤 구현하세요(추측 금지)."
)


@dataclass
class PriceChangeResult:
    """옵션 1건 가격 변경 결과."""
    option_id: str
    success: bool
    result_code: Optional[str] = None
    error_message: Optional[str] = None


def update_prices(
    items: list[dict],
    *,
    client: Optional[Eleven11Client] = None,
    **_cfg_overrides,
) -> list[PriceChangeResult]:
    """여러 옵션 가격을 배치 변경. ⚠️ 미구현 — 스펙 확보 후 채운다."""
    raise NotImplementedError(_SPEC_NEEDED)


def update_price(
    product_id: str,
    option_id: str,
    price: int,
    *,
    client: Optional[Eleven11Client] = None,
    **_cfg_overrides,
) -> PriceChangeResult:
    """단일 옵션 판매가 변경 (어댑터용). ⚠️ 미구현 — 스펙 확보 후 채운다."""
    raise NotImplementedError(_SPEC_NEEDED)
