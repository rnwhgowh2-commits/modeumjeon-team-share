# -*- coding: utf-8 -*-
"""판매처(마켓) 확장 기능 커넥터 — 흩어진 API 부품을 (마켓×기능) 레지스트리로 묶고,
마스터 게이트(``LEMOUTON_MARKET_EXTRA``) 뒤에 안전하게 둔다.

원칙:
- **기본 OFF.** 켜지 않으면 확장 기능(주문·정산·반품·문의·카테고리·배송·신규등록 등)은
  ``resolve()`` 가 ``CapabilityDisabled`` 를 던져 **실제 호출이 일어나지 않는다.**
- "코드(래퍼)는 있으나 프로그램이 아직 안 쓰는" 부품을 **한 곳에서 닿게(=연결)** 하되,
  실계정 100% 검증 전에는 ``verified=False`` → 데이터 코드 지도에 **"연결됨(검증대기)"** 로 표기.
- 가격·재고·판매상태·조회처럼 **이미 실사용 중인 핵심 기능만 ``verified=True``** (게이트와 무관하게 사용).
- 새 기능을 실제로 켤 때: 배포 env ``LEMOUTON_MARKET_EXTRA=1`` + **해당 기능 실계정 검증** 후 ``verified`` 승격.

관련: CLAUDE.md 🔒 3대 원칙(실계정 검증 전 완료 금지) · docs/markets/_새-마켓-추가-가이드.md
"""
from __future__ import annotations

import importlib
import os
from dataclasses import dataclass


class CapabilityDisabled(RuntimeError):
    """마스터 게이트 OFF 상태에서 미검증 확장 기능을 호출하려 할 때."""


def market_extra_enabled() -> bool:
    """확장 기능(주문·정산·CS 등) 실호출 허용 여부. 기본 False(=연결만·검증대기)."""
    return os.environ.get("LEMOUTON_MARKET_EXTRA") == "1"


DISABLED_MESSAGE = (
    "이 기능은 아직 '연결됨(검증대기)' 상태예요. 실계정 검증 후 "
    "LEMOUTON_MARKET_EXTRA=1 로 켜야 실제로 호출됩니다."
)


@dataclass(frozen=True)
class Capability:
    key: str
    label: str
    direction: str          # 'send'(프로그램→마켓) | 'recv'(마켓→프로그램)
    module: str             # import 경로
    func: str               # 함수명
    verified: bool = False   # 실계정 검증 완료(=이미 실사용). False = 연결됨·검증대기.


_C = "shared.platforms.coupang."
_S = "shared.platforms.smartstore."
_L = "shared.platforms.lotteon."

# (마켓 × 기능) → 실제 래퍼 함수. func 은 그 모듈의 공개 함수와 정확히 일치해야 한다
# (test_all_wrappers_import_when_enabled 가 전수 import 로 검증).
CAPABILITIES: dict[str, list[Capability]] = {
    "coupang": [
        Capability("product_register", "상품 등록", "send", _C + "products", "create_product"),
        Capability("product_fetch", "판매가·옵션 조회", "recv", _C + "products", "get_product", verified=True),
        Capability("price_update", "가격", "send", _C + "prices", "update_price", verified=True),
        Capability("stock_update", "재고", "send", _C + "inventory", "update_quantity", verified=True),
        Capability("category_predict", "카테고리 추천", "recv", _C + "categories", "predict"),
        Capability("category_meta", "카테고리 메타·고시", "recv", _C + "categories", "get_meta"),
        Capability("shipping_outbound", "출고지 조회", "recv", _C + "shipping", "list_outbound_places"),
        Capability("shipping_return", "반품지 조회", "recv", _C + "shipping", "list_return_centers"),
        Capability("order_fetch", "주문 조회", "recv", _C + "orders", "fetch_orders"),
        Capability("order_detail", "주문 상세", "recv", _C + "orders", "fetch_order_detail"),
        Capability("tracking_send", "송장·발송처리", "send", _C + "orders", "send_tracking"),
        Capability("settlement_fetch", "정산 예정금액", "recv", _C + "settlements", "fetch_revenue_page"),
        Capability("claim_list", "반품·취소·교환 조회", "recv", _C + "claims", "list_return_requests"),
        Capability("claim_approve", "반품 승인", "send", _C + "claims", "approve_return_request"),
        Capability("inquiry_fetch", "고객문의 조회", "recv", _C + "inquiries", "fetch_online_inquiries"),
        Capability("inquiry_reply", "문의 답변", "send", _C + "inquiries", "reply_online_inquiry"),
    ],
    "smartstore": [
        Capability("product_register", "상품 등록", "send", _S + "create_product", "create_product"),
        Capability("product_delete", "상품 삭제", "send", _S + "create_product", "delete_origin_product"),
        Capability("option_fetch", "판매가·옵션 조회", "recv", _S + "get_options", "fetch_product_options", verified=True),
        Capability("product_edit", "가격·재고 수정", "send", _S + "edit_product", "edit_options", verified=True),
        Capability("sale_status", "판매상태", "send", _S + "change_status", "change_sale_status", verified=True),
        Capability("product_search", "상품 검색", "recv", _S + "get_channel_no", "resolve_product_ids"),
        Capability("channel_no", "채널상품번호 조회", "recv", _S + "get_channel_no", "fetch_channel_product_no"),
        Capability("order_fetch", "주문 조회", "recv", _S + "orders", "fetch_orders"),
        Capability("order_detail", "주문 상세", "recv", _S + "orders", "fetch_order_detail"),
        Capability("tracking_send", "송장·발송처리", "send", _S + "orders", "send_tracking"),
        Capability("inquiry_fetch", "고객문의 조회", "recv", _S + "orders", "fetch_inquiries"),
        Capability("inquiry_reply", "문의 답변", "send", _S + "orders", "reply_inquiry"),
        Capability("claim_handle", "반품·취소·교환 처리", "send", _S + "orders", "handle_claim"),
    ],
    "lotteon": [
        Capability("product_fetch", "판매가·옵션 조회", "recv", _L + "products", "get_product_detail"),
        Capability("price_update", "가격", "send", _L + "prices", "update_price"),
        Capability("stock_update", "재고", "send", _L + "inventory", "update_stock"),
    ],
}


def supported_markets() -> list[str]:
    return list(CAPABILITIES.keys())


def list_capabilities(market: str) -> list[Capability]:
    return list(CAPABILITIES.get(market, []))


def _find(market: str, key: str):
    for c in CAPABILITIES.get(market, []):
        if c.key == key:
            return c
    return None


def resolve(market: str, capability: str):
    """확장 기능 호출 함수를 반환. 미검증(verified=False) 기능은 마스터 게이트 OFF 면
    ``CapabilityDisabled`` 를 던진다(실호출 차단). 이미 실사용(verified=True)은 항상 반환."""
    spec = _find(market, capability)
    if spec is None:
        raise KeyError(f"unknown capability: {market}/{capability}")
    if not spec.verified and not market_extra_enabled():
        raise CapabilityDisabled(DISABLED_MESSAGE)
    module = importlib.import_module(spec.module)
    return getattr(module, spec.func)
