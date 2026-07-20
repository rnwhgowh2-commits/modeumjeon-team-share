# -*- coding: utf-8 -*-
"""
11번가 상품 조회 래퍼 (상품 단위 정보 — 판매가 등).

정본 스펙(셀러 오픈API센터 · 2026-07-17):
  · 신규 상품 조회: GET /rest/prodmarketservice/prodmarket/[prdNo] → <Product>...<selPrc>..
    응답 필드 selPrc=판매가(상품 단위). 옵션별 재고/식별자는 stocks_query 로 조회한다.

주의: 옵션(단품)별 상세·재고는 이 엔드포인트가 아니라 stocks_query.get_stocks 를 쓴다
      (이 엔드포인트는 상품 단위 — selPrc·판매상태 등).
"""
from __future__ import annotations

import re as _re
import xml.etree.ElementTree as _ET
from typing import Optional

from shared.platforms.eleven11.client import Eleven11Client

_PATH_DETAIL = "/rest/prodmarketservice/prodmarket/{prd_no}"


def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def get_product_detail(
    product_id: str,
    *,
    client: Optional[Eleven11Client] = None,
    **_cfg_overrides,
) -> dict:
    """상품 조회 → <Product> 필드 dict. GET prodmarket/{prdNo}.

    반환: {prd_no, prd_nm, sel_prc(int|None), sel_stat_cd, ...주요필드}.
    파싱 실패는 예외로 표면화(추측·폴백 금지).
    """
    prd = str(product_id or "").strip()
    if not prd:
        raise ValueError("11번가 상품조회: 상품번호(prdNo) 없음")
    client = client or Eleven11Client()
    xml_text = client.request("GET", _PATH_DETAIL.format(prd_no=prd))
    cleaned = _re.sub(r"<\?xml[^>]*\?>", "", xml_text or "", count=1).strip()
    if not cleaned:
        raise ValueError("11번가 상품조회: 빈 응답")
    try:
        root = _ET.fromstring(cleaned)
    except _ET.ParseError as e:
        raise ValueError(f"11번가 상품조회: XML 파싱 실패 — {e}: {cleaned[:200]}")
    # <Product> 직속 자식만 상품 필드로(옵션/태그 하위는 무시). localname 매핑.
    f: dict = {}
    for child in list(root):
        f.setdefault(_localname(child.tag), (child.text or "").strip())

    def _int(v):
        v = (v or "").strip()
        return int(v) if v not in ("", None) and v.lstrip("-").isdigit() else None

    return {
        "prd_no": f.get("prdNo") or prd,
        "prd_nm": f.get("prdNm") or None,
        "sel_prc": _int(f.get("selPrc")),      # 판매가(상품 단위)
        "sel_stat_cd": f.get("selStatCd") or None,   # 103=판매중 등
        "sel_stat_nm": f.get("selStatNm") or None,
        "message": f.get("message") or None,
    }


def get_product_price(
    product_id: str,
    *,
    client: Optional[Eleven11Client] = None,
) -> Optional[int]:
    """상품 현재 판매가(selPrc) 조회. 미상은 None(0 날조 금지)."""
    return get_product_detail(product_id, client=client).get("sel_prc")


def extract_items(detail) -> list[dict]:
    """옵션(단품) 리스트는 이 엔드포인트가 아니라 stocks_query.get_stocks 를 쓴다."""
    raise NotImplementedError(
        "11번가 옵션별 재고/식별자는 stocks_query.get_stocks(prdNo) 를 사용하세요 "
        "(prodmarket/{prdNo} 상품조회는 상품 단위 — selPrc 만).")


_PATH_SEARCH = "/rest/prodmarketservice/prodmarket"


def search_products(
    *,
    client: Optional[Eleven11Client] = None,
    name: Optional[str] = None,
    sale_status: Optional[str] = None,
    limit: int = 100,
    start: Optional[int] = None,
    end: Optional[int] = None,
    date_type: Optional[str] = None,
    begin_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> list[dict]:
    """다중 상품 조회(= 조건 검색) → 상품 dict 리스트.

    근거: 데이터 코드 지도(판매처 > 데이터 코드 지도 > 상품 조회 > 11번가 「다중 상품 조회」).
        POST /rest/prodmarketservice/prodmarket · XML 요청/응답
        필수: SearchProduct(루트), limit
        선택: prdNo, prdNm(상품명), selStatCd(판매상태), selMthdCd(판매형태),
              schDateType + schBgnDt/schEndDt(기간은 반드시 타입과 동반), start, end

    판매상태 코드: 103=판매중 / 104=품절 / 101=승인대기 / 102=승인전
                  105=전시중지 / 106=판매정상종료 / 108=판매금지

    ⚠️ limit 이 빠지면 안 된다(필수). 기간을 줄 때는 schDateType 을 반드시 함께 준다 —
       한쪽만 주면 11번가가 거부한다(지도 명시).
    """
    client = client or Eleven11Client()
    parts = [f"<limit>{int(limit)}</limit>"]
    if name:
        parts.append(f"<prdNm>{_esc(name)}</prdNm>")
    if sale_status:
        parts.append(f"<selStatCd>{_esc(sale_status)}</selStatCd>")
    if start is not None:
        parts.append(f"<start>{int(start)}</start>")
    if end is not None:
        parts.append(f"<end>{int(end)}</end>")
    if date_type and begin_date and end_date:
        parts.append(f"<schDateType>{_esc(date_type)}</schDateType>")
        parts.append(f"<schBgnDt>{_esc(begin_date)}</schBgnDt>")
        parts.append(f"<schEndDt>{_esc(end_date)}</schEndDt>")
    body = ('<?xml version="1.0" encoding="UTF-8"?>'
            "<SearchProduct>" + "".join(parts) + "</SearchProduct>")
    xml = client.request(method="POST", path=_PATH_SEARCH, body=body)
    return _parse_products(xml)


def _esc(v) -> str:
    return (str(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _parse_products(xml: str) -> list[dict]:
    """응답 XML → 상품 dict 리스트. 네임스페이스(ns2:)는 로컬명으로 벗긴다.

    ⚠️ 응답 실측 스펙은 지도에 미확보(sample 비어 있음)라 필드를 추측해 뽑지 않는다.
       각 product 요소의 **자식 전부**를 그대로 dict 로 돌려주고, 호출부가 실제로 보고 정한다.
    """
    try:
        root = _ET.fromstring(xml)
    except _ET.ParseError:
        return []
    out: list[dict] = []
    for el in root.iter():
        if _localname(el.tag) != "product":
            continue
        row = {}
        for c in el:
            row[_localname(c.tag)] = (c.text or "").strip()
        if row:
            out.append(row)
    return out
