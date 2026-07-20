# -*- coding: utf-8 -*-
"""
롯데온 상품 상세조회 API 래퍼 (기존 상품 연동 = 옵션 조회).

공식 엔드포인트(실측): POST /v1/openapi/product/v1/product/detail
    Request: { trGrpCd:"SR", trNo, lrtrNo?, spdNo }
    Response.data.itmLst[] = 단품(옵션) 목록
        · sitmNo   판매자단품번호 = 마켓 옵션ID (예: "LO13640xx_1364003")
        · sitmNm   판매자단품명
        · slStatCd SALE(판매중) / SOUT(품절)
        · slPrc    판매가
        · stkQty   재고수량 (stkMgtYn=N 이면 999,999,999 = 재고 미관리)
        · itmOptLst[] 단품속성: optNm(색상/사이즈)·optVal

역할: 조회·파싱만. 매칭/저장은 상위(uploader/market_fetch)에서.
"""
from __future__ import annotations

import logging
from typing import Optional

from shared.platforms import LOTTEON
from shared.platforms.lotteon.client import LotteonClient


logger = logging.getLogger(__name__)

# stkMgtYn=N (재고 미관리) 일 때 롯데온이 채우는 센티넬 값.
STOCK_UNMANAGED_SENTINEL = 999_999_999


def get_product_detail(
    spd_no: str,
    *,
    client: Optional[LotteonClient] = None,
    tr_no: Optional[str] = None,
    tr_grp_cd: Optional[str] = None,
    lrtr_no: Optional[str] = None,
) -> dict:
    """상품 상세조회 → data(object) 반환. 옵션은 data.itmLst[].

    Args:
        spd_no: 판매자상품번호 (SetChannel.market_product_id)
        client: 주입 클라이언트. None 이면 기본 생성.
        tr_no/tr_grp_cd/lrtr_no: 미지정 시 config(LOTTEON) 값 사용.
    """
    client = client or LotteonClient()
    # ★다계정: trNo 는 계정별 값이어야 한다(전역 config 쓰면 토큰↔trNo 불일치=8888
    #   "인증정보와 요청정보가 일치하지 않습니다"). _lotteon_client 가 주입한 계정 _cfg 우선.
    cfg = getattr(client, "_cfg", None) or LOTTEON
    body = {
        "trGrpCd": tr_grp_cd or cfg.get("tr_grp_cd", "SR"),
        "trNo": tr_no if tr_no is not None else cfg.get("tr_no", ""),
        "lrtrNo": lrtr_no if lrtr_no is not None else cfg.get("lrtr_no", ""),
        "spdNo": str(spd_no),
    }
    resp = client.request(method="POST", path=cfg["paths"]["detail"], body=body)
    # 롯데온: HTTP 200 + returnCode. '0000' 아니면 조회 실패로 표면화(폴백 금지).
    if str(resp.get("returnCode")) not in ("0000", "SUCCESS"):
        raise ValueError(
            f"상품 상세조회 실패 spdNo={spd_no} returnCode={resp.get('returnCode')} "
            f"message={resp.get('message')}"
        )
    return resp.get("data") or {}


def extract_items(detail: dict) -> list[dict]:
    """상세조회 data.itmLst[] → 옵션 리스트 추출.

    Returns:
        [{"item_name","sitm_no","color","size","stock","stock_managed",
          "sale_price","status"}]
        · stock: stkMgtYn=N(미관리) 이면 None(센티넬 999,999,999 을 그대로 노출하지 않음).
        · sale_price: 없으면 None (0 으로 붕괴 금지 — 미상 표면화).
    """
    result = []
    for item in detail.get("itmLst") or []:
        sitm_no = item.get("sitmNo")
        if not sitm_no:
            continue

        # 색상·사이즈: itmOptLst[] 의 optNm 으로 구분 (쿠팡 attributes 와 동형)
        color, size = "", ""
        for opt in item.get("itmOptLst") or []:
            opt_nm = (opt.get("optNm") or "").strip()
            opt_val = (opt.get("optVal") or "").strip()
            if not opt_val:
                continue
            if "색상" in opt_nm and not color:
                color = opt_val
            elif "사이즈" in opt_nm and not size:
                size = opt_val

        # 재고: 미관리(stkMgtYn=N) → None. 관리 → 실수량.
        stk_managed = (item.get("stkMgtYn") or "Y").strip().upper() != "N"
        raw_stk = item.get("stkQty")
        if not stk_managed or raw_stk == STOCK_UNMANAGED_SENTINEL:
            stock = None
        else:
            stock = raw_stk

        sale_price = item.get("slPrc")

        result.append({
            "item_name": item.get("sitmNm"),
            "sitm_no": sitm_no,
            "color": color,
            "size": size,
            "stock": stock,
            "stock_managed": stk_managed,
            "sale_price": sale_price,
            "status": item.get("slStatCd"),   # SALE / SOUT
        })
    return result


def list_products(
    *,
    client: Optional[LotteonClient] = None,
    reg_start: Optional[str] = None,
    reg_end: Optional[str] = None,
    sale_status: Optional[str] = None,
    tr_no: Optional[str] = None,
    tr_grp_cd: Optional[str] = None,
) -> list[dict]:
    """상품 목록 조회 → 상품(dict) 리스트.

    근거: 데이터 코드 지도(판매처 > 데이터 코드 지도 > 상품 조회) 실측 요청형식.
        POST /v1/openapi/product/v1/product/list
        필수: trGrpCd, trNo, regStrtDttm(YYYYMMDDHHMMSS), regEndDttm
        선택: slStrtDttm, slEndDttm, slStatCd [END/SALE/SOUT/STP]

    ⚠️ 응답 필드 스펙은 지도에 비어 있다(res 미확보). 그래서 파싱을 추측하지 않고
       **원본 dict 를 그대로 돌려준다** — 호출부가 실제 응답을 보고 필드를 정한다.
       (실호출로 확인되면 지도의 res 를 채우고 여기 주석도 갱신할 것)

    Args:
        reg_start/reg_end: 등록일 범위. 미지정 시 최근 1년.
        sale_status: 'SALE'(판매중) 등. 미지정 시 전체.
    """
    from datetime import datetime, timedelta

    client = client or LotteonClient()
    cfg = getattr(client, "_cfg", None) or LOTTEON
    now = datetime.now()
    body = {
        "trGrpCd": tr_grp_cd or cfg.get("tr_grp_cd", "SR"),
        "trNo": tr_no if tr_no is not None else cfg.get("tr_no", ""),
        "regStrtDttm": reg_start or (now - timedelta(days=365)).strftime("%Y%m%d%H%M%S"),
        "regEndDttm": reg_end or now.strftime("%Y%m%d%H%M%S"),
    }
    if sale_status:
        body["slStatCd"] = sale_status
    resp = client.request(method="POST", path=cfg["paths"]["list"], body=body)
    if str(resp.get("returnCode")) not in ("0000", "SUCCESS"):
        raise ValueError(
            f"상품 목록 조회 실패 returnCode={resp.get('returnCode')} "
            f"message={resp.get('message')}"
        )
    data = resp.get("data")
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        # 목록 키 이름이 미확보라, 리스트로 보이는 첫 값을 쓴다(있으면).
        for v in data.values():
            if isinstance(v, list):
                return v
        return [data]
    return []
