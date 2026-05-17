# -*- coding: utf-8 -*-
"""
쿠팡 가격 변경 API 래퍼

공식 엔드포인트 (https://developers.coupangcorp.com/hc/ko/articles/360034156273):
    PUT /v2/providers/seller_api/apis/api/v1/marketplace/vendor-items/{vendorItemId}/prices/{price}
    Query: forceSalePriceUpdate (bool)

정책 (CLAUDE.md + 사용자 결정):
- 기본 `force=False` (auto_force 금지)
- 쿠팡 제약: 기존가 대비 -50% ~ +100% 변경만 허용. 초과 시 400
- 400(변경비율 초과) 감지 시 → 자동 force 금지, notifier 알림 + manual_review_required=True
- 실패 시 PriceChangeResult(success=False) 반환 → 호출자가 이전값 유지 처리
- 가격 최소 단위 10원

호출자 책임:
- validator.py 의 5단계 사전 검증 통과 후에만 호출
- 실패 시 이전값 유지 / 재시도 전략
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from shared.platforms import COUPANG
from shared.platforms.coupang.client import CoupangClient, CoupangAPIError


logger = logging.getLogger(__name__)


# 쿠팡 400 응답에 포함되는 "변경비율 초과" 시그니처 문구 (공식 에러 스펙 기반)
_RATE_LIMIT_ERROR_KEYWORDS = (
    "변경전 판매가",
    "50%",
    "100%인상",
    "변경비율",
)


@dataclass
class PriceChangeResult:
    """가격 변경 결과.

    Attributes:
        success: API 성공 여부
        manual_review_required:
            True 인 경우, 쿠팡의 변경비율 제한(50%/100%)을 초과해서
            자동 처리가 차단된 상태. 사람이 확인 후 force=True 로 재시도하거나
            WING에서 직접 수정 필요.
        error_message: 실패 사유
    """
    success: bool
    manual_review_required: bool = False
    error_message: Optional[str] = None


def _is_rate_limit_error(message: str) -> bool:
    m = message or ""
    return any(k in m for k in _RATE_LIMIT_ERROR_KEYWORDS)


def update_price(
    vendor_item_id: int,
    price: int,
    previous_price: Optional[int] = None,
    force: bool = False,
    client: Optional[CoupangClient] = None,
    notifier: Optional[object] = None,
) -> PriceChangeResult:
    """옵션 판매가를 변경한다.

    Args:
        vendor_item_id: 쿠팡 옵션 ID
        price: 변경할 판매가 (10원 단위)
        previous_price: 기존 가격 (알림 상세용, 필수는 아님)
        force: True 면 forceSalePriceUpdate=true. 사용자가 명시적으로
               허용한 경우에만 사용. 기본값은 config 의 auto_force 에 따른다.
        client: 주입받은 CoupangClient. None 이면 기본 생성.
        notifier: 알림 발송 객체 (manual_review 발생 시 호출).

    Returns:
        PriceChangeResult
    """
    if price <= 0:
        raise ValueError(f"price 는 양의 정수여야 합니다 (입력: {price})")
    if price % COUPANG.get("price_unit", 10) != 0:
        raise ValueError("price 는 10원 단위로만 입력 가능합니다")

    # config 에 auto_force=False 로 고정된 상태. 외부에서 force=True 전달된 경우만 적용.
    effective_force = bool(force) and not COUPANG["price_change"].get("auto_force", False)
    if force and COUPANG["price_change"].get("auto_force", False):
        # 정책상 자동 force 가 차단되지만 호출자가 명시 force 를 준 경우엔 사용한다
        effective_force = True

    path_tpl = COUPANG["paths"]["update_price"]
    path = path_tpl.format(vendorItemId=vendor_item_id, price=price)
    query = f"forceSalePriceUpdate={'true' if effective_force else 'false'}"

    client = client or CoupangClient()
    try:
        resp = client.request(method="PUT", path=path, query=query)
    except CoupangAPIError as e:
        # 변경비율 초과 400 — 자동 force 금지 상태라면 수동 처리 유도
        if (
            e.status_code == 400
            and _is_rate_limit_error(e.message)
            and not effective_force
            and COUPANG["price_change"].get("alert_on_limit_hit", True)
        ):
            _alert_manual_review(
                notifier=notifier,
                vendor_item_id=vendor_item_id,
                price=price,
                previous_price=previous_price,
                message=e.message,
            )
            return PriceChangeResult(
                success=False,
                manual_review_required=True,
                error_message=e.message,
            )

        logger.warning(
            "가격 변경 실패 vendor_item_id=%s price=%s force=%s status=%s msg=%s",
            vendor_item_id, price, effective_force, e.status_code, e.message,
        )
        return PriceChangeResult(success=False, error_message=e.message)

    return PriceChangeResult(success=(resp.get("code") == "SUCCESS"))


def _alert_manual_review(
    notifier,
    vendor_item_id: int,
    price: int,
    previous_price: Optional[int],
    message: str,
) -> None:
    if not notifier:
        return
    subject = "[쿠팡] 가격 변경비율 초과 — 수동 확인 필요"
    detail = {
        "vendor_item_id": vendor_item_id,
        "new_price": price,
        "previous_price": previous_price,
        "api_message": message,
        "action_required": (
            "WING 에서 직접 수정하거나, validator 재확인 후 force=True 로 재시도"
        ),
    }
    try:
        notifier.send_alert(subject=subject, detail=detail)
    except Exception:
        logger.exception("가격 변경비율 초과 알림 발송 실패")
