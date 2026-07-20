# -*- coding: utf-8 -*-
"""ESM 2.0(옥션·G마켓) 상품 상세조회 — 기존 상품 연동(옵션 조회).

근거(공개문서 etapi.gmarket.com, 2026-07-09 실측):
  · 사이트상품번호→goodsNo  GET /item/v1/site-goods/{siteGoodsNo}/goods-no   (문서 /30)
  · 상품 상세조회(옵션 포함) GET /item/v1/goods/{goodsNo}                     (문서 /20)
  · 옵션 조회/수정            GET·PUT /item/v1/goods/{goodsNo}/recommended-options (문서 /26)

옵션(색·사이즈)은 recommendedOpts.independent.details[] (상세조회) 또는
recommended-options 응답의 details[] 에 담긴다. 사이트별 값은 키 gmkt(G마켓)/iac(옥션).
ESM 문서가 대소문자를 혼용(Gmkt/Iac vs gmkt/iac)해 대소문자 무시로 읽는다.

⚠️ 라이브 미검증(키없음) — 필드명/응답 envelope 는 공개문서 근거. 실계정 응답에서 확정 후
   불일치 시 이 파서를 정정한다(추측·폴백 금지: 미상은 None 으로 표면화, 0/센티넬 금지).
역할: 조회·파싱만. 매칭/저장은 상위(uploader/market_fetch)에서.
"""
from __future__ import annotations

import logging
from typing import Optional

from shared.platforms import AUCTION as _ESM_CFG

logger = logging.getLogger(__name__)

# 우리 마켓 슬러그 → ESM 사이트 필드 키.
_SITE_FIELD = {"auction": "iac", "gmarket": "gmkt"}


def site_field(market: str) -> str:
    """마켓 슬러그(auction|gmarket) → ESM 사이트 값 키(iac|gmkt). 미상은 그대로."""
    return _SITE_FIELD.get(market, market)


def _ci_get(d: dict, key: str):
    """대소문자 무시 dict 조회(ESM 이 Gmkt/gmkt 혼용). 없으면 None."""
    if not isinstance(d, dict):
        return None
    kl = key.lower()
    for k, v in d.items():
        if str(k).lower() == kl:
            return v
    return None


def _site_val(container, market: str):
    """{gmkt:.., iac:..} 형태에서 해당 마켓 값(대소문자 무시). 없으면 None."""
    return _ci_get(container, site_field(market))


def _check_ok(resp: dict, ctx: str) -> None:
    """ESM 응답 결과코드 확인. resultCode/ResultCode 가 있고 성공(0)이 아니면 raise.

    상세조회(GET)는 결과코드 envelope 없이 객체를 바로 줄 수도 있어, 코드가 없으면 통과.
    """
    if not isinstance(resp, dict):
        return
    rc = _ci_get(resp, "resultCode")
    if rc is None:
        rc = _ci_get(resp, "ResultCode")
    if rc is None:
        return  # envelope 없음 — 객체 직접 반환으로 간주
    if str(rc) not in ("0", "0000", "SUCCESS", "OK"):
        msg = _ci_get(resp, "message") or _ci_get(resp, "Message") or ""
        raise ValueError(f"ESM {ctx} 실패 resultCode={rc} {msg}")


def _unwrap(resp: dict):
    """{resultCode, data/Data:{...}} 이면 data 를, 아니면 resp 자체를 반환."""
    if not isinstance(resp, dict):
        return resp
    data = _ci_get(resp, "data")
    return data if isinstance(data, (dict, list)) else resp


