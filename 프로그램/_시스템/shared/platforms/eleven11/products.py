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
        # [2026-07-23 M3 Task 6] 등록 당시 고른 카테고리 번호(dispCtgrNo · 최하위 카테고리).
        #   파서가 이미 <Product> 자식을 전부 f 에 담고 있는데 6개만 돌려주고 버리던 값이다.
        #   ⚠️ 단건 GET 응답에 dispCtgrNo 가 실려 오는지는 라이브 미확정 — 지도가 이 필드를
        #      명시한 원천은 「다중 상품 조회」(POST prodmarket) 응답이다. 없으면 None 이고,
        #      되찾기는 get_display_category_no() 가 다중 조회로 한 번 더 묻는다(날조 금지).
        "disp_ctgr_no": (f.get("dispCtgrNo") or "").strip() or None,
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
    prd_no: Optional[str] = None,
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
    if prd_no:
        # 지도 요청 파라미터 '요청.prdNo'(상품번호) — 한 상품만 되받을 때 쓴다.
        parts.append(f"<prdNo>{_esc(prd_no)}</prdNo>")
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
    # ★ client 가 body 를 euc-kr 로 인코딩(client.py)한다 — 선언도 euc-kr 로 일치시켜야
    #   한글 검색어가 "Invalid UTF-8 start byte" 500 을 안 낸다(2026-07-21 실측).
    body = ('<?xml version="1.0" encoding="euc-kr"?>'
            "<SearchProduct>" + "".join(parts) + "</SearchProduct>")
    xml = client.request(method="POST", path=_PATH_SEARCH, body=body)
    return _parse_products(xml)


def get_display_category_no(
    product_id: str,
    *,
    client: Optional[Eleven11Client] = None,
) -> Optional[str]:
    """[2026-07-23 M3 Task 6] 등록된 상품의 카테고리 번호(dispCtgrNo). 없으면 None.

    ① 단건 상품조회(GET prodmarket/{prdNo}) 응답에 dispCtgrNo 가 있으면 그대로 쓴다.
    ② 없으면 지도가 이 필드를 명시한 원천인 「다중 상품 조회」(POST prodmarket, prdNo 조건)로
       한 번 더 묻는다. 둘 다 없으면 None — 0/빈값으로 날조하지 않는다(맵핑은 '확인불가'로 남음).
    """
    prd = str(product_id or "").strip()
    if not prd:
        return None
    client = client or Eleven11Client()
    try:
        code = get_product_detail(prd, client=client).get("disp_ctgr_no")
    except Exception:  # noqa: BLE001 — 단건 실패는 다중 조회로 한 번 더 시도(사유는 상위가 집계)
        code = None
    if code:
        return str(code)
    for row in search_products(client=client, prd_no=prd, limit=1) or []:
        if str(row.get("prdNo") or "").strip() not in ("", prd):
            continue   # 조건이 안 먹어 다른 상품이 섞여 오면 그 행은 쓰지 않는다
        got = (row.get("dispCtgrNo") or "").strip()
        if got:
            return got
    return None


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


# ──────────────────────────────────────────────────────────────
# [2026-07-21] 신규 상품 등록 / 전시중지 / 출고지조회 — 지도 실측 스펙
#   등록: POST /rest/prodservices/product (XML <Product>, 필수 93 중 상시필수만)
#   전시중지: PUT /rest/prodstatservice/stat/stopdisplay/{prdNo} — 재고 0 불가라 이것이 유일한 판매중단
#   출고지: GET /rest/areaservice/outboundarea — addrSeqOut/addrSeqIn 수확용
# ──────────────────────────────────────────────────────────────

_PATH_OUTBOUND = "/rest/areaservice/outboundarea"
_PATH_REGISTER = "/rest/prodservices/product"
_PATH_STOP_DISPLAY = "/rest/prodstatservice/stat/stopdisplay/{prd_no}"


def _flat_fields(xml_text: str) -> dict:
    """응답 XML 전 요소를 {로컬명: 텍스트} 로 평탄화(마지막 값 우선 아님 — 첫 값 유지)."""
    cleaned = _re.sub(r"<\?xml[^>]*\?>", "", xml_text or "", count=1).strip()
    if not cleaned:
        return {}
    try:
        root = _ET.fromstring(cleaned)
    except _ET.ParseError:
        return {}
    f: dict = {}
    for el in root.iter():
        if (el.text or "").strip():
            f.setdefault(_localname(el.tag), el.text.strip())
    return f


def _cdata(v) -> str:
    return "<![CDATA[" + str(v if v is not None else "") + "]]>"


