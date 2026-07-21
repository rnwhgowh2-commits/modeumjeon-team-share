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
    page_no: int = 1,
    rows_per_page: int = 100,
    tr_no: Optional[str] = None,
    tr_grp_cd: Optional[str] = None,
) -> list[dict]:
    """상품 목록 조회 → 상품(dict) 리스트.

    근거: 데이터 코드 지도(판매처 > 데이터 코드 지도 > 상품 조회) 실측 요청형식.
        POST /v1/openapi/product/v1/product/list
        필수: trGrpCd, trNo, regStrtDttm(YYYYMMDDHHMMSS), regEndDttm
        선택: slStrtDttm, slEndDttm, slStatCd [END/SALE/SOUT/STP]

    ★ [2026-07-20 실호출 검증] pageNo·rowsPerPage 가 **필수**다. 지도에 접수된 params
       목록에는 빠져 있어(res 가 플레이스홀더였음) 이것만 없으면 returnCode 9000
       ("처리 중 오류")이 난다 — 권한 문제로 오해하기 쉬우니 주의.
       같은 롯데온 목록 API(product/qna/list)도 pageNo*·rowsPerPage*(MAX 100) 필수.
       검증 결과: returnCode 0000 · dataCount 13,883 · data[] 에 spdNo 등.

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
    body["pageNo"] = int(page_no)
    body["rowsPerPage"] = min(int(rows_per_page), 100)   # 롯데온 상한 100
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


# ──────────────────────────────────────────────────────────────
# [2026-07-21] 상품 등록 — 라이브 실측으로 발굴한 스키마(르무통 테스트 LO2729045338 성공).
#   등록 body = 기존 상품 detail 응답과 동일 구조(지도 명시·실측 확인).
#   ★★ 함정 1: body 는 {"spdLst":[{...}]} 래퍼 필수 — 래퍼 없이 보내면
#       returnCode 9999 + message "정상 처리되었습니다" + data [] 로
#       **0건 접수를 '정상'이라 답한다**(조용한 무시 — 등록 안 됨).
#   ★★ 함정 2: 성공/실패는 최상위 returnCode 가 아니라 **data[] 항목별 resultCode**.
#       최상위 0000 이어도 data[0].resultCode 9999 면 미생성. 성공 = data[0].spdNo 발급.
#   ★ 함정 3: "출고지 번호 필수" 에러의 실제 필드명은 dvpNo 가 아니라 **owhpNo**(출하지).
#       회수지 = rtrpNo. 값은 계약조회(getDvpListSr)의 dvpNo 를 그대로 쓴다.
#   ★ 함정 4: 단품 itmOptLst 의 optNm 은 카테고리 사전값('색상'/'의류 사이즈' 등) —
#       임의 변경('사이즈' 등)하면 "판매옵션정보를 선택해주세요" 로 거부.
#   ★ 지도의 registration/request 가 정답. yaml 의 /product/regist 는 404(미검증 TODO 였음).
# ──────────────────────────────────────────────────────────────

_PATH_REGISTER = "/v1/openapi/product/v1/product/registration/request"

#: 본보기(기존 상품 detail)에서 그대로 복사해야 등록이 통과한 필드(전부 실측).
#: 하나라도 빠지면 롯데온이 항목별 resultMessage 로 그 필드를 짚는다.
_REGISTER_TEMPLATE_FIELDS = (
    "scatNo", "dcatLst", "slTypCd", "pdTypCd", "dvCstPolNo",
    "tdfDvsCd", "pdStatCd", "ageLmtCd", "dvPdTypCd", "oplcCd", "sitmYn",
    "pdItmsInfo", "purPsbQtyInfo", "epnLst",
    "dvProcTypCd", "dvMnsCd", "dmstOvsDvDvsCd", "dvRgsprGrpCd", "dvCstStdQty",
    "owhpNo", "rtrpNo", "hdcCd", "rtngHdcCd",
)


def _register_dttm(v) -> str:
    """detail 표기('2026-07-21 00:00:00')→등록 요구 형식 YYYYMMDDHH24MISS(숫자만)."""
    import re as _re2
    return _re2.sub(r"[^0-9]", "", str(v or ""))[:14]


def build_register_payload(
    *,
    template: dict,
    spd_nm: str,
    price: int,
    stock: int,
    item_name: Optional[str] = None,
) -> dict:
    """기존 상품 detail(template)을 본보기로 등록용 상품 1건(dict)을 조립한다.

    Args:
        template: get_product_detail() 결과 — 같은 계정·같은 카테고리 상품이어야
            카테고리/고시/배송/출하지 값이 그대로 통한다.
        spd_nm/price/stock: 새 상품명·판매가(10원 단위)·재고.
        item_name: 단품명(미지정 시 본보기 단품명 유지 — optNm/optVal 은 사전값이라
            임의 변경 금지, 본보기 원값을 쓴다).

    Returns:
        spdLst 항목 1개(dict). register_product() 에 넘긴다.

    Raises:
        ValueError: 본보기에 필수 필드가 없을 때(추측·폴백 금지 — 다른 본보기를 쓸 것).
    """
    from datetime import datetime as _dt3

    if not isinstance(template, dict) or not template:
        raise ValueError("롯데온 등록: template(기존 상품 detail) 필수")
    inner: dict = {}
    missing = []
    for k in _REGISTER_TEMPLATE_FIELDS:
        v = template.get(k)
        if v is None:
            missing.append(k)
        else:
            inner[k] = v
    if missing:
        raise ValueError(
            f"롯데온 등록: 본보기에 필수 필드 없음 — {missing} (다른 기존 상품을 본보기로)")

    itm_tpl = (template.get("itmLst") or [None])[0]
    if not isinstance(itm_tpl, dict):
        raise ValueError("롯데온 등록: 본보기 itmLst 가 비어 있음")
    itm = {k: v for k, v in itm_tpl.items() if k not in ("sitmNo", "eitmNo")}
    itm["slPrc"] = int(price)
    itm["stkQty"] = int(stock)
    if item_name:
        itm["sitmNm"] = str(item_name)
    if itm.get("sortSeq") is None:
        itm["sortSeq"] = 1

    inner["spdNm"] = str(spd_nm)
    inner["itmLst"] = [itm]
    now = _dt3.now()
    inner["slStrtDttm"] = now.strftime("%Y%m%d%H%M%S")
    inner["slEndDttm"] = "20991231235959"
    return inner


def register_product(inner: dict, *, client: Optional[LotteonClient] = None) -> dict:
    """상품 등록 — POST registration/request, body={"spdLst":[inner]}.

    trGrpCd/trNo 는 계정 client._cfg 에서 강제 주입(★전역 config 쓰면 8888).
    성공판정 = data[0].spdNo 발급만(거짓 성공 금지).
    """
    client = client or LotteonClient()
    cfg = getattr(client, "_cfg", None) or LOTTEON
    inner = dict(inner)
    inner["trGrpCd"] = cfg.get("tr_grp_cd", "SR")
    inner["trNo"] = cfg.get("tr_no", "")
    resp = client.request(method="POST", path=_PATH_REGISTER, body={"spdLst": [inner]})
    data = resp.get("data")
    item = data[0] if isinstance(data, list) and data and isinstance(data[0], dict) else {}
    spd_no = item.get("spdNo")
    if not spd_no:
        raise ValueError(
            "롯데온 등록 실패(거짓 성공 금지): "
            f"항목결과={item.get('resultCode')} {str(item.get('resultMessage'))[:200]} / "
            f"최상위={resp.get('returnCode')} {str(resp.get('message'))[:100]}")
    return {"spdNo": spd_no, "resultCode": item.get("resultCode"),
            "resultMessage": item.get("resultMessage"), "raw": item}


def set_sale_status(spd_no: str, sl_stat_cd: str, *, client: Optional[LotteonClient] = None) -> bool:
    """상품 판매상태 변경 — POST status/change, slStatCd [SALE/SOUT/END].

    판매중단 = END(판매종료)/SOUT(품절). 재고 0 으로는 못 내린다(롯데온 규격).
    반환 True 여도 호출부가 get_product_detail 로 slStatCd 재조회 검증 권장.
    """
    client = client or LotteonClient()
    cfg = getattr(client, "_cfg", None) or LOTTEON
    body = {"spdLst": [{"trGrpCd": cfg.get("tr_grp_cd", "SR"),
                        "trNo": cfg.get("tr_no", ""),
                        "spdNo": str(spd_no), "slStatCd": str(sl_stat_cd)}]}
    resp = client.request(method="POST",
                          path="/v1/openapi/product/v1/product/status/change", body=body)
    return str(resp.get("returnCode")) in ("0000", "SUCCESS")
