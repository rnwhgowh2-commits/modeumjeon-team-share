# -*- coding: utf-8 -*-
"""
11번가 상품/옵션 상세조회 래퍼 (기존 상품 연동 = 옵션 조회).

⚠️ 스펙 미확보(로그인 게이트) — 셀러 REST 상품 상세조회 엔드포인트 경로와 응답 XML
   필드명(상품번호·단품/옵션 식별자·색/사이즈·재고·판매가)을 공개 문서에서 얻지 못했다.
   CLAUDE.md 3대 원칙(추측·폴백 금지)에 따라 **실제 파싱 로직은 스펙 확보 후 구현**한다.
   현재는 구조(시그니처)만 제공하고, 호출되면 스펙 필요를 명시적으로 표면화한다.

스펙 확보 시 채울 것(롯데온 products.py 대칭):
   · get_product_detail: client.request("GET"/"POST", paths["detail"], body) → 응답 XML
   · extract_items: XML → [{"item_name","option_id","color","size","stock",
                            "sale_price","status"}]  (0/센티넬 붕괴 금지, 미상=None)
"""
from __future__ import annotations

from typing import Optional

from shared.platforms.eleven11.client import Eleven11Client

_SPEC_NEEDED = (
    "11번가 셀러 REST 상품 상세조회 스펙 미확보(로그인 게이트). "
    "docs/markets/eleven11.yaml 의 endpoints/fields 를 확보한 뒤 구현하세요(추측 금지)."
)


def get_product_detail(
    product_id: str,
    *,
    client: Optional[Eleven11Client] = None,
    **_cfg_overrides,
) -> str:
    """상품/옵션 상세조회 → 응답 XML(str) 반환.

    ⚠️ 미구현 — 엔드포인트·필드 스펙 확보 후 채운다.
    """
    raise NotImplementedError(_SPEC_NEEDED)


def extract_items(detail) -> list[dict]:
    """상세조회 XML → 옵션 리스트 추출.

    ⚠️ 미구현 — 응답 XML 필드명 스펙 확보 후 채운다.
    """
    raise NotImplementedError(_SPEC_NEEDED)
