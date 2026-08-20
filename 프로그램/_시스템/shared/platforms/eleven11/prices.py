# -*- coding: utf-8 -*-
"""
11번가 기본 판매가 수정 API 래퍼.

★ 확보 스펙(셀러 OPEN API CENTER 콘솔 추출, 정본):
  GET http://api.11st.co.kr/rest/prodservices/product/price/{prdNo}/{selPrc}
    · prdNo·selPrc 를 **URL 경로**에 넣는다(본문 없음). selPrc = 새 판매가(원, 정수).
    · 응답 XML:
        <ClientMessage>
          <resultCode>...</resultCode><message>...</message>
          <productNo>...</productNo><preSelPrc>수정전판매가</preSelPrc>
          <selPrc>...</selPrc><prdNo>...</prdNo>
        </ClientMessage>
    · 제약: 인상 50% / 인하 80% 한도(마켓 서버측 검증 — 위반 시 resultCode 실패로 표면화).

성공 판정(⚠️ 거짓 성공 금지):
  · resultCode ∈ {200,210} = 성공(11번가 상품등록 선례). 그 외/누락 = 실패(message 표면화).
  · **HTTP 2xx 만으로 성공 판정하지 않는다** — 본문 resultCode 로만 판정.
  · 정확한 성공 코드값은 라이브(SellerAPI 승인+서버IP) 확정 대상 → 보수적 기본.

정책(CLAUDE.md): 가격은 실브라우저 소싱처 URL 실값 기준·폴백 금지·실패 명시 표면화.
"""
from __future__ import annotations

import logging
import re as _re
import xml.etree.ElementTree as _ET
from dataclasses import dataclass
from typing import Optional

from shared.platforms.eleven11.client import Eleven11Client

logger = logging.getLogger(__name__)

# 보수적 성공 코드(라이브 확정 전). 상품등록 선례 200/210.
SUCCESS_CODES = {"200", "210"}

_PATH_PRICE = "/rest/prodservices/product/price/{prd_no}/{sel_prc}"


@dataclass
class PriceChangeResult:
    """상품 1건 판매가 변경 결과.

    11번가 기본 판매가는 **상품(prdNo) 단위**라 식별자는 product_id.
    (option_id 는 어댑터 로깅 호환을 위한 선택 필드.)
    """
    product_id: str
    success: bool
    result_code: Optional[str] = None
    error_message: Optional[str] = None
    option_id: Optional[str] = None
    pre_price: Optional[str] = None
    new_price: Optional[str] = None


def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse_client_message(xml_text: str) -> dict:
    """<ClientMessage> XML → {localname소문자: text}. 파싱 실패는 조용히 삼키지 않는다.

    반환 dict 에 파싱불가 시 '_raw' 스니펫을 담아 실패 message 로 표면화하게 한다.
    """
    cleaned = _re.sub(r"<\?xml[^>]*\?>", "", xml_text or "", count=1).strip()
    if not cleaned:
        return {"_raw": ""}
    try:
        root = _ET.fromstring(cleaned)
    except _ET.ParseError:
        return {"_raw": cleaned[:200]}
    found: dict = {}
    for el in root.iter():
        name = _localname(el.tag).lower()
        if name not in found:  # 최초값 우선(중첩 대비)
            found[name] = (el.text or "").strip()
    return found


def _result_from_message(product_id: str, found: dict) -> PriceChangeResult:
    code = found.get("resultcode", "") or ""
    success = code in SUCCESS_CODES
    if success:
        err = None
    else:
        msg = found.get("message") or ""
        if not code and "_raw" in found:
            err = f"응답 파싱 실패/결과코드 없음: {found['_raw']}"
        else:
            err = msg or f"resultCode={code or '누락'}"
    return PriceChangeResult(
        product_id=product_id,
        success=success,
        result_code=code or None,
        error_message=err,
        pre_price=found.get("preselprc") or None,
        new_price=found.get("selprc") or None,
    )


def update_price(
    product_id: str,
    price: int,
    *,
    client: Optional[Eleven11Client] = None,
    **_cfg_overrides,
) -> PriceChangeResult:
    """상품 기본 판매가 변경 (어댑터용).

    GET /rest/prodservices/product/price/{prdNo}/{selPrc} — 경로 파라미터 방식(본문 없음).
    성공 = resultCode ∈ SUCCESS_CODES. 실패는 message 를 error_message 로 표면화.
    """
    prd = str(product_id or "").strip()
    if not prd:
        raise ValueError("11번가 가격수정: 상품번호(prdNo) 없음")
    price_int = int(price)
    if price_int <= 0:
        raise ValueError(f"11번가 가격수정: 판매가는 양의 정수여야 함 (입력={price!r})")

    client = client or Eleven11Client()
    path = _PATH_PRICE.format(prd_no=prd, sel_prc=price_int)
    xml_text = client.request("GET", path)
    result = _result_from_message(prd, _parse_client_message(xml_text))
    if not result.success:
        logger.warning("[11번가] 가격수정 실패 prdNo=%s code=%s msg=%s",
                       prd, result.result_code, result.error_message)
    return result


def update_prices(
    items: list[dict],
    *,
    client: Optional[Eleven11Client] = None,
    **_cfg_overrides,
) -> list[PriceChangeResult]:
    """여러 상품 판매가를 배치 변경(개별 GET 호출 반복).

    items: [{ "product_id", "price" }]. 11번가는 배치 엔드포인트가 없어 상품마다 호출한다.
    """
    if not items:
        return []
    client = client or Eleven11Client()
    return [
        update_price(str(it["product_id"]), int(it["price"]), client=client)
        for it in items
    ]