def get_outbound_areas_xml(*, client: Optional[Eleven11Client] = None) -> str:
    """판매자 출고지/반품지 주소 조회 — 응답 XML **원문** 반환.

    응답 필드 실측 스펙이 지도에 미확보(sample 빈)라 파싱하지 않고 원문을 돌려준다
    (추측 금지 — 호출부/사람이 보고 addrSeq 를 정한다).
    """
    client = client or Eleven11Client()
    return client.request("GET", _PATH_OUTBOUND)


def build_register_xml(f: dict) -> str:
    """신규 상품 등록 XML 조립 — 무옵션·무료배송·일반상품 최소 필수 세트.

    지도 「신규 상품 등록」(POST /rest/prodservices/product · params 235 · 필수 93) 중
    상시 필수만 채운다. 조건부 섹션(옵션·사은품·인증·의료기기·추가상품)은 만들지 않는다.
    필수 재료가 비면 ValueError(추측·폴백 금지).
    """
    def req(k):
        v = f.get(k)
        if v in (None, ""):
            raise ValueError(f"11번가 등록: 필수 재료 없음 — {k}")
        return v

    parts = [
        "<selMthdCd>01</selMthdCd>",                       # 판매방식: 고정가판매
        f"<dispCtgrNo>{_esc(req('disp_ctgr_no'))}</dispCtgrNo>",  # 최하위 카테고리
        "<prdTypCd>01</prdTypCd>",                         # 일반배송상품
        f"<prdNm>{_cdata(req('prd_nm'))}</prdNm>",
        f"<brand>{_cdata(req('brand'))}</brand>",
        "<rmaterialTypCd>04</rmaterialTypCd>",             # 원산지 의무 표시대상 아님
        "<orgnTypCd>03</orgnTypCd>",                       # 원산지: 기타(원산지명 입력)
        "<orgnNmVal>상세설명 참조</orgnNmVal>",
        "<suplDtyfrPrdClfCd>01</suplDtyfrPrdClfCd>",       # 과세상품
        "<forAbrdBuyClf>01</forAbrdBuyClf>",               # 일반판매상품
        "<prdStatCd>01</prdStatCd>",                       # 새상품
        "<minorSelCnYn>Y</minorSelCnYn>",                  # 미성년자 구매가능
        f"<prdImage01>{_esc(req('image_url'))}</prdImage01>",
        f"<htmlDetail>{_cdata(req('detail_html'))}</htmlDetail>",
        f"<selPrc>{int(req('price'))}</selPrc>",           # 10원 단위·10억 미만
        f"<prdSelQty>{int(req('stock'))}</prdSelQty>",     # 재고(0 불가)
        f"<asDetail>{_cdata(req('as_detail'))}</asDetail>",  # 공백 불가
        "<dlvCnAreaCd>01</dlvCnAreaCd>",                   # 배송가능지역: 전국
        "<dlvWyCd>01</dlvWyCd>",                           # 배송방법: 택배
        "<dlvCstInstBasiCd>01</dlvCstInstBasiCd>",         # 배송비: 무료
        "<dlvCstPayTypCd>03</dlvCstPayTypCd>",             # 선결제
        "<bndlDlvCnYn>N</bndlDlvCnYn>",                    # 묶음배송 불가
        "<jejuDlvCst>0</jejuDlvCst>",
        "<islandDlvCst>0</islandDlvCst>",
        f"<addrSeqOut>{_esc(req('addr_seq_out'))}</addrSeqOut>",   # 출고지 주소코드
        f"<addrSeqIn>{_esc(req('addr_seq_in'))}</addrSeqIn>",      # 반품/교환지 주소코드
        f"<rtngdDlvCst>{int(f.get('return_cost') or 0)}</rtngdDlvCst>",   # 반품배송비(편도)
        f"<exchDlvCst>{int(f.get('exchange_cost') or 0)}</exchDlvCst>",   # 교환배송비(왕복)
    ]
    # 판매기간 — 등록 실측: aplBgnDy 누락 시 "판매시작일이 누락되었습니다" 500.
    #   형식은 지도 example 'YYYY/MM/DD'. 기본 = 오늘 ~ +3년(기존 상품 실측 3년 스팬).
    import datetime as _dtm
    _today = _dtm.date.today()
    apl_bgn = f.get("apl_bgn_dy") or _today.strftime("%Y/%m/%d")
    apl_end = f.get("apl_end_dy") or _today.replace(year=_today.year + 3).strftime("%Y/%m/%d")
    parts.append(f"<aplBgnDy>{_esc(apl_bgn)}</aplBgnDy>")
    parts.append(f"<aplEndDy>{_esc(apl_end)}</aplEndDy>")
    # 옵션(선택형 싱글옵션) — colValue0 에 "색상/사이즈" 조합값(지도 example '파랑/XXL').
    #   멀티옵션은 API 로 옵션별 재고 불가(일괄만)라 싱글옵션이 정답. 옵션 있으면
    #   colCount 가 옵션별 재고, prdSelQty 는 총재고(옵션합)로 둔다.
    opts = f.get("options") or []
    if opts:
        parts.append("<optSelectYn>Y</optSelectYn>")
        parts.append(f"<colTitle>{_cdata('색상/사이즈')}</colTitle>")
        for o in opts:
            val = f"{o.get('color') or ''}/{o.get('size') or ''}".strip("/")
            po = ["<ProductOption>",
                  f"<colOptPrice>{int(o.get('extra_price') or 0)}</colOptPrice>",
                  f"<colValue0>{_cdata(val)}</colValue0>",
                  f"<colCount>{int(o.get('stock') or 0)}</colCount>",
                  "<useYn>Y</useYn>"]
            if o.get("sku"):
                po.append(f"<colSellerStockCd>{_cdata(o['sku'])}</colSellerStockCd>")
            po.append("</ProductOption>")
            parts.append("".join(po))
    # 상품정보제공고시 — 실측 500 "상품고시항목이 입력되지 않았습니다" 필수.
    #   구조(지도 실측): <ProductNotification><type>유형코드</type>
    #                    <item><code>항목코드</code><name>항목값</name></item>...</ProductNotification>
    #   유형/항목 코드는 카테고리별(첨부파일) — 호출부가 notification 으로 주입한다.
    noti = f.get("notification") or {}
    if noti.get("type"):
        items_xml = "".join(
            f"<item><code>{_esc(it.get('code'))}</code>"
            f"<name>{_cdata(it.get('name'))}</name></item>"
            for it in (noti.get("items") or []))
        parts.append(f"<ProductNotification><type>{_esc(noti['type'])}</type>"
                     f"{items_xml}</ProductNotification>")
    # 추가 필드 통로 — 마켓이 더 요구하는 단순 필드를 재배포 없이 붙인다({태그: 값}).
    for k, v in (f.get("extra") or {}).items():
        parts.append(f"<{k}>{_esc(v)}</{k}>")
    # ★ client 가 body 를 euc-kr 로 인코딩한다 — 선언 불일치 시 한글에서 500(실측).
    return ('<?xml version="1.0" encoding="euc-kr"?>'
            "<Product>" + "".join(parts) + "</Product>")


