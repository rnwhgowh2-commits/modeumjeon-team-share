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


# 우리 마켓 슬러그 → ESM 카테고리 siteType(지도: 1=옥션 · 2=G마켓).
_SITE_TYPE = {"auction": "1", "gmarket": "2"}


def extract_category_codes(detail, market: str) -> dict:
    """[2026-07-23 M3 Task 6] 상품 상세에서 '등록 당시 고른' 카테고리 코드를 꺼낸다(순수함수).

    지도 근거(consult-market-map 전수정독):
      itemBasicInfo.category.site[]  — {siteType(1=옥션·2=G마켓), catCode(리프 사이트 카테고리)}
      itemBasicInfo.category.esm.catCode — ESM 표준(sd) 코드
    등록 payload 는 둘 다 요구하므로 짝으로 함께 돌려준다. 다만 우리 카테고리 사전
    (market_categories)의 `code` 는 **사이트 카테고리 코드**라, 맵핑에 박히는 값은
    site_cat_code 다(사전에 없는 코드를 확정 게이트에 넣지 않기 위해).

    ⚠️ 반대편 사이트 코드를 대신 돌려주지 않는다 — 옥션 상품에 G마켓 코드를 붙이면
    다음 등록이 조용히 엉뚱한 카테고리로 나간다. 없으면 None(추측·폴백 금지).
    ESM 은 Gmkt/gmkt·CatCode/catCode 대소문자를 혼용하므로 전부 대소문자 무시로 읽는다.
    """
    if not isinstance(detail, dict):
        return {"site_cat_code": None, "esm_cat_code": None}
    basic = _ci_get(detail, "itemBasicInfo") or _ci_get(detail, "itemBasicinfo") or {}
    cat = _ci_get(basic, "category") or {}
    if not isinstance(cat, dict):
        return {"site_cat_code": None, "esm_cat_code": None}

    want = _SITE_TYPE.get(market)
    if want is None:
        # [2026-07-23 리뷰 M4] ESM 이 아닌 마켓 슬러그 — siteType 대조가 통째로 무력화돼
        #   첫 사이트(옥션) 코드가 그대로 나갔다. 미지원이면 아무 것도 돌려주지 않는다.
        return {"site_cat_code": None, "esm_cat_code": None}
    sites = _ci_get(cat, "site")
    if isinstance(sites, dict):
        sites = [sites]
    site_code = None
    for entry in (sites or []):
        if not isinstance(entry, dict):
            continue
        st = _ci_get(entry, "siteType")
        if st is None:
            st = _ci_get(entry, "siteId")   # 상품 검색 API 는 siteId 로 적는다(지도 fields)
        if want is not None and str(st).strip() != want:
            continue
        code = _ci_get(entry, "catCode") or _ci_get(entry, "siteCatCode")
        if code not in (None, ""):
            site_code = str(code).strip() or None
            break

    esm = _ci_get(cat, "esm")
    if isinstance(esm, dict):
        esm = _ci_get(esm, "catCode")
    esm_code = str(esm).strip() if esm not in (None, "") else None

    return {"site_cat_code": site_code, "esm_cat_code": esm_code or None}


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
    # 옵션조회(recommended-options GET) 응답 형태: {type, isStockManage, independent:{details:[]}}
    #   조합형은 combination 에 들어갈 수 있어 둘 다 본다(라이브 확인: independent.details).
    for grp in ("independent", "combination", "dependent"):
        g = _ci_get(source, grp)
        if isinstance(g, dict):
            v = _ci_get(g, "details")
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
    page_index: int = 1,   # ★ ESM 은 1부터(0 보내면 resultCode 1000)
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
        pageIndex   ★ 1부터 시작 (0 보내면 "pageIndex에는 0보다 큰 값" 에러)
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


def register_goods(payload: dict, *, client) -> dict:
    """상품 등록(POST /item/v1/goods) → {goodsNo, siteDetail{gmkt,iac}, resultCode}.

    근거: 데이터 코드 지도(상품 등록/수정/전환/조회 API) 실측 payload 샘플 그대로.
        필수 26필드는 build_esm_register_payload 가 조립한다(추측 0).

    ★ 등록 직후 2~3분간 수정(sell-status 포함) 호출 불가 — 바로 부르면
      "상품 정보가 부정확합니다" 에러. 판매중지는 2~3분 뒤에.
    ★ 성공 판정 = resultCode==0 AND goodsNo 수령. HTTP 200/빈응답을 성공으로 보지 않는다
      (이 프로젝트 반복 사고: '거짓 성공').
    """
    cfg = getattr(client, "_cfg", None) or {}
    path = (cfg.get("paths") or {}).get("register")
    if not path:
        raise ValueError("ESM 등록 경로 미설정(스펙 미확보)")
    resp = client.request(method="POST", path=path, body=payload)
    _check_ok(resp, "상품 등록")
    data = _unwrap(resp)
    if not isinstance(data, dict):
        data = resp if isinstance(resp, dict) else {}
    goods_no = data.get("goodsNo") or (resp.get("goodsNo") if isinstance(resp, dict) else None)
    if not goods_no:
        raise ValueError(f"상품 등록 응답에 goodsNo 없음 — 실패로 처리(거짓 성공 금지): {str(resp)[:200]}")
    return {"goodsNo": goods_no,
            "siteDetail": data.get("siteDetail") or {},
            "resultCode": data.get("resultCode"),
            "raw": data}


