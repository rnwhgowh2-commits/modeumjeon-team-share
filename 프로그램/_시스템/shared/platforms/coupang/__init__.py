# -*- coding: utf-8 -*-
"""
쿠팡 Open API 연동 모듈

역할 경계 (CLAUDE.md):
- 판매처 업로드 전용. 소싱처 수집 로직 금지.
- 모든 설정값은 config.COUPANG 참조. 하드코딩 금지.
- 가격/재고 처리 전 validator.py 통과 필수.
"""

from shared.platforms.coupang.auth import build_authorization
from shared.platforms.coupang.client import CoupangClient, CoupangAPIError
from shared.platforms.coupang.inventory import update_quantity
from shared.platforms.coupang.prices import update_price, PriceChangeResult

__all__ = [
    "build_authorization",
    "CoupangClient",
    "CoupangAPIError",
    "update_quantity",
    "update_price",
    "PriceChangeResult",
]