def resolve_goods_no(site_goods_no: str, *, client) -> Optional[str]:
    """옥션/G마켓 사이트 상품번호 → 마스터 goodsNo (문서 /30).

    입력이 이미 마스터 goodsNo 일 수도 있어, 실패하면 입력값을 그대로 반환(상위가 상세조회로 판별).
    """
    paths = (getattr(client, "_cfg", None) or {}).get("paths") or {}
    tmpl = paths.get("site_goods_map")
    if not tmpl:
        return str(site_goods_no)
    path = tmpl.format(siteGoodsNo=str(site_goods_no))
    try:
        resp = client.request(method="GET", path=path)
    except Exception as e:  # noqa: BLE001 — 매핑 실패는 상위에서 상세조회로 재시도
        # ★ 마켓은 400 과 함께 **이유를 본문에 적어 보낸다**
        #   (예: {"resultCode":1000,"message":"삭제된 상품 입니다."}).
        #   raise_for_status 가 본문을 버려서 그동안 상태코드만 보고 "404 났다"고만 알았다.
        #   여기서 본문의 message 를 건져 예외에 실어 올린다 — 그래야 화면이 진짜 이유를 말한다.
        msg = ""
        try:
            body = getattr(getattr(e, "response", None), "text", "") or ""
            if body:
                import json as _j
                msg = (_j.loads(body) or {}).get("message") or ""
        except Exception:   # noqa: BLE001 — 본문 파싱 실패는 무시(사유만 못 얻을 뿐)
            pass
        logger.info("[esm] site-goods 매핑 실패(%s): %s %s", site_goods_no, e, msg)
        if msg:
            raise RuntimeError(msg) from e
        return str(site_goods_no)
    data = _unwrap(resp)
    if isinstance(data, dict):
        gn = _ci_get(data, "goodsNo") or _ci_get(data, "goodsno")
        if gn:
            return str(gn)
    return str(site_goods_no)


def get_goods_detail(goods_no: str, *, client) -> dict:
    """상품 상세조회 → 상품 객체(dict). 옵션은 recommendedOpts.independent.details (문서 /20)."""
    paths = (getattr(client, "_cfg", None) or {}).get("paths") or {}
    tmpl = paths.get("detail")
    if not tmpl:
        raise ValueError("ESM 상세조회 경로 미설정(스펙 미확보)")
    path = tmpl.format(goodsNo=str(goods_no))
    resp = client.request(method="GET", path=path)
    _check_ok(resp, f"상세조회 goodsNo={goods_no}")
    data = _unwrap(resp)
    return data if isinstance(data, dict) else {}


def get_recommended_options(goods_no: str, *, client) -> list[dict]:
    """옵션 목록 조회(full-replace PUT 전 현재 배열 확보용, 문서 /26). details[] 원본 반환."""
    paths = (getattr(client, "_cfg", None) or {}).get("paths") or {}
    tmpl = paths.get("options")
    if not tmpl:
        raise ValueError("ESM 옵션조회 경로 미설정(스펙 미확보)")
    path = tmpl.format(goodsNo=str(goods_no))
    resp = client.request(method="GET", path=path)
    _check_ok(resp, f"옵션조회 goodsNo={goods_no}")
    return _find_option_details(resp)


def _find_option_details(source) -> list[dict]:
    """상세조회 dict / 옵션조회 응답 / 원본 리스트 어느 형태든 옵션 details[] 를 찾아 반환."""
    if isinstance(source, list):
        return source
    if not isinstance(source, dict):
        return []
    # data/Data envelope 우선 언랩
    for key in ("data", "Data"):
        inner = _ci_get(source, key)
        if isinstance(inner, (dict, list)):
            got = _find_option_details(inner)
            if got:
                return got
    # 직접 details[]
    for key in ("details", "Details"):
        v = _ci_get(source, key)
        if isinstance(v, list):
            return v
    # 상세조회 중첩: itemAddtionalInfo.recommendedOpts.independent.details
    add = (_ci_get(source, "itemAddtionalInfo")
           or _ci_get(source, "itemAdditionalInfo") or {})
    ropts = _ci_get(add, "recommendedOpts") or {}
    indep = _ci_get(ropts, "independent") or {}
    v = _ci_get(indep, "details")
    return v if isinstance(v, list) else []


def _opt_value_pair(detail: dict):
    """옵션 값에서 (색, 사이즈) 추출. ESM recommendedOptValue 구조가 다양해 방어적."""
    # 후보1: recommendedOptValue1/2 (축별 분리)
    v1 = _ci_get(detail, "recommendedOptValue1") or _ci_get(detail, "optValue1")
    v2 = _ci_get(detail, "recommendedOptValue2") or _ci_get(detail, "optValue2")
    if v1 or v2:
        return (str(v1).strip() if v1 else ""), (str(v2).strip() if v2 else "")
    # 후보2: 단일 문자열 "블랙,260" / "블랙|260"
    raw = _ci_get(detail, "recommendedOptValue") or _ci_get(detail, "optValue") or ""
    if isinstance(raw, str) and raw.strip():
        for sep in (",", "|", "/"):
            if sep in raw:
                parts = [p.strip() for p in raw.split(sep)]
                return parts[0], (parts[1] if len(parts) > 1 else "")
        return raw.strip(), ""
    return "", ""


