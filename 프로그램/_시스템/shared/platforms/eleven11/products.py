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