def build_esm_register_payload(
    *,
    market: str,
    goods_name: str,
    cat_code: str,
    site_cat_code: str,
    site_type: int,
    price: int,
    stock: int,
    place_no: int,
    dispatch_policy_no: int,
    return_addr_no: str,
    delivery_company_no: int,
    official_notice_no: int,
    official_notice_details: list,
    image_url: str,
    detail_html: str,
    options: list = None,
    is_vat_free: bool = False,
) -> dict:
    """옥션·G마켓 상품 등록 payload 조립 — 지도 필수 26필드를 채운다.

    site_type: 1=옥션, 2=G마켓. 값은 그 사이트 키(iac/gmkt)에만 넣고 반대편은 0/미노출.
    options: [{name, value_no, qty, add_amnt, manage_code}] — 없으면 옵션 미사용(type 0).
    ★ 재고는 0 불가(1 이상). 가격은 10원 단위.
    """
    is_iac = (site_type == 1)
    # ★ ESM 통합 item API 는 price/stock 의 Gmkt·Iac 를 **둘 다 required=Y** 로 검증한다
    #   (stock 0 불가·price 10원~10억). 0 을 넣으면 400. 어느 사이트에 실제 노출할지는
    #   itemBasicInfo.category.site[] 가 결정하므로(옥션 전용=siteType 1만), 비대상 사이트의
    #   price/stock 도 스키마를 만족시키는 유효값을 넣되 category 에 없으면 노출되지 않는다.
    price_block = {"Gmkt": int(price), "Iac": int(price)}
    stock_block = {"Gmkt": int(stock), "Iac": int(stock)}
    period_block = {"Gmkt": -1, "Iac": -1}   # -1 = 무제한(신규 유효값)

    rec_opts = {"type": 0}   # 옵션 미사용 기본
    if options:
        details = []
        for o in options:
            q = int(o.get("qty", stock))
            details.append({
                "recommendedOptValueNo": o.get("value_no", 0),
                "isSoldOut": False, "isDisplay": True,
                "qty": {"iac": q if is_iac else 0, "gmkt": 0 if is_iac else q},
                "manageCode": o.get("manage_code", ""),
                "addAmnt": int(o.get("add_amnt", 0)),
            })
        rec_opts = {"type": 1, "isStockManage": True,
                    "independent": {"recommendedOptNo": options[0].get("group_no", 0),
                                    "details": details}}

    return {
        "itemBasicInfo": {
            "goodsName": {"kor": goods_name},
            "category": {
                "site": [{"siteType": site_type, "catCode": site_cat_code}],
                "esm": {"catCode": cat_code},
            },
        },
        "itemAddtionalInfo": {
            "price": price_block,
            "stock": stock_block,
            "sellingPeriod": period_block,
            "recommendedOpts": rec_opts,
            "shipping": {
                "type": 1,
                "companyNo": int(delivery_company_no),
                # feeType 2=상품별배송비 → each(개별배송비) 필수. 테스트=무료(each.feeType 1)
                "policy": {"placeNo": int(place_no), "feeType": 2,
                           "each": {"feeType": 1, "feePayType": 1, "fee": 0}},
                "dispatchPolicyNo": {"gmkt": 0 if is_iac else int(dispatch_policy_no),
                                     "iac": int(dispatch_policy_no) if is_iac else 0},
                "returnAndExchange": {"addrNo": str(return_addr_no)},
            },
            "officialNotice": {
                "officialNoticeNo": int(official_notice_no),
                "details": official_notice_details or [],
            },
            "isAdultProduct": False,   # ESM 필수(일반상품). 누락 시 400
            "isVatFree": bool(is_vat_free),
            "images": {"basicImgURL": image_url},
            "descriptions": {"kor": {"type": 2, "html": detail_html}},
        },
        "addtionalInfo": {
            "siteDiscount": {"gmkt": False, "iac": False},
        },
    }


def extract_register_prereq(detail: dict, market: str) -> dict:
    """기존 상품 상세(get_goods_detail)에서 등록 선행자원을 뽑는다(순수 함수).

    2026-07-21 실등록 검증에서 쓴 재사용 항목 그대로: 출하지·발송정책·반품주소·택배사·
    상품정보고시. 값이 비면 그대로 None — 호출부가 표면화(추측·폴백 금지).
    market: 'auction'|'gmarket' — 발송정책은 사이트별 값(iac/gmkt)이라 필요한 쪽을 고른다.
    """
    ai = detail.get("itemAddtionalInfo") or detail.get("itemAdditionalInfo") or {}
    ship = ai.get("shipping") or {}
    pol = ship.get("policy") or {}
    dp = ship.get("dispatchPolicyNo") or {}
    dispatch = dp.get("iac") if market == "auction" else dp.get("gmkt")
    notice = ai.get("officialNotice") or {}
    return {
        "place_no": pol.get("placeNo"),
        "dispatch_policy_no": dispatch or None,   # 0 = 그 사이트 정책 없음 → None 으로 표면화
        "return_addr_no": (ship.get("returnAndExchange") or {}).get("addrNo"),
        "delivery_company_no": ship.get("companyNo"),
        "official_notice_no": notice.get("officialNoticeNo"),
        "official_notice_details": notice.get("details") or [],
    }