def extract_options(source, market: str) -> list[dict]:
    """상세조회/옵션조회 → 정규화 옵션 리스트.

    Returns [{"option_id","color","size","stock","add_amount","sold_out"}]:
      · option_id: 판매자옵션코드(manageCode) 우선, 없으면 optNo/id.
      · stock: 해당 마켓 사이트(qty.gmkt|iac). 없으면 None(0/센티넬 금지 — 미상 표면화).
      · add_amount: 옵션 추가금(addAmnt). 없으면 None.
      · sold_out: isSoldOut(bool).
    """
    out: list[dict] = []
    for d in _find_option_details(source):
        if not isinstance(d, dict):
            continue
        oid = (_ci_get(d, "manageCode") or _ci_get(d, "optNo")
               or _ci_get(d, "recommendedOptNo") or _ci_get(d, "id"))
        if oid in (None, ""):
            continue
        color, size = _opt_value_pair(d)
        qty = _ci_get(d, "qty")
        stock = _site_val(qty, market) if isinstance(qty, dict) else _ci_get(d, "qty")
        try:
            stock = int(stock) if stock is not None else None
        except (TypeError, ValueError):
            stock = None
        add_amt = _ci_get(d, "addAmnt")
        try:
            add_amt = int(add_amt) if add_amt is not None else None
        except (TypeError, ValueError):
            add_amt = None
        out.append({
            "option_id": str(oid),
            "color": color,
            "size": size,
            "stock": stock,
            "add_amount": add_amt,
            "sold_out": bool(_ci_get(d, "isSoldOut")),
        })
    return out


def search_goods(
    *,
    client,
    keyword: Optional[str] = None,
    market: Optional[str] = None,
    sell_status: Optional[str] = None,
    page_index: int = 0,
    page_size: int = 100,
) -> dict:
    """상품 목록 조회 → {totalItems, pageIndex, pageSize, items[]}.

    근거: 데이터 코드 지도(판매처 > 데이터 코드 지도 > 상품 조회 > 옥션/G마켓
        「상품 목록 조회 API」) 실측 — 요청 파라미터 26개·응답 필드 94개 전부 뜻 확보.
        POST /item/v1/goods/search

    주요 파라미터:
        keyword     상품명·브랜드명·제조사명·관리코드 검색 (★ 키워드는 1개씩만)
        siteId      1=옥션 / 2=지마켓
        sellStatus  11=판매중 / 21=판매중지 / 22=직권중지 / 31=SKU품절
        pageIndex   페이지 인덱스
        pageSize    ★ 최대 500

    응답 주요 필드:
        totalItems              조회 조건 전체 상품수
        items[].goodsNo         마스터번호
        items[].siteGoodsNo.gmkt  지마켓 상품번호
        items[].siteGoodsNo.iac   옥션 상품번호
        items[].managedCode     판매자관리코드

    ★ 옥션·G마켓은 **같은 엔드포인트**를 쓰고 siteId 로만 갈린다(마스터번호는 공용).
    """
    body: dict = {
        "pageIndex": int(page_index),
        "pageSize": min(int(page_size), 500),   # 문서 상한 500
    }
    if keyword:
        body["keyword"] = str(keyword)
    if sell_status:
        body["sellStatus"] = str(sell_status)
    if market:
        if market not in _SITE_FIELD:
            raise ValueError(f"ESM 마켓 아님: {market}")
        body["siteId"] = "1" if market == "auction" else "2"
    resp = client.request(method="POST", path=_ESM_CFG["paths"]["search"], body=body)
    _check_ok(resp, "상품 목록 조회")
    data = _unwrap(resp)
    if isinstance(data, dict):
        return data
    return {"totalItems": None, "items": data if isinstance(data, list) else []}
