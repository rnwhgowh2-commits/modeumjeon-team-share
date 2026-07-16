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


def build_full_replace_from_current(
    current_options: list[dict],
    changes: Optional[dict] = None,
) -> list[dict]:
    """현재 옵션(stocks_query.get_stocks 결과)을 **echo-back** 하는 full-replace 페이로드 조립.

    순수함수(네트워크 없음). ``changes`` 에 지정된 옵션만 재고(colCount)를 교체하고,
    **나머지 옵션은 모든 값을 그대로 보존**한다(옵션 소실 0 — 대상 외 옵션은 손대지 않음).

    Args:
        current_options: get_stocks 반환 리스트. 각 dict 키 =
            {opt_no, opt_nm, dtl_opt_nm, stock, stat, seller_stock_cd, add_prc}.
        changes: {opt_no: new_stock}. 해당 opt_no 옵션의 재고만 new_stock 으로 교체.
            None/빈 dict 면 순수 echo-back(현재값 그대로 되보냄).

    Returns:
        update_option_stocks 입력형 리스트 [{col_value0, col_count, col_opt_price,
        use_yn, col_seller_stock_cd, (opt_no 패스스루)}].

    조회필드 → 수정필드 매핑:
        colCount            ← stock (changes 대상이면 new_stock)
        colSellerStockCd    ← seller_stock_cd
        colOptPrice         ← add_prc (없으면 0)
        colValue0           ← dtl_opt_nm (없으면 opt_nm)
        useYn               ← 'Y' 고정(보존). 품절도 colCount=0 로 표현하고 useYn 은 임의로
                              바꾸지 않는다(옵션 비활성화 방지). prdStckStatCd 기반 자동 N 전환 안 함.

    ⚠️ 매핑 불확실성(라이브 라운드트립 검증 전 자동 무장 금지 — docstring·주석·yaml 명시):
      · colValue0 ↔ 어느 조회필드(mixDtlOptNm/mixOptNm)가 updateProductOption 의 옵션 매칭
        키인지 미확정. 잘못 매핑하면 옵션이 중복/소실될 수 있음 → 라이브에서 되보내기 검증 필요.
      · optionMappingKey 는 재고조회 응답에 없어 생략한다. 만약 updateProductOption 이
        optionMappingKey 를 옵션 식별에 **필수**로 요구하면(라이브 확인), 그 매핑키를 얻는
        별도 상세조회가 선행돼야 한다(현재 미확보 — 이 함수는 colValue0 매칭 가정).
      · useYn 보존 정책(품절=colCount 0, useYn 유지)도 라이브 검증 대상.
    """
    changes = changes or {}
    built: list[dict] = []
    for opt in current_options:
        opt_no = opt.get("opt_no")
        # 재고: 대상이면 교체, 아니면 현재값 echo-back(미상 None → 0 으로 날조하지 않고 예외 유발).
        if opt_no is not None and opt_no in changes:
            col_count = int(changes[opt_no])
        else:
            cur_stock = opt.get("stock")
            if cur_stock is None:
                raise ValueError(
                    f"옵션(opt_no={opt_no}) 현재 재고 미상 — echo-back 불가"
                    "(0 으로 날조 금지). 재고조회 실패/누락 확인 필요.")
            col_count = int(cur_stock)

        col_value0 = opt.get("dtl_opt_nm") or opt.get("opt_nm")
        if col_value0 is None or str(col_value0) == "":
            raise ValueError(
                f"옵션(opt_no={opt_no}) colValue0 매핑 불가 — dtl_opt_nm·opt_nm 모두 공란")

        add_prc = opt.get("add_prc")
        built.append({
            "col_value0": col_value0,
            "col_count": col_count,
            "col_opt_price": int(add_prc) if add_prc is not None else 0,
            "use_yn": "Y",  # 보존(임의 N 전환 금지). 품절은 col_count=0 로 표현.
            "col_seller_stock_cd": opt.get("seller_stock_cd") or "",
            "opt_no": opt_no,  # 패스스루(_build_option_xml 은 무시). 배치 매핑·디버깅용.
        })
    return built


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


