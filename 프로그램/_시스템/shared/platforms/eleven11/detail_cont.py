# -*- coding: utf-8 -*-
"""11번가 **상품상세 설명** 조회·수정 — 전용 API.

정본 스펙(셀러 오픈API센터 · 2026-08-12 사장님이 직접 받아 주심):
  · 조회  GET  /rest/prodservices/getProductDetailCont/[prdNo]
          응답 <ProductDetailCont><prdDescContClob>…</prdDescContClob></ProductDetailCont>
  · 수정  POST /rest/prodservices/updateProductDetailCont/[prdNo]
          본문 같은 봉투. **성공 응답이 빈 `<Product/>`** 다.

🎯 왜 이게 중요한가 — 상품수정(PUT /rest/prodservices/product/{prdNo})은 문서 원문에
   「기존 데이터는 사라지고 수정되는 정보로 교체됩니다」라고 적힌 **전체 교체**다.
   상세 한 줄을 바꾸려고 필수 30여 개를 되돌려 보내다 하나라도 빠지면 그 값이 지워진다.
   이 전용 API 는 그 위험을 통째로 피한다.

🔴🔴 수정 성공 응답에 resultCode 도 message 도 없다(빈 `<Product/>`).
   성공 판정 근거가 응답에 없으므로 **되읽기가 유일한 검증 수단**이다.
   「보냈으니 됐다」로 적으면 거짓 보고가 된다.
"""
from __future__ import annotations

import re as _re
import xml.etree.ElementTree as _ET
from typing import Optional

from shared.platforms.eleven11.client import Eleven11Client

_PATH_GET = "/rest/prodservices/getProductDetailCont/{prd_no}"
_PATH_PUT = "/rest/prodservices/updateProductDetailCont/{prd_no}"
_FIELD = "prdDescContClob"


def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _root_name(xml_text: str) -> Optional[str]:
    """최상위 봉투 이름. 🔴 성공은 `Product`, 에러는 `Products`(복수) — 한 글자 차이다."""
    cleaned = _re.sub(r"<\?xml[^>]*\?>", "", xml_text or "", count=1).strip()
    if not cleaned:
        return None
    try:
        return _localname(_ET.fromstring(cleaned).tag)
    except _ET.ParseError:
        return None


def _find_text(xml_text: str, name: str) -> Optional[str]:
    cleaned = _re.sub(r"<\?xml[^>]*\?>", "", xml_text or "", count=1).strip()
    if not cleaned:
        return None
    try:
        root = _ET.fromstring(cleaned)
    except _ET.ParseError:
        return None
    if _localname(root.tag) == name:
        return root.text or ""
    for el in root.iter():
        if _localname(el.tag) == name:
            return el.text or ""
    return None


def get_detail_html(
    product_id: str,
    *,
    client: Optional[Eleven11Client] = None,
) -> Optional[str]:
    """상품상세 설명(HTML). 못 읽으면 None — 빈 문자열로 「상세 없음」을 지어내지 않는다.

    🔴 성공 봉투는 `ProductDetailCont`, 에러 봉투는 `Products><message` 로 다르다.
       봉투 이름으로 갈라야 에러를 상세 내용으로 착각하지 않는다.
    """
    prd = str(product_id or "").strip()
    if not prd:
        raise ValueError("11번가 상세조회: 상품번호(prdNo) 없음")
    client = client or Eleven11Client()
    xml_text = client.request("GET", _PATH_GET.format(prd_no=prd))
    return _find_text(xml_text or "", _FIELD)


def update_detail_html(
    product_id: str,
    html: str,
    *,
    client: Optional[Eleven11Client] = None,
) -> None:
    """상품상세 설명을 바꾼다. 실패는 예외.

    🔴 [2026-08-12 라이브] **성공에도 message 가 온다.**
       「상품 상세 내용이 수정되었습니다.」를 실패로 읽어 왕복이 통째로 죽었다.
       문서의 성공 예제는 빈 `<Product/>` 였는데, 같은 문서 「출력 결과 필드」표엔
       `message`(결과내용)가 **필수(O)** 로 적혀 있다 — 예제만 보고 필드표를 안 봤다.
       ⚠️ 예제와 필드표가 어긋나면 **필드표가 더 정확하다**(예제는 자주 낡는다).

    성공/실패는 **봉투 이름으로 가른다** — 성공 `Product`, 에러 `Products`(복수).
    낱말 판정은 하지 않는다(마켓이 문구를 바꾸면 조용히 깨진다).
    ⚠️ 그래도 최종 확인은 호출부의 되읽기다 — 그게 유일하게 확실한 검증 수단이다.
    """
    prd = str(product_id or "").strip()
    if not prd:
        raise ValueError("11번가 상세수정: 상품번호(prdNo) 없음")
    if html is None:
        raise ValueError("11번가 상세수정: 내용이 None — 지어내지 않고 멈춥니다")
    client = client or Eleven11Client()
    # 🔴 client 가 본문을 euc-kr 로 인코딩한다 — 선언도 euc-kr 로 맞춰야 한글이 안 깨진다
    #    (2026-07-21 실측: 불일치 시 "Invalid UTF-8 start byte" 500).
    body = ('<?xml version="1.0" encoding="euc-kr"?>'
            f"<ProductDetailCont><{_FIELD}><![CDATA[{html}]]></{_FIELD}></ProductDetailCont>")
    resp = client.request(method="POST", path=_PATH_PUT.format(prd_no=prd), body=body)
    if _root_name(resp or "") == "Products":       # 복수 = 에러 봉투
        msg = _find_text(resp or "", "message") or ""
        raise RuntimeError(f"11번가 상세수정 실패 prdNo={prd}: {msg[:200]}")
