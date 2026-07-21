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
    # ★ 실 응답(2026-07-21 라이브)에서 옵션 식별자는 **optSeq** 다.
    #   manageCode 는 null, recommendedOptNo 는 없고 recommendedOptValueNo 는 0(무용).
    #   optSeq 를 최우선으로 본다 — 이걸 빼먹어 옵션을 못 찾고 재고갱신이 통째로 실패했다.
    oid = (_ci_get(detail, "optSeq") or _ci_get(detail, "manageCode")
           or _ci_get(detail, "optNo") or _ci_get(detail, "recommendedOptNo")
           or _ci_get(detail, "id"))
    return str(oid) if oid not in (None, "") else ""


def _set_soldout_site(detail: dict, market: str, value: bool) -> None:
    """품절 플래그를 **사이트별**(isSoldOutSite[site])로 세팅.

    실 구조는 isSoldOutSite:{gmkt,iac} 사이트별 + top-level isSoldOut 둘 다 있다.
    한 사이트만 내릴 때 top-level 을 건드리면 양쪽이 다 내려간다 → 사이트별만 만진다.
    isSoldOutSite 가 없는(옛/단순) 구조면 top-level isSoldOut 으로 폴백.
    """
    key = site_field(market)
    site = _ci_get(detail, "isSoldOutSite")
    if isinstance(site, dict):
        for k in list(site.keys()):
            if str(k).lower() == key:
                site[k] = bool(value)
                return
        site[key] = bool(value)
        return
    # 폴백: 사이트별 필드가 없으면 top-level
    for k in list(detail.keys()):
        if str(k).lower() == "issoldout":
            detail[k] = bool(value)
            return
    detail["isSoldOut"] = bool(value)


def _is_sold_out_site(detail: dict, market: str) -> bool:
    """그 사이트에서 품절인가. isSoldOutSite[site] 우선, 없으면 top-level isSoldOut."""
    site = _ci_get(detail, "isSoldOutSite")
    if isinstance(site, dict):
        return bool(_ci_get(site, site_field(market)))
    return bool(_ci_get(detail, "isSoldOut"))


def update_stock(goods_no: str, market: str, option_id: str, stock: int, *, client) -> bool:
    """옵션(option_id) 재고를 full-replace(echo-back)로 변경. 성공 True / 실패 False.

    GET recommended-options → 대상 옵션만 수정 → PUT 전체 details.
    대상 옵션을 못 찾으면 실패(조용한 누락 금지).

    🔴 문서 /26 + 라이브 실구조(2026-07-21) — 어기면 마켓이 거부하는데 성공으로 알고 판다(오버셀):
      · 옵션 식별자는 **optSeq**(manageCode 는 null). 이걸 못 찾으면 재고갱신이 통째로 실패한다.
      · qty 는 **1~99,999**, **0 불가**(에러 1000). 품절은 qty 가 아니라 **isSoldOutSite[사이트]**
        로 표현한다(사이트별). stock=0 이 들어오면 그 사이트만 품절로 번역한다.
      · **한 사이트의 모든 옵션이 품절이면 불가**(에러 3000). 그 사이트의 마지막 판매가능 옵션을
        내리려 하면 보내기 전에 막고, 상품 판매중지로 가라고 사유를 준다(사이트별 판정).
      · full-replace 라 **다른 옵션의 잘못된 재고도 전체를 거부시킨다** → 조용히 고치지 않고
        어느 옵션인지 짚어서 실패시킨다(폴백 금지).
    """
    stock = int(stock)
    if stock < 0:
        raise ValueError(f"재고는 0 이상이어야 합니다 (goodsNo={goods_no}, 입력={stock})")
    if stock > _STOCK_MAX:
        raise ValueError(f"재고는 {_STOCK_MAX} 이하여야 합니다 (goodsNo={goods_no}, 입력={stock})")

    path = _path_of(client, goods_no, "options")

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

    going_sold_out = (stock == 0)
    if going_sold_out:
        # 품절 = 그 사이트 isSoldOutSite=true. qty 는 건드리지 않는다(0 은 무효).
        _set_soldout_site(target, market, True)
    else:
        _set_site_qty(target, market, stock)
        # 재입고면 그 사이트 품절 플래그도 내린다 — 안 그러면 재고만 차고 계속 품절로 보인다.
        _set_soldout_site(target, market, False)

    # 전 옵션 품절 방지(에러 3000) — **그 사이트 기준**. 판매가능이 하나도 안 남으면 안 보낸다.
    if not any(not _is_sold_out_site(d, market) for d in details if isinstance(d, dict)):
        raise ValueError(
            f"{market} 의 모든 옵션이 품절이 됩니다 (goodsNo={goods_no}, option={option_id}). "
            f"ESM 은 이 상태를 거부합니다(에러 3000) — 상품 자체를 판매중지 하세요."
        )

    # full-replace 라 남의 옵션이 가진 잘못된 재고도 전체를 거부시킨다. 어느 옵션인지 짚는다.
    for d in details:
        if not isinstance(d, dict):
            continue
        for site_key, qty in (_ci_get(d, "qty") or {}).items():
            if isinstance(qty, int) and not (_STOCK_MIN <= qty <= _STOCK_MAX):
                raise ValueError(
                    f"옵션 재고가 1~{_STOCK_MAX} 범위를 벗어납니다 — "
                    f"옵션 {_option_id_of(d) or '?'} 의 {site_key}={qty} "
                    f"(goodsNo={goods_no}). 이대로 보내면 전체가 거부됩니다."
                )

    try:
        resp = client.request(method="PUT", path=path, body={"details": details})
    except Exception as e:  # noqa: BLE001
        logger.warning("[esm] 재고 full-replace 실패 goodsNo=%s: %s", goods_no, e)
        return False
    return _resp_ok(resp)


