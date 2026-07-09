# -*- coding: utf-8 -*-
"""ESM 2.0(옥션·G마켓) 가격 수정.

근거(공개문서 etapi.gmarket.com, 2026-07-09 실측):
  본품(대표) 가격  PUT /item/v1/goods/{goodsNo}/price   body {gmkt|iac: 가격}  (문서 /186)
    · 가격은 10원 단위, 판매중 상태만 수정.
    · 옵션별 차등가는 별도 PATCH 없음 → recommended-options full-replace 의 addAmnt 로 표현(후속·라이브검증).
      모음전은 모델당 단일가가 대부분이라 어댑터는 이 본품가 경로를 쓴다.

정책(CLAUDE.md): 가격=실브라우저 소싱처 URL 실값 기준, 폴백 금지. 실패는 명시 표면화.
10원 단위 위반은 임의 반올림 없이 ValueError 로 표면화(금전 오차 방지). site: 옥션=iac / G마켓=gmkt.

⚠️ 라이브 미검증(키없음) — 응답 envelope(resultCode 0=성공)는 공개문서 근거. 실계정에서 확정.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from .products import site_field, _ci_get

logger = logging.getLogger(__name__)

_OK_CODES = ("0", "0000", "SUCCESS", "OK")


@dataclass
class EsmPriceResult:
    """가격 변경 결과(옵션/상품 1건)."""
    goods_no: str
    success: bool
    result_code: Optional[str] = None
    error_message: Optional[str] = None


def _resp_ok(resp: dict) -> tuple[bool, Optional[str], Optional[str]]:
    """(성공?, resultCode, message) — resultCode/ResultCode 대소문자 무시."""
    rc = _ci_get(resp, "resultCode")
    if rc is None:
        rc = _ci_get(resp, "ResultCode")
    msg = _ci_get(resp, "message") or _ci_get(resp, "Message")
    ok = str(rc) in _OK_CODES if rc is not None else False
    return ok, (str(rc) if rc is not None else None), msg


def update_price(goods_no: str, market: str, price: int, *, client) -> EsmPriceResult:
    """본품(대표) 판매가 변경. market=auction|gmarket → 사이트 키 iac|gmkt.

    price 는 양의 정수·10원 단위(마켓 규칙). 위반은 ValueError(반올림으로 금액 왜곡 금지).
    """
    price = int(price)
    if price <= 0:
        raise ValueError(f"price 는 양의 정수여야 합니다 (goodsNo={goods_no}, 입력={price})")
    if price % 10 != 0:
        raise ValueError(f"ESM 가격은 10원 단위여야 합니다 (goodsNo={goods_no}, 입력={price})")

    cfg = getattr(client, "_cfg", None) or {}
    tmpl = (cfg.get("paths") or {}).get("price_change")
    if not tmpl:
        raise ValueError("ESM 가격수정 경로 미설정(스펙 미확보)")
    path = tmpl.format(goodsNo=str(goods_no))
    body = {site_field(market): price}

    try:
        resp = client.request(method="PUT", path=path, body=body)
    except Exception as e:  # noqa: BLE001 — HTTP/네트워크 실패는 실패로 표면화(폴백 금지)
        logger.warning("[esm] 가격수정 실패 goodsNo=%s: %s", goods_no, e)
        return EsmPriceResult(goods_no=str(goods_no), success=False, error_message=str(e))

    ok, rc, msg = _resp_ok(resp)
    return EsmPriceResult(goods_no=str(goods_no), success=ok, result_code=rc,
                          error_message=None if ok else (msg or f"resultCode={rc}"))