def register_product(xml_body: str, *, client: Optional[Eleven11Client] = None) -> dict:
    """신규 상품 등록 — POST /rest/prodservices/product.

    ★ 성공판정 = 응답에 productNo 존재. HTTP 200/resultCode 만 믿지 않는다(거짓 성공 금지).
      resultCode: 200=성공 / 210=신규등록(승인대기) / 500=에러 / 400=한도초과.
      210 도 정책위배면 200(일반)으로 강등되니 productNo 수령이 유일한 성공 근거.
    """
    client = client or Eleven11Client()
    resp = client.request("POST", _PATH_REGISTER, body=xml_body)
    fields = _flat_fields(resp)
    product_no = (fields.get("productNo") or "").strip()
    if not product_no:
        raise ValueError(
            f"11번가 등록 응답에 productNo 없음 — 실패로 처리(거짓 성공 금지): {resp[:300]}")
    return {"productNo": product_no,
            "resultCode": fields.get("resultCode"),
            "message": fields.get("message"),
            "raw": resp[:500]}


def stop_display(prd_no: str, *, client: Optional[Eleven11Client] = None) -> dict:
    """전시중지(판매중단) — PUT /rest/prodstatservice/stat/stopdisplay/{prdNo}.

    11번가는 재고 0 불가 → 판매중단=전시중지(selStatCd 105)가 유일한 길.
    성공해도 호출부가 get_product_detail 로 selStatCd==105 재조회 검증할 것.
    """
    prd = str(prd_no or "").strip()
    if not prd:
        raise ValueError("11번가 전시중지: prdNo 없음")
    client = client or Eleven11Client()
    resp = client.request("PUT", _PATH_STOP_DISPLAY.format(prd_no=prd))
    out = _flat_fields(resp)
    out["raw"] = (resp or "")[:400]
    return out