_STOCK_MIN = 1
_STOCK_MAX = 99999


def _check_stock_range(goods_no: str, stock: int) -> None:
    """ESM 재고 유효범위 1~99,999 (문서 /194·/21). **0 은 무효다.**

    0 을 품절 의도로 보내면 마켓이 거부한다. 여기서 안 막으면 "품절 올렸다"고 착각한 채
    계속 팔린다(오버셀). 품절은 set_sold_out() = 판매중지로 가야 한다.
    """
    if stock == 0:
        raise ValueError(
            f"재고 0 은 ESM 규격상 무효입니다 (goodsNo={goods_no}). "
            f"품절 처리는 set_sold_out() 으로 판매중지(isSell=false) 하세요."
        )
    if not (_STOCK_MIN <= stock <= _STOCK_MAX):
        raise ValueError(f"재고는 1~99999 여야 합니다 (goodsNo={goods_no}, 입력={stock})")


def _path_of(client, goods_no: str, key: str) -> str:
    cfg = getattr(client, "_cfg", None) or {}
    tmpl = (cfg.get("paths") or {}).get(key)
    if not tmpl:
        raise ValueError(f"ESM 경로 미설정: {key}")
    return tmpl.format(goodsNo=str(goods_no))


def update_base_stock(goods_no: str, market: str, stock: int, *, client) -> bool:
    """본품 재고 변경(문서 /194). PUT /item/v1/goods/{goodsNo}/stock

    ⚠️ 문서 명시 제약 — **본품만 판매하는 상품 전용**. 아래는 대상이 아니다:
       · 옵션 사용 상품 → update_stock() (옵션 재고 full-replace)
       · 풀필먼트 스타배송 상품 → 불가
    ⚠️ 옵션 재고관리를 쓰는 상품은 본품 재고가 무시되고 옵션 합계가 적용된다(문서 /21).
    """
    stock = int(stock)
    _check_stock_range(goods_no, stock)
    path = _path_of(client, goods_no, "stock_change")
    body = {"stock": {site_field(market): stock}}
    try:
        resp = client.request(method="PUT", path=path, body=body)
    except Exception as e:  # noqa: BLE001
        logger.warning("[esm] 본품 재고수정 실패 goodsNo=%s: %s", goods_no, e)
        return False
    return _resp_ok(resp)


