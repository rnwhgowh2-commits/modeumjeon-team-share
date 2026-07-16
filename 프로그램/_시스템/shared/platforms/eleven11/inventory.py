# -*- coding: utf-8 -*-
"""
11번가 옵션 가격+재고 수정 API 래퍼 (옵션 full-replace).

★ 확보 스펙(셀러 OPEN API CENTER 콘솔 추출, 정본):
  POST http://api.11st.co.kr/rest/prodservices/updateProductOption/{prdNo}
    · 본문 XML:
        <Product>
          <ProductOption>
            <colValue0>옵션값</colValue0>
            <colOptPrice>옵션가(기본가 대비 +/-)</colOptPrice>
            <colCount>옵션재고수량</colCount>
            <useYn>Y|N</useYn>
            <colSellerStockCd>셀러재고번호</colSellerStockCd>   (선택)
            <optionMappingKey>옵션매핑Key</optionMappingKey>     (선택)
          </ProductOption>
          ... 옵션마다 반복 ...
        </Product>
    · ⚠️ **full-replace 추정** — 옵션 전체를 보내야 할 수 있다(ESM recommended-options 선례).
      단건만 보내면 나머지 옵션이 삭제/초기화될 위험 → 단건 update_stock 은 막는다.
    · 응답 <ClientMessage> + resultCode/message. 성공 = resultCode ∈ {200,210}(보수적).

정책(CLAUDE.md): 재고=실브라우저 소싱처 URL 실값 기준·폴백 금지. 0=품절도 명시 전송
  (센티넬 붕괴 금지). 실패(미승인 300 등)는 message 로 표면화. HTTP 2xx 만으로 성공 판정 금지.

라이브 검증 한계: SellerAPI 승인·서버IP 등록 전에는 실호출 검증 불가. 성공 resultCode
  정확값은 라이브 확정 대상(코드엔 보수적 기본).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional
from xml.sax.saxutils import escape as _xml_escape

from shared.platforms.eleven11.client import Eleven11Client
from shared.platforms.eleven11.prices import (
    SUCCESS_CODES,
    _parse_client_message,
)

logger = logging.getLogger(__name__)

_PATH_OPTION = "/rest/prodservices/updateProductOption/{prd_no}"


@dataclass
class StockChangeResult:
    """옵션 full-replace 1회(상품 단위) 재고/옵션 변경 결과."""
    product_id: str
    success: bool
    result_code: Optional[str] = None
    error_message: Optional[str] = None


def _opt_get(opt: dict, snake: str, camel: str, default=None):
    """옵션 dict 에서 snake_case 또는 camelCase 키를 허용해 값을 꺼낸다."""
    if snake in opt:
        return opt[snake]
    if camel in opt:
        return opt[camel]
    return default


def _build_option_xml(options: list[dict]) -> str:
    """옵션 리스트 → <Product><ProductOption>...</Product> XML(euc-kr 선언).

    필수: colValue0(옵션값)·colCount(재고수량). 없으면 조용히 0/공란으로 붕괴시키지 않고 예외.
    선택: colOptPrice(기본 0)·useYn(기본 Y)·colSellerStockCd·optionMappingKey.
    값은 XML 이스케이프한다(옵션명의 &,<,> 누출 방지).
    """
    parts = ['<?xml version="1.0" encoding="euc-kr"?>', "<Product>"]
    for idx, opt in enumerate(options):
        col_value0 = _opt_get(opt, "col_value0", "colValue0")
        col_count = _opt_get(opt, "col_count", "colCount")
        if col_value0 is None or str(col_value0) == "":
            raise ValueError(f"옵션[{idx}] colValue0(옵션값) 누락")
        if col_count is None:
            raise ValueError(f"옵션[{idx}] colCount(재고수량) 누락 — 0=품절도 명시 필요")

        col_opt_price = _opt_get(opt, "col_opt_price", "colOptPrice", 0)
        use_yn = str(_opt_get(opt, "use_yn", "useYn", "Y") or "Y")
        seller_stock_cd = _opt_get(opt, "col_seller_stock_cd", "colSellerStockCd", "")
        mapping_key = _opt_get(opt, "option_mapping_key", "optionMappingKey", "")

        parts.append("<ProductOption>")
        parts.append(f"<colValue0>{_xml_escape(str(col_value0))}</colValue0>")
        parts.append(f"<colOptPrice>{int(col_opt_price)}</colOptPrice>")
        parts.append(f"<colCount>{int(col_count)}</colCount>")
        parts.append(f"<useYn>{_xml_escape(use_yn)}</useYn>")
        if str(seller_stock_cd) != "":
            parts.append(
                f"<colSellerStockCd>{_xml_escape(str(seller_stock_cd))}</colSellerStockCd>")
        if str(mapping_key) != "":
            parts.append(
                f"<optionMappingKey>{_xml_escape(str(mapping_key))}</optionMappingKey>")
        parts.append("</ProductOption>")
    parts.append("</Product>")
    return "".join(parts)


def update_option_stocks(
    product_id: str,
    options: list[dict],
    *,
    client: Optional[Eleven11Client] = None,
    **_cfg_overrides,
) -> StockChangeResult:
    """상품의 옵션 전체(가격+재고)를 full-replace 로 변경.

    POST /rest/prodservices/updateProductOption/{prdNo}.
    options: [{ col_value0, col_count, (col_opt_price, use_yn, col_seller_stock_cd,
                option_mapping_key) }].  ⚠️ 대상 상품의 **전체 옵션**을 담아야 한다
    (일부만 보내면 나머지가 사라질 수 있음 — full-replace).
    성공 = resultCode ∈ SUCCESS_CODES. 실패는 message 를 error_message 로 표면화.
    """
    prd = str(product_id or "").strip()
    if not prd:
        raise ValueError("11번가 옵션수정: 상품번호(prdNo) 없음")
    if not options:
        raise ValueError(
            "11번가 옵션수정: 옵션 목록이 비어있음 — full-replace 는 전체 옵션이 필요")

    body = _build_option_xml(options)
    client = client or Eleven11Client()
    xml_text = client.request("POST", _PATH_OPTION.format(prd_no=prd), body)

    found = _parse_client_message(xml_text)
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
        logger.warning("[11번가] 옵션수정 실패 prdNo=%s code=%s msg=%s", prd, code, err)
    return StockChangeResult(product_id=prd, success=success,
                             result_code=code or None, error_message=err)


def update_stock(
    product_id: str,
    option_id: str,
    stock: int,
    *,
    client: Optional[Eleven11Client] = None,
    **_cfg_overrides,
) -> bool:
    """⛔ 단건 옵션 재고 변경은 지원하지 않는다(안전).

    11번가 재고 수정은 옵션 full-replace(updateProductOption)라, 옵션 1건만 보내면
    같은 상품의 **다른 옵션이 삭제/초기화**될 수 있다(금전·재고 손실). 따라서 단건 경로는
    아무 것도 전송하지 않고 즉시 막는다. 재고를 바꾸려면 대상 상품의 **전체 옵션**을 모아
    ``update_option_stocks(product_id, options=[...전체...])`` 를 호출하라.
    """
    raise NotImplementedError(
        "11번가 재고는 옵션 full-replace 라 단건 전송이 다른 옵션을 날릴 수 있음. "
        "update_option_stocks(product_id, options=[상품의 전체 옵션]) 로 호출하세요."
    )


def update_stocks(
    items: list[dict],
    *,
    client: Optional[Eleven11Client] = None,
    **_cfg_overrides,
) -> list[StockChangeResult]:
    """여러 상품의 옵션 재고를 배치 변경.

    items: [{ "product_id", "options": [옵션전체] }].  각 상품마다 full-replace 1회.
    (옵션 단건 리스트가 아니라 **상품별 전체 옵션 묶음**이어야 안전.)
    """
    if not items:
        return []
    client = client or Eleven11Client()
    return [
        update_option_stocks(str(it["product_id"]), it["options"], client=client)
        for it in items
    ]