@dataclass
class ProductBatchResult:
    """상품 1건 가격+재고 배치(조회→echo-back full-replace→가격) 결과.

    partial 방지를 위해 재고 실패 시 가격은 전송하지 않는다(price_result=None).
    """
    product_id: str
    success: bool
    stock_result: Optional[StockChangeResult] = None
    price_result: Optional["object"] = None   # prices.PriceChangeResult (지연 임포트)
    error_message: Optional[str] = None


def update_product_price_stock(
    product_id: str,
    sel_prc: Optional[int],
    option_changes: Optional[dict] = None,
    *,
    client: Optional[Eleven11Client] = None,
    **_cfg_overrides,
) -> ProductBatchResult:
    """상품 단위 가격+재고 배치 (⚠️ 라이브 검증 전용 도구 — 자동 파이프라인 미배선).

    흐름: stocks_query.get_stocks(현재 옵션 전체) → build_full_replace_from_current
          (echo-back, 대상만 재고 교체) → update_option_stocks(full-replace)
          → (sel_prc 있으면) prices.update_price.

    Args:
        product_id: 11번가 상품번호(prdNo).
        sel_prc: 새 판매가(원, 정수). None 이면 가격 전송 생략(재고만).
        option_changes: {opt_no: new_stock}. 재고를 바꿀 옵션만. None/빈 dict 면 순수
            echo-back(현재 옵션을 값 보존으로 되보냄).

    안전:
      · echo-back — 현재 옵션을 **하나도 잃지 않고** 되보낸다(대상 외 값 보존).
      · partial 방지 — 재고 full-replace 가 실패하면 가격은 전송하지 않는다.
      · 거짓 성공 금지 — resultCode 판정(update_option_stocks·update_price 재사용).

    ⚠️ ⚠️ 이 배치는 **기본적으로 호출되지 않는다**(select_adapters armed 경로에 연결 금지).
       colValue0/optionMappingKey/useYn 매핑이 라이브 라운드트립으로 검증되기 전에는
       자동 무장 금지. SellerAPI 승인·서버IP 없이는 실검증 불가. 수동/검증 도구로만 사용.
    """
    # 지연 임포트(순환 회피 + 도구 전용 강조).
    from shared.platforms.eleven11.stocks_query import get_stocks
    from shared.platforms.eleven11.prices import update_price

    prd = str(product_id or "").strip()
    if not prd:
        raise ValueError("11번가 배치: 상품번호(prdNo) 없음")

    client = client or Eleven11Client()

    # 1) 현재 옵션 전체 조회(실패는 예외로 표면화 — 조용한 0/빈 붕괴 금지).
    current = get_stocks(prd, client=client)
    if not current:
        return ProductBatchResult(
            product_id=prd, success=False,
            error_message="재고조회 결과 옵션 0개 — full-replace 대상 없음(전송 보류).")

    # 2) echo-back 페이로드(대상만 재고 교체, 나머지 값 보존).
    options = build_full_replace_from_current(current, option_changes)

    # 3) 재고 full-replace 전송.
    stock_result = update_option_stocks(prd, options, client=client)
    if not stock_result.success:
        # partial 방지 — 재고 실패면 가격 미전송.
        return ProductBatchResult(
            product_id=prd, success=False, stock_result=stock_result,
            error_message=f"재고 전송 실패(가격 미전송, partial 방지): "
                          f"{stock_result.error_message}")

    # 4) 가격 전송(요청 시).
    price_result = None
    if sel_prc is not None:
        price_result = update_price(prd, int(sel_prc), client=client)
        if not price_result.success:
            return ProductBatchResult(
                product_id=prd, success=False,
                stock_result=stock_result, price_result=price_result,
                error_message=f"가격 전송 실패(재고는 반영됨): "
                              f"{price_result.error_message}")

    return ProductBatchResult(
        product_id=prd, success=True,
        stock_result=stock_result, price_result=price_result)