# ── 가격/재고/판매상태 통합(sell-status, 문서 /21) ─────────────────────────
# PUT 은 전 필드가 필수라 **읽고 그대로 되돌려 보내되 목표만 바꾼다**(echo-back).
# 함정 2개 — 둘 다 문서 샘플에서 직접 확인:
#   ① GET 은 대문자 키(IsSell·Price·Stock·SellingPeriod), PUT 은 소문자(isSell·price·
#      stock·sellingPeriod). 읽은 걸 그대로 되돌리면 마켓이 못 알아듣는다.
#   ② GET 의 SellingPeriod 는 **종료일 YYYYMMDD**(예 20190328), PUT 은 **기간**
#      (-1 무제한 / 0 유지 / 15·30·60·90·365). 되돌려 보내면 2천만일짜리 기간이 된다.
#      → 판매기간은 우리가 건드릴 일이 없으므로 항상 0(유지).
# 🟡 가격은 우리가 계산해 넣지 않는다. 읽은 값을 그대로 되돌릴 뿐이다.
#    (문서 오류 1000 = "0원 금액은 입력하실 수 없습니다" — 0 을 만들지 않도록 주의)
_PERIOD_MAINTAIN = 0


def get_sell_status(goods_no: str, *, client) -> dict:
    """가격/재고/판매상태 조회(GET). 원본 응답 그대로 반환(대문자 키 유지)."""
    return client.request(method="GET", path=_path_of(client, goods_no, "sell_status"))


def _both(container) -> dict:
    """{gmkt:..., iac:...} 를 대소문자 무시로 두 사이트 다 뽑는다."""
    return {"gmkt": _ci_get(container, "gmkt"), "iac": _ci_get(container, "iac")}


def _build_sell_status_body(cur: dict, market: str, *, stock=None, is_sell=None) -> dict:
    """조회 결과(cur)를 PUT 규격으로 바꾸고 목표 사이트만 덮어쓴다."""
    info = _ci_get(cur, "itemBasicInfo") or {}
    key = site_field(market)

    body_is_sell = _both(_ci_get(cur, "isSell"))
    body_price = _both(_ci_get(info, "price"))
    body_stock = _both(_ci_get(info, "stock"))

    if is_sell is not None:
        body_is_sell[key] = bool(is_sell)
    if stock is not None:
        body_stock[key] = int(stock)

    return {
        "isSell": body_is_sell,
        "itemBasicInfo": {
            "price": body_price,
            "stock": body_stock,
            # ★ 읽은 종료일을 되돌리지 않는다 — 항상 '유지'.
            "sellingPeriod": {"gmkt": _PERIOD_MAINTAIN, "iac": _PERIOD_MAINTAIN},
        },
    }


def _put_sell_status(goods_no: str, market: str, *, client, stock=None, is_sell=None) -> bool:
    try:
        cur = get_sell_status(goods_no, client=client)
    except Exception as e:  # noqa: BLE001 — 조회 실패는 변경 실패로 표면화
        logger.warning("[esm] sell-status 조회 실패 goodsNo=%s: %s", goods_no, e)
        return False

    body = _build_sell_status_body(cur, market, stock=stock, is_sell=is_sell)
    try:
        resp = client.request(method="PUT", path=_path_of(client, goods_no, "sell_status"),
                              body=body)
    except Exception as e:  # noqa: BLE001
        logger.warning("[esm] sell-status 수정 실패 goodsNo=%s: %s", goods_no, e)
        return False
    return _resp_ok(resp)


def set_stock_via_sell_status(goods_no: str, market: str, stock: int, *, client) -> bool:
    """재고를 sell-status 로 변경. /stock 이 거부하는 상품의 대안이자 콜 수 절약 경로."""
    stock = int(stock)
    _check_stock_range(goods_no, stock)
    return _put_sell_status(goods_no, market, client=client, stock=stock)


def set_sold_out(goods_no: str, market: str, *, client) -> bool:
    """품절 처리 = 해당 사이트 **판매중지**(isSell=false). 재고는 건드리지 않는다.

    재고 0 은 ESM 규격상 무효라 품절을 재고로 표현할 수 없다. 반대편 사이트의
    판매상태는 읽은 값 그대로 보존한다(한쪽만 내린다).
    """
    return _put_sell_status(goods_no, market, client=client, is_sell=False)
