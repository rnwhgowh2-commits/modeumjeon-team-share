# -*- coding: utf-8 -*-
"""
롯데온 재고 변경 API 래퍼.

공식 엔드포인트(실측): POST /v1/openapi/product/v1/item/stock/change
    Request: { "itmStkLst": [ { trGrpCd, trNo, lrtrNo?, spdNo, sitmNo, stkQty }, ... ] }
    Response: { returnCode, message, data: [ { spdNo, sitmNo, resultCode, resultMessage }, ... ] }

역할:
- 옵션(sitmNo) 단위 재고 변경 (배치 array 지원).
- 실패(부분 실패 포함)는 명시 표면화 — 이전값 유지는 호출자 책임.

제약:
- stkQty >= 0 (0 = 품절)
- 호출 전 validator 검증 통과 필수 (호출자 책임)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from shared.platforms import LOTTEON
from shared.platforms.lotteon.client import LotteonClient, LotteonAPIError


logger = logging.getLogger(__name__)


@dataclass
class StockChangeResult:
    """옵션 1건 재고 변경 결과."""
    sitm_no: str
    success: bool
    result_code: Optional[str] = None
    error_message: Optional[str] = None


def update_stocks(
    items: list[dict],
    *,
    client: Optional[LotteonClient] = None,
    tr_no: Optional[str] = None,
    tr_grp_cd: Optional[str] = None,
    lrtr_no: Optional[str] = None,
) -> list[StockChangeResult]:
    """여러 옵션 재고를 배치 변경.

    items: [{ "spd_no","sitm_no","stock" }]
    """
    if not items:
        return []

    cfg = LOTTEON
    _tr_no = tr_no if tr_no is not None else cfg.get("tr_no", "")
    _tr_grp = tr_grp_cd or cfg.get("tr_grp_cd", "SR")
    _lrtr = lrtr_no if lrtr_no is not None else cfg.get("lrtr_no", "")

    itm_stk_lst = []
    for it in items:
        stock = int(it["stock"])
        if stock < 0:
            raise ValueError(f"stkQty 는 0 이상이어야 합니다 (sitm_no={it.get('sitm_no')}, 입력={stock})")
        itm_stk_lst.append({
            "trGrpCd": _tr_grp,
            "trNo": _tr_no,
            "lrtrNo": _lrtr,
            "spdNo": str(it["spd_no"]),
            "sitmNo": str(it["sitm_no"]),
            "stkQty": stock,
        })

    client = client or LotteonClient()
    try:
        resp = client.request(
            method="POST",
            path=cfg["paths"]["stock_change"],
            body={"itmStkLst": itm_stk_lst},
        )
    except LotteonAPIError as e:
        logger.warning("재고 변경 실패(HTTP) status=%s msg=%s", e.status_code, e.message)
        return [StockChangeResult(sitm_no=str(it["sitm_no"]), success=False,
                                  error_message=e.message) for it in items]

    return _parse_batch_result(resp, items)


def update_stock(
    spd_no: str,
    sitm_no: str,
    stock: int,
    *,
    client: Optional[LotteonClient] = None,
    **cfg_overrides,
) -> bool:
    """단일 옵션 재고 변경 (어댑터용). 성공 True / 실패 False."""
    results = update_stocks(
        [{"spd_no": spd_no, "sitm_no": sitm_no, "stock": stock}],
        client=client,
        tr_no=cfg_overrides.get("tr_no"),
        tr_grp_cd=cfg_overrides.get("tr_grp_cd"),
        lrtr_no=cfg_overrides.get("lrtr_no"),
    )
    return bool(results and results[0].success)


def _parse_batch_result(resp: dict, items: list[dict]) -> list[StockChangeResult]:
    """returnCode + data[] resultCode 를 옵션별 결과로 변환."""
    return_code = str(resp.get("returnCode"))
    if return_code not in ("0000", "SUCCESS"):
        msg = resp.get("message") or f"returnCode={return_code}"
        return [StockChangeResult(sitm_no=str(it["sitm_no"]), success=False,
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
            results.append(StockChangeResult(sitm_no=sitm, success=False,
                                             error_message="응답 data[] 에 해당 옵션 없음"))
            continue
        rc = str(row.get("resultCode"))
        results.append(StockChangeResult(
            sitm_no=sitm,
            success=(rc == "0000"),
            result_code=rc,
            error_message=None if rc == "0000" else (row.get("resultMessage") or rc),
        ))
    return results
