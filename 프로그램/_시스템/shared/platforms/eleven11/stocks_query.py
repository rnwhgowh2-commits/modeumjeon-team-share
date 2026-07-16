# -*- coding: utf-8 -*-
"""
11번가 다중 상품 재고정보 조회 API 래퍼 (현재 옵션 읽기).

★ 확보 스펙(셀러 OPEN API CENTER, 정본 · 2026-07-16):
  POST http://api.11st.co.kr/rest/prodmarketservice/prodmarket/stocks
    · 헤더 openapikey. 요청·응답 XML(euc-kr). 요청에 prdNo(상품번호)를 담는다.
    · 응답(ns2: 네임스페이스): <ProductStocks> 하위 <ProductStock> 반복(옵션마다 1요소).
      필드:
        mixOptNo      옵션번호
        mixOptNm      옵션명
        mixDtlOptNm   상세옵션명
        stckQty       재고수량(정수)
        prdStckStatCd 재고상태 enum
        sellerStockCd 셀러재고번호
        addPrc        옵션가격(기본가 대비 +/-)
        selQty        판매수량
        prdStckNo     재고번호
      (추가구성품 productComponent/addCompPrc 등은 옵션 재고와 분리 — 여기선 무시.)

용도: 옵션 full-replace 전송 전에 **현재 옵션 전체**를 읽어 echo-back 하기 위한 조회.
  inventory.build_full_replace_from_current 과 짝을 이룬다.

정책(CLAUDE.md): 파싱 실패를 조용히 0/빈 리스트로 붕괴시키지 않는다 → 예외로 표면화.
  재고 미상을 999/센티넬로 날조하지 않는다.

⚠️ 라이브 미검증(SellerAPI 승인·서버IP 필요) — 요청 본문 래퍼 엘리먼트(prdNo 를 감싸는
   루트명)와 ns2 네임스페이스 프리픽스는 라이브 라운드트립에서 확정 대상. localname 으로
   파싱해 프리픽스 변동에는 견고하다.
"""
from __future__ import annotations

import logging
import re as _re
import xml.etree.ElementTree as _ET
from typing import Optional

from shared.platforms.eleven11.client import Eleven11Client

logger = logging.getLogger(__name__)

_PATH_STOCKS = "/rest/prodmarketservice/prodmarket/stocks"


def _localname(tag: str) -> str:
    """'{ns}ProductStock' → 'ProductStock' (네임스페이스 제거). prices.py 패턴 재사용."""
    return tag.rsplit("}", 1)[-1]


def _build_request_xml(product_id: str) -> str:
    """조회 요청 XML(prdNo 만, euc-kr 선언).

    ★라이브 확정(2026-07-17): 요청 본문은 래퍼 없이 <prdNo>만. <ProductStocks> 래퍼로
      감싸면 "재고 정보 조회 오류"를 반환하고, 래퍼 없이 <prdNo> 만 보내면 정상 조회된다.
      (응답 래퍼는 ns2:ProductStockss — 파서는 localname 으로 ProductStock 만 순회.)
    """
    return ('<?xml version="1.0" encoding="euc-kr"?>'
            f"<prdNo>{product_id}</prdNo>")


def _to_int(text: str) -> Optional[int]:
    """재고수량 등 정수 파싱. 공란은 None(미상 — 0 으로 날조 금지)."""
    s = (text or "").strip()
    if s == "":
        return None
    return int(s)


def _parse_stocks(xml_text: str) -> list[dict]:
    """<ProductStocks><ProductStock>... XML → 옵션 dict 리스트.

    파싱 실패(빈 응답·XML 오류)는 예외로 표면화(조용한 빈 리스트 붕괴 금지).
    """
    cleaned = _re.sub(r"<\?xml[^>]*\?>", "", xml_text or "", count=1).strip()
    if not cleaned:
        raise ValueError("11번가 재고조회: 빈 응답(옵션 없음으로 오판 금지)")
    try:
        root = _ET.fromstring(cleaned)
    except _ET.ParseError as e:
        raise ValueError(f"11번가 재고조회: 응답 XML 파싱 실패 — {e}: {cleaned[:200]}")

    options: list[dict] = []
    for el in root.iter():
        if _localname(el.tag) != "ProductStock":
            continue
        f: dict = {}
        for child in el:
            f[_localname(child.tag)] = (child.text or "").strip()
        options.append({
            "opt_no": f.get("mixOptNo") or None,
            "opt_nm": f.get("mixOptNm") or None,
            "dtl_opt_nm": f.get("mixDtlOptNm") or None,
            "stock": _to_int(f.get("stckQty", "")),
            "stat": f.get("prdStckStatCd") or None,
            "seller_stock_cd": f.get("sellerStockCd") or None,
            "add_prc": _to_int(f.get("addPrc", "")),
        })
    return options


def get_stocks(
    product_id: str,
    *,
    client: Optional[Eleven11Client] = None,
    **_cfg_overrides,
) -> list[dict]:
    """상품(prdNo)의 현재 옵션 재고정보 전체를 조회한다.

    POST /rest/prodmarketservice/prodmarket/stocks (prdNo 담은 XML 본문).
    반환: 옵션 dict 리스트 [{opt_no, opt_nm, dtl_opt_nm, stock(int|None), stat,
                            seller_stock_cd, add_prc(int|None)}].
    파싱 실패는 예외(조용한 0/빈 리스트 붕괴 금지).
    """
    prd = str(product_id or "").strip()
    if not prd:
        raise ValueError("11번가 재고조회: 상품번호(prdNo) 없음")

    client = client or Eleven11Client()
    body = _build_request_xml(prd)
    xml_text = client.request("POST", _PATH_STOCKS, body)
    options = _parse_stocks(xml_text)
    logger.debug("[11번가] 재고조회 prdNo=%s 옵션=%d개", prd, len(options))
    return options
