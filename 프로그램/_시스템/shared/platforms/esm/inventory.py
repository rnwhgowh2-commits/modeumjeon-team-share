# -*- coding: utf-8 -*-
"""ESM 2.0(옥션·G마켓) 재고 수정.

근거(공개문서 etapi.gmarket.com, 2026-07-09 실측) + 도메인 함정:
  · 본품 재고     PUT /item/v1/goods/{goodsNo}/stock  body {stock:{gmkt|iac:수량}}  (문서 /194)
        └ ⚠️ "옵션 사용 상품·풀필먼트는 재고수정 불가" → 모음전(색·사이즈 옵션) 에는 못 씀.
  · 옵션 재고(핵심) PUT /item/v1/goods/{goodsNo}/recommended-options 로 details[] 전체 재전송(문서 /26).
        └ PATCH 가 없어 full-replace. 우리는 GET 으로 받은 details 배열을 그대로 두고
          대상 옵션의 qty[사이트]만 바꿔 PUT(echo-back) → 나머지 옵션 필드/값 보존(누락 방지).

정책(CLAUDE.md): 재고=실브라우저 소싱처 URL 실값 기준, 폴백 금지. stkQty≥0(0=품절). 실패는 표면화.
site: 옥션=iac / G마켓=gmkt.

⚠️ 라이브 미검증(키없음) — recommended-options 의 PUT 요청 envelope 는 GET 응답을 echo-back 하는
   전략이라 필드명 불일치에 강하지만, 실계정 라운드트립으로 최종 확정 필요(추측 금지).
"""
from __future__ import annotations

import logging

from .products import (site_field, _ci_get, get_recommended_options,
                       _find_option_details)

logger = logging.getLogger(__name__)

_OK_CODES = ("0", "0000", "SUCCESS", "OK")


def _resp_ok(resp: dict) -> bool:
    rc = _ci_get(resp, "resultCode")
    if rc is None:
        rc = _ci_get(resp, "ResultCode")
    return str(rc) in _OK_CODES if rc is not None else False


def _set_site_qty(detail: dict, market: str, stock: int) -> None:
    """detail 의 qty[사이트]=stock (기존 구조·대소문자 보존). qty 없으면 생성."""
    key = site_field(market)
    qty = _ci_get(detail, "qty")
    if isinstance(qty, dict):
        # 기존 키 대소문자 유지(Gmkt/gmkt)
        for k in list(qty.keys()):
            if str(k).lower() == key:
                qty[k] = int(stock)
                return
        qty[key] = int(stock)
    else:
        detail["qty"] = {key: int(stock)}


def _option_id_of(detail: dict) -> str:
    oid = (_ci_get(detail, "manageCode") or _ci_get(detail, "optNo")
           or _ci_get(detail, "recommendedOptNo") or _ci_get(detail, "id"))
    return str(oid) if oid not in (None, "") else ""


def update_stock(goods_no: str, market: str, option_id: str, stock: int, *, client) -> bool:
    """옵션(option_id) 재고를 full-replace(echo-back)로 변경. 성공 True / 실패 False.

    GET recommended-options → 대상 옵션 qty[사이트]=stock → PUT 전체 details.
    대상 옵션을 못 찾으면 실패(조용한 누락 금지).
    """
    stock = int(stock)
    if stock < 0:
        raise ValueError(f"stkQty 는 0 이상이어야 합니다 (goodsNo={goods_no}, 입력={stock})")

    cfg = getattr(client, "_cfg", None) or {}
    tmpl = (cfg.get("paths") or {}).get("options")
    if not tmpl:
        raise ValueError("ESM 옵션수정 경로 미설정(스펙 미확보)")
    path = tmpl.format(goodsNo=str(goods_no))

    try:
        details = get_recommended_options(str(goods_no), client=client)
    except Exception as e:  # noqa: BLE001 — 조회 실패는 재고수정 실패로 표면화
        logger.warning("[esm] 옵션조회 실패 goodsNo=%s: %s", goods_no, e)
        return False

    target = None
    for d in details:
        if isinstance(d, dict) and _option_id_of(d) == str(option_id):
            target = d
            break
    if target is None:
        logger.warning("[esm] 대상 옵션 없음 goodsNo=%s option=%s (재고수정 실패)", goods_no, option_id)
        return False

    _set_site_qty(target, market, stock)

    try:
        resp = client.request(method="PUT", path=path, body={"details": details})
    except Exception as e:  # noqa: BLE001
        logger.warning("[esm] 재고 full-replace 실패 goodsNo=%s: %s", goods_no, e)
        return False
    return _resp_ok(resp)


def update_base_stock(goods_no: str, market: str, stock: int, *, client) -> bool:
    """본품 재고 변경(옵션無 상품 전용, 문서 /194). 옵션 상품은 update_stock 사용."""
    stock = int(stock)
    if stock < 0:
        raise ValueError(f"stkQty 는 0 이상이어야 합니다 (goodsNo={goods_no}, 입력={stock})")
    cfg = getattr(client, "_cfg", None) or {}
    tmpl = (cfg.get("paths") or {}).get("stock_change")
    if not tmpl:
        raise ValueError("ESM 재고수정 경로 미설정(스펙 미확보)")
    path = tmpl.format(goodsNo=str(goods_no))
    body = {"stock": {site_field(market): stock}}
    try:
        resp = client.request(method="PUT", path=path, body=body)
    except Exception as e:  # noqa: BLE001
        logger.warning("[esm] 본품 재고수정 실패 goodsNo=%s: %s", goods_no, e)
        return False
    return _resp_ok(resp)
