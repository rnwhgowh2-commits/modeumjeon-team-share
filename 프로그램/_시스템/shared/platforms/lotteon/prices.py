# -*- coding: utf-8 -*-
"""
롯데온 가격 변경 API 래퍼.

공식 엔드포인트(실측): POST /v1/openapi/product/v1/item/price/change
    Request: { "itmPrcLst": [ { trGrpCd, trNo, lrtrNo?, spdNo, sitmNo,
                                 slPrc, itmDcTypCd, hstStrtDttm, hstEndDttm }, ... ] }
    Response: { returnCode, message, data: [ { spdNo, sitmNo, resultCode, resultMessage }, ... ] }

정책 (CLAUDE.md):
- 가격은 실브라우저 소싱처 URL 실값 기준. 폴백 금지.
- 실패(부분 실패 포함)는 명시 표면화 — 조용한 성공 위장 금지.
- 배치 array 지원: 여러 옵션을 1회 호출로 변경.

호출자 책임:
- validator 5단계 사전 검증 통과 후에만 호출.
- 실패 시 이전값 유지.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from shared.platforms import LOTTEON
from shared.platforms.lotteon.client import LotteonClient, LotteonAPIError


logger = logging.getLogger(__name__)

_DEFAULT_HST_END = "99991231235959"   # 무기한
_DTFMT = "%Y%m%d%H%M%S"


@dataclass
class PriceChangeResult:
    """옵션 1건 가격 변경 결과."""
    sitm_no: str
    success: bool
    result_code: Optional[str] = None
    error_message: Optional[str] = None


def _now_str() -> str:
    return datetime.now().strftime(_DTFMT)


def update_prices(
    items: list[dict],
    *,
    client: Optional[LotteonClient] = None,
    tr_no: Optional[str] = None,
    tr_grp_cd: Optional[str] = None,
    lrtr_no: Optional[str] = None,
) -> list[PriceChangeResult]:
    """여러 옵션 가격을 배치 변경.

    items: [{ "spd_no","sitm_no","price", (선택)"itm_dc_typ_cd","hst_start","hst_end" }]
    tr_no/tr_grp_cd/lrtr_no: 미지정 시 config(LOTTEON) 값.
    """
    if not items:
        return []

    cfg = LOTTEON
    _tr_no = tr_no if tr_no is not None else cfg.get("tr_no", "")
    _tr_grp = tr_grp_cd or cfg.get("tr_grp_cd", "SR")
    _lrtr = lrtr_no if lrtr_no is not None else cfg.get("lrtr_no", "")

    itm_prc_lst = []
    for it in items:
        price = int(it["price"])
        if price <= 0:
            raise ValueError(f"price 는 양의 정수여야 합니다 (sitm_no={it.get('sitm_no')}, 입력={price})")
        itm_prc_lst.append({
            "trGrpCd": _tr_grp,
            "trNo": _tr_no,
            "lrtrNo": _lrtr,
            "spdNo": str(it["spd_no"]),
            "sitmNo": str(it["sitm_no"]),
            "slPrc": price,
            "itmDcTypCd": it.get("itm_dc_typ_cd", "GNRL"),
            "hstStrtDttm": it.get("hst_start") or _now_str(),
            "hstEndDttm": it.get("hst_end") or _DEFAULT_HST_END,
        })

    client = client or LotteonClient()
    try:
        resp = client.request(
            method="POST",
            path=cfg["paths"]["price_change"],
            body={"itmPrcLst": itm_prc_lst},
        )
    except LotteonAPIError as e:
        logger.warning("가격 변경 실패(HTTP) status=%s msg=%s", e.status_code, e.message)
        # 전 항목 실패로 표면화
        return [PriceChangeResult(sitm_no=str(it["sitm_no"]), success=False,
                                  error_message=e.message) for it in items]

    return _parse_batch_result(resp, items, price=True)


def update_price(
    spd_no: str,
    sitm_no: str,
    price: int,
    *,
    client: Optional[LotteonClient] = None,
    itm_dc_typ_cd: str = "GNRL",
    hst_start: Optional[str] = None,
    hst_end: Optional[str] = None,
    **cfg_overrides,
) -> PriceChangeResult:
    """단일 옵션 판매가 변경 (어댑터용)."""
    results = update_prices(
        [{"spd_no": spd_no, "sitm_no": sitm_no, "price": price,
          "itm_dc_typ_cd": itm_dc_typ_cd, "hst_start": hst_start, "hst_end": hst_end}],
        client=client,
        tr_no=cfg_overrides.get("tr_no"),
        tr_grp_cd=cfg_overrides.get("tr_grp_cd"),
        lrtr_no=cfg_overrides.get("lrtr_no"),
    )
    return results[0]


def _parse_batch_result(resp: dict, items: list[dict], *, price: bool) -> list[PriceChangeResult]:
    """returnCode + data[] resultCode 를 옵션별 결과로 변환.

    최상위 returnCode 가 정상이 아니면 전 항목 실패.
    data[] 는 (spdNo, sitmNo) 로 매칭. 응답에 없는 항목은 실패로 간주(조용한 누락 금지).
    """
    return_code = str(resp.get("returnCode"))
    if return_code not in ("0000", "SUCCESS"):
        msg = resp.get("message") or f"returnCode={return_code}"
        return [PriceChangeResult(sitm_no=str(it["sitm_no"]), success=False,
                                  result_code=return_code, error_message=msg)
                for it in items]

    by_sitm = {}
    for row in resp.get("data") or []:
        by_sitm[str(row.get("sitmNo"))] = row

    results = []
    for it in items:
        sitm = str(it["sitm_no"])
        row = by_sitm.get(sitm)
        if row is None:
            results.append(PriceChangeResult(sitm_no=sitm, success=False,
                                             error_message="응답 data[] 에 해당 옵션 없음"))
            continue
        rc = str(row.get("resultCode"))
        results.append(PriceChangeResult(
            sitm_no=sitm,
            success=(rc == "0000"),
            result_code=rc,
            error_message=None if rc == "0000" else (row.get("resultMessage") or rc),
        ))
    return results
