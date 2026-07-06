# -*- coding: utf-8 -*-
"""
11번가 재고 변경 API 래퍼.

⚠️ 스펙 미확보(로그인 게이트) — 셀러 REST 재고수정 엔드포인트·요청 XML 스키마를
   공개 문서에서 얻지 못했다. CLAUDE.md 원칙(추측·폴백 금지)에 따라 **실제 호출 로직은
   스펙 확보 후 구현**한다. 결과 dataclass 와 시그니처만 제공(롯데온 inventory.py 대칭).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from shared.platforms.eleven11.client import Eleven11Client

_SPEC_NEEDED = (
    "11번가 셀러 REST 재고수정 스펙 미확보(로그인 게이트). "
    "docs/markets/eleven11.yaml 의 endpoints/fields 를 확보한 뒤 구현하세요(추측 금지)."
)


@dataclass
class StockChangeResult:
    """옵션 1건 재고 변경 결과."""
    option_id: str
    success: bool
    result_code: Optional[str] = None
    error_message: Optional[str] = None


def update_stocks(
    items: list[dict],
    *,
    client: Optional[Eleven11Client] = None,
    **_cfg_overrides,
) -> list[StockChangeResult]:
    """여러 옵션 재고를 배치 변경. ⚠️ 미구현 — 스펙 확보 후 채운다."""
    raise NotImplementedError(_SPEC_NEEDED)


def update_stock(
    product_id: str,
    option_id: str,
    stock: int,
    *,
    client: Optional[Eleven11Client] = None,
    **_cfg_overrides,
) -> bool:
    """단일 옵션 재고 변경 (어댑터용). ⚠️ 미구현 — 스펙 확보 후 채운다."""
    raise NotImplementedError(_SPEC_NEEDED)
