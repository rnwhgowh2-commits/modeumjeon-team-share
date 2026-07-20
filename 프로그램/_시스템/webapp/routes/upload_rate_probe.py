# -*- coding: utf-8 -*-
"""업로드 속도 한도 실측 라우트 — **쓰기 프로브**(조사용, 상시 기능 아님).

마켓 API 는 서버 IP 허용목록(54.116.196.90)에 묶여 있어 로컬 PC 에서는 인증 이전에
거부된다. 그래서 실측은 서버에서 돌 수밖에 없고, 이 라우트가 그 통로다.

  GET /api/upload-rate-probe/targets?market=coupang
      → 이 마켓에 등록된 상품·옵션 후보 (읽기 전용)

  GET /api/upload-rate-probe/baseline?market=&product_id=&option_id=
      → 현재 재고 확인 (읽기 전용). 여기서 200 이 안 나오면 측정 불가.

  GET /api/upload-rate-probe/noop-check?market=&product_id=&option_id=&n=3
      → 무변화 갱신 n 회. 마켓이 무변화를 받아주는지·응답시간이 어떤지 확인.

  GET /api/upload-rate-probe/burst?market=&product_id=&option_id=&max_calls=40
      → 간격 없이 연속 → 첫 429 직전까지 = 버스트 용량

  GET /api/upload-rate-probe/ramp?market=&product_id=&option_id=&hold=20
      → 계단식 증속(0.2→20 req/s). 처음 429 난 계단과 그 직전.

★ 안전
  - **무변화 갱신**이라 재고가 바뀌지 않는다. 상태를 남기지 않으므로 원복도 불필요.
  - 매 요청이 시작 전 baseline 을 잡고, 끝나고 **다시 읽어** 값이 그대로인지 확인한다.
    달라졌으면 응답에 `restored=false` 로 표면화한다(조용한 오염 금지).
  - 가격은 어떤 경로로도 건드리지 않는다.
  - `UPLOAD_RATE_PROBE=1` 일 때만 열린다. 끄면 즉시 닫힌다(재배포 대기 불필요).
"""
from __future__ import annotations

import os
import time

from flask import Blueprint, jsonify, request

bp = Blueprint("upload_rate_probe", __name__)

_MARKETS = ("coupang", "smartstore", "lotteon", "eleven11", "auction", "gmarket")
_MAX_CALLS_CAP = 6000         # 한 요청이 때릴 수 있는 최대 호출 수
_MAX_CONCURRENCY = 64         # 동시 호출 상한
_MAX_DURATION = 60.0          # load 1회 지속 상한(초)
_RAMP_STEPS = (0.2, 0.5, 1, 2, 3, 5, 8, 12, 20)


@bp.before_request
def _gate():
    """조사 기간에만 연다. 라이브에서 무인증으로 쓰기 API 를 두드릴 수 있으면 안 된다."""
    if (os.getenv("UPLOAD_RATE_PROBE") or "").strip() not in ("1", "true", "TRUE"):
        return jsonify({"ok": False,
                        "error": "프로브 비활성 — 서버 env UPLOAD_RATE_PROBE=1 필요"}), 404
    return None


def _args():
    market = (request.args.get("market") or "").strip()
    if market not in _MARKETS:
        return None, (jsonify({"ok": False, "error": f"market 이 잘못됨: {market!r}"}), 400)
    return {
        "market": market,
        "product_id": (request.args.get("product_id") or "").strip(),
        "option_id": (request.args.get("option_id") or "").strip(),
        "env_prefix": (request.args.get("env_prefix") or "").strip() or None,
    }, None


def _client(market: str, env_prefix):
    from lemouton.markets import order_export as _oe
    return _oe._account_client(market, env_prefix)


@bp.get("/api/upload-rate-probe/targets")
def targets():
    """이 마켓에 등록된 상품·옵션 후보 (읽기 전용, 마켓 API 미접촉)."""
    market = (request.args.get("market") or "").strip()
    if market not in _MARKETS:
        return jsonify({"ok": False, "error": f"market 이 잘못됨: {market!r}"}), 400
    limit = min(int(request.args.get("limit") or 20), 100)

    from shared.db import SessionLocal
    from lemouton.uploader.models import MarketRegistration
    with SessionLocal() as s:
        rows = (s.query(MarketRegistration)
                .filter(MarketRegistration.market == market)
                .filter(MarketRegistration.market_product_id.isnot(None))
                .filter(MarketRegistration.market_option_id.isnot(None))
                .limit(limit).all())
        out = [{"canonical_sku": r.canonical_sku,
                "product_id": r.market_product_id,
                "option_id": r.market_option_id,
                "status": getattr(r, "status", None)} for r in rows]
    return jsonify({"ok": True, "market": market, "count": len(out), "targets": out})


@bp.get("/api/upload-rate-probe/discover")
def discover():
    """마켓 API 로 **상품·옵션 후보를 직접 찾는다** (읽기 전용).

    market_registrations 는 연동한 마켓에만 행이 있다(쿠팡·스스뿐). 나머지는
    마켓 목록 API 로 실제 판매 상품을 뽑는다.

      롯데온   POST /product/v1/product/list        → data[].spdNo → 단품 sitmNo
      옥션·G   POST /item/v1/goods/search           → items[].goodsNo → 옵션 id
      11번가   목록 API 가 없다 → **주문내역**의 prdNo 를 쓴다 → 재고번호 prdStckNo
    """
    a, err = _args()
    if err:
        return err
    limit = min(int(request.args.get("limit") or 5), 20)
    cli = _client(a["market"], a["env_prefix"])
    if cli is None:
        return jsonify({"ok": False, "error": "클라이언트 생성 실패(키 미등록 의심)"}), 400

    m = a["market"]
    try:
        if m == "lotteon":
            found = _discover_lotteon(cli, limit)
        elif m in ("auction", "gmarket"):
            found = _discover_esm(cli, m, limit)
        elif m == "eleven11":
            found = _discover_eleven11(cli, a["env_prefix"], limit)
        elif m == "coupang":
            found = _discover_coupang(cli, limit)
        elif m == "smartstore":
            found = _discover_smartstore(cli, limit)
        else:
            return jsonify({"ok": False,
                            "error": f"{m}: /targets 를 쓰세요(연동 이력 있음)"}), 400
    except Exception as e:   # noqa: BLE001 — 실패는 그대로 표면화(빈 목록으로 위장 금지)
        return jsonify({"ok": False, "market": m,
                        "error": f"{type(e).__name__}: {e}"}), 500

    return jsonify({"ok": True, "market": m, "count": len(found),
                    "candidates": found,
                    "note": None if found else "판매 상품을 못 찾음 — 기간·판매상태 조건 확인"})


def _discover_lotteon(cli, limit):
    """상품 목록 → 각 상품의 단품(sitmNo) 1개까지 해석.

    ★ 파라미터를 쿼리로 바꿀 수 있게 열어 뒀다 — 500 이 나면 조건을 바꿔가며
      재배포 없이 시도해야 하기 때문. 지도 스펙(apiNo=93)의 필수는
      trGrpCd·trNo·regStrtDttm·regEndDttm 이고 slStatCd 는 선택이다.
      (slStatCd 문서 표기는 END/SALE/SOUT/STP 인데 응답 예시는 "20" 이라 모호 →
       기본은 **안 보낸다**. 보내려면 sl_stat_cd 쿼리로 명시.)
    """
    from datetime import datetime, timedelta, timezone
    from shared.platforms.lotteon.products import get_product_detail, extract_items

    cfg = getattr(cli, "_cfg", None) or {}
    days = min(int(request.args.get("days") or 90), 730)
    now = datetime.now(timezone.utc) + timedelta(hours=9)
    body = {"trGrpCd": request.args.get("tr_grp_cd") or cfg.get("tr_grp_cd", "SR"),
            "trNo": request.args.get("tr_no") or cfg.get("tr_no", ""),
            "regStrtDttm": (now - timedelta(days=days)).strftime("%Y%m%d%H%M%S"),
            "regEndDttm": now.strftime("%Y%m%d%H%M%S")}
    sl = (request.args.get("sl_stat_cd") or "").strip()
    if sl:
        body["slStatCd"] = sl
    # ★ 지도에 접수된 params 가 전체 스펙이 아닐 수 있다(res.note = "전체 스펙 apiNo=93").
    #   extra 로 임의 필드를 얹어 재배포 없이 시험한다. 예: extra={"pageNo":1,"rowsPerPage":100}
    extra = (request.args.get("extra") or "").strip()
    if extra:
        import json as _j
        try:
            body.update(_j.loads(extra))
        except ValueError as e:
            raise RuntimeError(f"extra 파싱 실패({e}) — JSON 이어야 한다: {extra}")
    try:
        resp = cli.request(method="POST",
                           path="/v1/openapi/product/v1/product/list", body=body)
    except Exception as e:   # noqa: BLE001 — 어떤 조건에서 깨졌는지 보여준다
        raise RuntimeError(f"product/list 실패 body={body} :: {type(e).__name__}: {e}")
    # ★ 응답 구조를 모르면 0건이 '없다'인지 '못 읽었다'인지 구분 못 한다.
    #   raw=1 이면 원본을 그대로 돌려준다(진단용).
    if (request.args.get("raw") or "") in ("1", "true"):
        import json as _j
        raise RuntimeError("RAW " + _j.dumps(resp, ensure_ascii=False)[:1500])
    data = (resp or {}).get("data") or []
    if isinstance(data, dict):        # data 가 dict 로 감싸져 오는 경우
        for k in ("list", "items", "products", "spdList"):
            if isinstance(data.get(k), list):
                data = data[k]
                break
    out = []
    for row in data[:limit]:
        spd = str(row.get("spdNo") or "").strip()
        if not spd:
            continue
        item = {"product_id": spd, "sell_status": row.get("slStatCd"),
                "option_id": None, "stock": None}
        try:
            for it in extract_items(get_product_detail(spd, client=cli)):
                item["option_id"] = str(it.get("sitm_no"))
                item["stock"] = it.get("stock")
                break
        except Exception as e:   # noqa: BLE001
            item["detail_error"] = f"{type(e).__name__}: {e}"
        out.append(item)
    return out


def _discover_esm(cli, market, limit):
    """goods/search → 마스터번호 → 추천옵션 id. ★ 분당 30회 제한 API."""
    from shared.platforms.esm.inventory import get_recommended_options, _option_id_of

    resp = cli.request(method="POST", path="/item/v1/goods/search",
                       body={"siteId": "1" if market == "auction" else "2",
                             "sellStatus": "11", "pageIndex": 1, "pageSize": limit})
    body = resp if isinstance(resp, dict) else {}
    items = (body.get("items") or (body.get("data") or {}).get("items") or [])
    out = []
    for row in items[:limit]:
        gno = str(row.get("goodsNo") or "").strip()
        if not gno:
            continue
        item = {"product_id": gno, "goods_name": row.get("goodsName"),
                "option_id": None}
        try:
            for d in (get_recommended_options(gno, client=cli) or []):
                item["option_id"] = _option_id_of(d)
                break
        except Exception as e:   # noqa: BLE001
            item["detail_error"] = f"{type(e).__name__}: {e}"
        out.append(item)
    return out


def _discover_smartstore(cli, limit):
    """이 **계정이 소유한** 상품 → 옵션ID 까지. 계정별/IP별 판별에 필수.

    POST /external/v1/products/search  (지도: 「상품 목록 조회」)
    응답 contents[].channelProducts[].{originProductNo, channelProductNo}
    """
    # 지도에 본문 상세가 미접수(body_fields:12 만 표기)라 형식을 모른다.
    #   extra 로 본문을 통째로 바꿔가며 재배포 없이 시험한다.
    body = {"productStatusTypes": ["SALE"], "page": 1,
            "size": max(1, min(limit * 3, 50))}
    extra = (request.args.get("extra") or "").strip()
    if extra:
        import json as _j
        try:
            body = _j.loads(extra)
        except ValueError as e:
            raise RuntimeError(f"extra 파싱 실패({e}): {extra}")
    try:
        resp = cli.request("POST", "/external/v1/products/search", body)
    except Exception as e:   # noqa: BLE001 — 보낸 본문을 그대로 실어 보여준다
        raise RuntimeError(f"products/search 실패 body={body} :: {type(e).__name__}: {e}")
    if (request.args.get("raw") or "") in ("1", "true"):
        import json as _j
        raise RuntimeError("RAW " + _j.dumps(resp, ensure_ascii=False)[:1200])
    rows = (resp or {}).get("contents") or []
    out = []
    for row in rows:
        chans = row.get("channelProducts") or []
        origin = row.get("originProductNo") or (chans[0].get("originProductNo") if chans else None)
        if not origin:
            continue
        item = {"product_id": str(origin), "option_id": None, "stock": None,
                "name": ((chans[0].get("name") if chans else "") or "")[:36]}
        try:
            from shared.platforms.smartstore.get_options import fetch_product_options
            r = fetch_product_options(int(origin), client=cli)
            for o in (getattr(r, "options", None) or []):
                item["option_id"] = str(o.option_id)
                item["stock"] = o.stock
                break
        except Exception as e:   # noqa: BLE001
            item["detail_error"] = f"{type(e).__name__}: {e}"
        out.append(item)
        if len([o for o in out if o.get("option_id")]) >= limit:
            break
    return out


def _discover_coupang(cli, limit):
    """이 **계정이 소유한** 상품 → vendorItemId 까지.

    계정별/IP별 판별에 필수 — 계정 B 는 A 의 상품에 접근 권한이 없어 400 이 난다.
    (실제로 그 설계로 판별에 실패했다.) B 는 **자기 상품**으로 쏴야 한다.
    GET .../marketplace/seller-products?vendorId=&maxPerPage=
    """
    cfg = getattr(cli, "_cfg", None) or {}
    vendor = cfg.get("vendor_id") or ""
    # ★ 쿠팡 CEA HMAC 은 method+path+query 를 **분리해서** 서명한다.
    #   query 를 path 에 붙여 보내면 401 Invalid signature 가 난다(실제로 겪음).
    path = "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products"
    query = f"vendorId={vendor}&maxPerPage={max(1, min(limit * 3, 50))}"
    resp = cli.request(method="GET", path=path, query=query)
    rows = (resp or {}).get("data") or []
    out = []
    for row in rows:
        spid = row.get("sellerProductId")
        if not spid:
            continue
        item = {"seller_product_id": str(spid),
                "name": (row.get("sellerProductName") or "")[:40],
                "product_id": None, "option_id": None, "stock": None}
        # 등록상품ID → 옵션(vendorItemId) 해석
        try:
            det = cli.request(method="GET", path=(
                "/v2/providers/seller_api/apis/api/v1/marketplace/"
                f"seller-products/{spid}"))
            items = ((det or {}).get("data") or {}).get("items") or []
            for it in items:
                vid = it.get("vendorItemId")
                if vid:
                    item["product_id"] = str(spid)
                    item["option_id"] = str(vid)
                    break
        except Exception as e:   # noqa: BLE001
            item["detail_error"] = f"{type(e).__name__}: {e}"
        out.append(item)
        if len([o for o in out if o.get("option_id")]) >= limit:
            break
    return out


def _discover_eleven11(cli, env_prefix, limit):
    """11번가 **상품 목록** — `prodmarket` 조건검색.

    ★ 「다중 상품 조회」라는 이름 때문에 "번호를 넣어야 하는 것"으로 오해했었다.
      실제로는 prdNo 가 **선택**이고 selStatCd(판매상태)·기간으로 조건검색이 된다.
      selStatCd: 103=판매중 104=품절 105=전시중지 …
      schDateType: 1=생성일 2=판매일 4=수정일 / schBgnDt·schEndDt 동반 필수
    주문내역 폴백은 유지 — 상품조회가 비면 주문에서 prdNo 를 줍는다.
    """
    from datetime import datetime, timedelta
    from shared.platforms.eleven11.stocks_query import get_stocks

    prd_nos = []
    try:
        until = datetime.now()
        since = until - timedelta(days=365)
        body = ('<?xml version="1.0" encoding="euc-kr"?>'
                "<SearchProduct>"
                "<selStatCd>103</selStatCd>"
                "<schDateType>1</schDateType>"
                f"<schBgnDt>{since.strftime('%Y%m%d')}</schBgnDt>"
                f"<schEndDt>{until.strftime('%Y%m%d')}</schEndDt>"
                "</SearchProduct>")
        xml = cli.request("POST", "/rest/prodmarketservice/prodmarket", body)
        import re as _re
        prd_nos = _re.findall(r"<prdNo>(\d+)</prdNo>", xml if isinstance(xml, str) else str(xml))
    except Exception as e:   # noqa: BLE001 — 폴백으로 넘어가되 원인은 남긴다
        prd_nos = []
        _first_err = f"{type(e).__name__}: {e}"

    out = []
    for prd in dict.fromkeys(prd_nos):
        item = {"product_id": prd, "option_id": None, "stock": None,
                "via": "prodmarket"}
        try:
            for s2 in (get_stocks(prd, client=cli) or []):
                if s2.get("prd_stck_no"):
                    item["option_id"] = str(s2["prd_stck_no"])
                    item["stock"] = s2.get("stock")
                    break
        except Exception as e:   # noqa: BLE001
            item["detail_error"] = f"{type(e).__name__}: {e}"
        out.append(item)
        if len(out) >= limit:
            return out

    # 폴백: 주문내역의 prdNo
    from shared.platforms.eleven11.orders import iter_orders
    until = datetime.now()
    since = until - timedelta(days=60)
    seen = {o["product_id"] for o in out}
    for od in (iter_orders(since, until, client=cli) or []):
        prd = str(od.get("prdNo") or "").strip()
        if not prd or prd in seen:
            continue
        seen.add(prd)
        item = {"product_id": prd, "product_name": od.get("prdNm"),
                "option_id": None, "stock": None, "via": "orders"}
        try:
            for s in (get_stocks(prd, client=cli) or []):
                if s.get("prd_stck_no"):
                    item["option_id"] = str(s["prd_stck_no"])
                    item["stock"] = s.get("stock")
                    break
        except Exception as e:   # noqa: BLE001
            item["detail_error"] = f"{type(e).__name__}: {e}"
        out.append(item)
        if len(out) >= limit:
            break
    return out


@bp.get("/api/upload-rate-probe/resolve")
def resolve():
    """상품의 **옵션 목록을 날것으로** 돌려준다 (읽기 전용, 진단용).

    baseline 은 못 읽으면 None 만 준다(폴백 금지 원칙상 추정을 안 하므로).
    그래서 어떤 옵션ID 가 실제로 존재하는지, 왜 실패했는지 안 보인다.
    이 라우트는 **예외를 그대로 표면화**해서 원인을 보여준다.
    """
    a, err = _args()
    if err:
        return err
    cli = _client(a["market"], a["env_prefix"])
    if cli is None:
        return jsonify({"ok": False, "error": "클라이언트 생성 실패(키 미등록 의심)"}), 400

    m, pid = a["market"], a["product_id"]
    try:
        if m == "lotteon":
            from shared.platforms.lotteon.products import get_product_detail, extract_items
            detail = get_product_detail(pid, client=cli)
            items = extract_items(detail)
            return jsonify({"ok": True, "market": m, "product_id": pid,
                            "name": detail.get("spdNm") or detail.get("pdNm"),
                            "options": [{"option_id": str(i.get("sitm_no")),
                                         "color": i.get("color"), "size": i.get("size"),
                                         "stock": i.get("stock")} for i in items][:20],
                            "raw_keys": sorted(list(detail.keys()))[:25]})
        if m == "eleven11":
            from shared.platforms.eleven11.stocks_query import get_stocks
            out = {"ok": True, "market": m, "product_id": pid}
            # 재고(옵션) 목록
            try:
                rows = get_stocks(pid, client=cli) or []
                out["options"] = [{"option_id": r.get("prd_stck_no"),
                                   "opt_no": r.get("opt_no"),
                                   "name": r.get("dtl_opt_nm") or r.get("opt_nm"),
                                   "stock": r.get("stock")} for r in rows][:20]
            except Exception as e:   # noqa: BLE001
                out["stocks_error"] = f"{type(e).__name__}: {e}"
                out["options"] = []
            # ★ 빈 목록이 '상품이 없다'인지 '옵션이 없다'인지 구분한다.
            #   상품 자체 조회로 존재 여부를 확인 (GET /rest/prodmarketservice/prodmarket/{prdNo})
            try:
                raw = cli.request("GET", f"/rest/prodmarketservice/prodmarket/{pid}", None)
                txt = raw if isinstance(raw, str) else str(raw)
                out["product_exists"] = ("prdNo" in txt) or ("prdNm" in txt)
                out["product_raw_head"] = txt[:400]
            except Exception as e:   # noqa: BLE001
                out["product_lookup_error"] = f"{type(e).__name__}: {e}"
            out["is_single_product"] = (not out["options"]) and out.get("product_exists") is True
            return jsonify(out)
        if m in ("auction", "gmarket"):
            from shared.platforms.esm.inventory import get_recommended_options, _option_id_of
            from shared.platforms.esm.products import get_goods_detail
            out = {"ok": True, "market": m, "product_id": pid}
            try:
                opts = get_recommended_options(pid, client=cli) or []
                out["options"] = [{"option_id": _option_id_of(d)} for d in opts][:20]
            except Exception as e:   # noqa: BLE001 — 옵션 없는 단일상품일 수 있다
                out["recommended_options_error"] = f"{type(e).__name__}: {e}"
                out["options"] = []
            try:
                det = get_goods_detail(pid, client=cli)
                out["goods_detail_keys"] = sorted(list(det.keys()))[:25]
                # 재고가 어디 들어있는지 눈으로 확인 (키 이름을 추측하지 않기 위해)
                import json as _j
                out["stock_like"] = {k: v for k, v in det.items()
                                     if any(w in str(k).lower()
                                            for w in ("qty", "stock", "quantity"))}
                out["detail_head"] = _j.dumps(det, ensure_ascii=False)[:600]
                out["is_single_product"] = not out["options"]
            except Exception as e:   # noqa: BLE001
                out["goods_detail_error"] = f"{type(e).__name__}: {e}"
            return jsonify(out)
        if m in ("coupang", "smartstore"):
            from lemouton.uploader.market_fetch import fetch_market_options
            r = fetch_market_options(m, pid)
            return jsonify({"ok": r.success, "market": m, "product_id": pid,
                            "name": r.product_name, "error": r.error,
                            "options": [{"option_id": o.option_id, "stock": o.stock}
                                        for o in r.options][:20]})
    except Exception as e:   # noqa: BLE001 — 원인을 숨기지 않는다
        return jsonify({"ok": False, "market": m, "product_id": pid,
                        "error": f"{type(e).__name__}: {e}"}), 500
    return jsonify({"ok": False, "error": f"미지원 마켓: {m}"}), 400


@bp.get("/api/upload-rate-probe/baseline")
def baseline():
    """현재 재고만 읽는다. 쓰기 없음."""
    a, err = _args()
    if err:
        return err
    from lemouton.markets.upload_rate_probe import read_stock

    cli = _client(a["market"], a["env_prefix"])
    if cli is None:
        return jsonify({"ok": False, "error": "클라이언트 생성 실패(키 미등록 의심)"}), 400
    t0 = time.monotonic()
    stock = read_stock(a["market"], client=cli,
                       product_id=a["product_id"], option_id=a["option_id"])
    return jsonify({"ok": stock is not None, "market": a["market"],
                    "product_id": a["product_id"], "option_id": a["option_id"],
                    "current_stock": stock,
                    "elapsed_ms": round((time.monotonic() - t0) * 1000, 1),
                    "note": None if stock is not None
                            else "재고를 못 읽음 — 측정 불가(상품·옵션ID 확인)"})


def _prepare(a):
    """클라이언트 + baseline. 실패하면 (None, None, 오류응답)."""
    from lemouton.markets.upload_rate_probe import Baseline, ProbeUnsafe

    cli = _client(a["market"], a["env_prefix"])
    if cli is None:
        return None, None, (jsonify({"ok": False,
                                     "error": "클라이언트 생성 실패(키 미등록 의심)"}), 400)
    try:
        base = Baseline.capture(a["market"], client=cli,
                                product_id=a["product_id"], option_id=a["option_id"])
    except ProbeUnsafe as e:
        return None, None, (jsonify({"ok": False, "error": str(e)}), 400)
    return cli, base, None


def _finish(a, cli, base, payload: dict):
    """끝나고 재고가 원래대로인지 **다시 읽어** 확인한다."""
    from lemouton.markets.upload_rate_probe import read_stock

    cur = read_stock(a["market"], client=cli,
                     product_id=a["product_id"], option_id=a["option_id"])
    payload["original_stock"] = base.original_stock
    payload["final_stock"] = cur
    payload["restored"] = (cur is not None and int(cur) == int(base.original_stock))
    if not payload["restored"]:
        payload["warning"] = ("재고가 원래 값과 다르다 — 수기 확인 필요 "
                              f"(원래 {base.original_stock} → 지금 {cur})")
    return jsonify(payload)


@bp.get("/api/upload-rate-probe/noop-check")
def noop_check():
    """무변화 갱신 n 회. 마켓이 받아주는지·응답시간이 조회보다 긴지 본다."""
    a, err = _args()
    if err:
        return err
    n = min(int(request.args.get("n") or 3), 10)
    from lemouton.markets.upload_rate_probe import noop_write

    cli, base, err = _prepare(a)
    if err:
        return err

    calls = []
    for _ in range(n):
        r = noop_write(a["market"], client=cli, product_id=a["product_id"],
                       option_id=a["option_id"], known_stock=base.original_stock)
        calls.append({"status": r.status, "elapsed_ms": round(r.elapsed_ms, 1),
                      "rate_limited": r.is_rate_limited, "error": r.error,
                      "headers": _rate_headers(r.headers)})
    return _finish(a, cli, base, {"ok": True, "market": a["market"],
                                  "mode": "noop", "calls": calls})


@bp.get("/api/upload-rate-probe/burst")
def burst():
    """간격 없이 연속 호출 → 첫 429 직전까지 = 버스트 용량."""
    a, err = _args()
    if err:
        return err
    max_calls = min(int(request.args.get("max_calls") or 40), _MAX_CALLS_CAP)
    from lemouton.markets.upload_rate_probe import noop_write, measure_burst

    cli, base, err = _prepare(a)
    if err:
        return err

    seen = []

    def probe():
        r = noop_write(a["market"], client=cli, product_id=a["product_id"],
                       option_id=a["option_id"], known_stock=base.original_stock)
        seen.append({"status": r.status, "ms": round(r.elapsed_ms, 1),
                     "error": r.error, "headers": _rate_headers(r.headers)})
        return r

    t0 = time.monotonic()
    res = measure_burst(probe, max_calls=max_calls)
    res.update(ok=True, market=a["market"], mode="burst",
               wall_sec=round(time.monotonic() - t0, 2),
               observed_per_sec=(round(len(seen) / max(0.001, time.monotonic() - t0), 2)),
               calls=seen[-10:], total_calls=len(seen),
               rate_headers_seen=[c["headers"] for c in seen if c.get("headers")][-3:])
    return _finish(a, cli, base, res)


@bp.get("/api/upload-rate-probe/ramp")
def ramp():
    """계단식 증속. 각 계단을 hold 초 유지하며 429 가 나면 그 계단이 상한."""
    a, err = _args()
    if err:
        return err
    hold = min(float(request.args.get("hold") or 20), 60.0)
    cooldown = min(float(request.args.get("cooldown") or 10), 60.0)
    from lemouton.markets.upload_rate_probe import noop_write, ramp_up

    cli, base, err = _prepare(a)
    if err:
        return err

    log = []
    budget = {"used": 0}

    def holds_at(rate: float) -> bool:
        interval = 1.0 / rate
        deadline = time.monotonic() + hold
        n = fails = 0
        while time.monotonic() < deadline:
            if budget["used"] >= _MAX_CALLS_CAP:
                break
            r = noop_write(a["market"], client=cli, product_id=a["product_id"],
                           option_id=a["option_id"], known_stock=base.original_stock)
            budget["used"] += 1
            n += 1
            if r.is_rate_limited:
                fails += 1
                log.append({"rate": rate, "calls": n, "verdict": "429",
                            "note": "한도 도달"})
                time.sleep(cooldown)
                return False
            if r.status is None or r.status >= 400:
                log.append({"rate": rate, "calls": n, "verdict": f"error {r.status}",
                            "note": r.error})
                time.sleep(cooldown)
                return False
            time.sleep(interval)
        log.append({"rate": rate, "calls": n, "verdict": "ok"})
        time.sleep(cooldown)
        return True

    t0 = time.monotonic()
    res = ramp_up(holds_at, steps=_RAMP_STEPS)
    res.update(ok=True, market=a["market"], mode="ramp", steps=log,
               total_calls=budget["used"],
               wall_sec=round(time.monotonic() - t0, 2))
    if res.get("last_ok"):
        from lemouton.markets.upload_rate_probe import recommended_rate, calls_per_upload
        res["calls_per_upload"] = calls_per_upload(a["market"])
        res["recommended_calls_per_sec"] = recommended_rate(res["last_ok"])
        res["recommended_uploads_per_sec"] = round(
            res["recommended_calls_per_sec"] / calls_per_upload(a["market"]), 3)
    return _finish(a, cli, base, res)


@bp.get("/api/upload-rate-probe/load")
def load():
    """**동시** 호출로 목표 속도를 만들어 429 지점을 찾는다.

    순차 호출은 왕복지연(~200ms)에 묶여 5/s 를 못 넘는다. 마켓 한도가 그보다
    높으면 순차로는 영원히 429 를 못 본다 — 그래서 동시 호출이 필요하다.

    concurrency=N 개 스레드가 duration 초 동안 쉬지 않고 무변화 갱신을 던진다.
    """
    a, err = _args()
    if err:
        return err
    conc = max(1, min(int(request.args.get("concurrency") or 4), _MAX_CONCURRENCY))
    duration = max(1.0, min(float(request.args.get("duration") or 8), _MAX_DURATION))
    from lemouton.markets.upload_rate_probe import noop_write

    cli, base, err = _prepare(a)
    if err:
        return err

    import threading
    from concurrent.futures import ThreadPoolExecutor

    lock = threading.Lock()
    tally = {"ok": 0, "r429": 0, "other": 0, "sent": 0}
    statuses = []
    hdrs = []
    deadline = time.monotonic() + duration

    def worker():
        # 스레드마다 자기 클라이언트 — 클라 내부 상태 공유로 인한 오염 방지
        c = _client(a["market"], a["env_prefix"]) or cli
        while time.monotonic() < deadline:
            with lock:
                if tally["sent"] >= _MAX_CALLS_CAP:
                    return
                tally["sent"] += 1
            r = noop_write(a["market"], client=c, product_id=a["product_id"],
                           option_id=a["option_id"], known_stock=base.original_stock)
            with lock:
                if r.is_rate_limited:
                    tally["r429"] += 1
                elif r.status == 200:
                    tally["ok"] += 1
                else:
                    tally["other"] += 1
                    if len(statuses) < 8:
                        statuses.append({"status": r.status, "error": r.error})
                if r.headers and len(hdrs) < 3:
                    h = _rate_headers(r.headers)
                    if h:
                        hdrs.append(h)

    t0 = time.monotonic()
    with ThreadPoolExecutor(max_workers=conc) as ex:
        for _ in range(conc):
            ex.submit(worker)
    wall = time.monotonic() - t0

    res = {"ok": True, "market": a["market"], "mode": "load",
           "concurrency": conc, "duration_req": duration,
           "wall_sec": round(wall, 2),
           "sent": tally["sent"], "success": tally["ok"],
           "rate_limited_429": tally["r429"], "other_errors": tally["other"],
           "achieved_calls_per_sec": round(tally["sent"] / max(0.001, wall), 2),
           "success_calls_per_sec": round(tally["ok"] / max(0.001, wall), 2),
           "hit_429": tally["r429"] > 0,
           "error_samples": statuses, "rate_headers": hdrs}
    if tally["sent"] >= _MAX_CALLS_CAP:
        res["note"] = f"호출 상한 {_MAX_CALLS_CAP} 도달로 조기 종료 — duration 이 아니라 상한이 끊었다"
    return _finish(a, cli, base, res)


@bp.get("/api/upload-rate-probe/keytest")
def keytest():
    """**제한 단위 판별** — 계정별인가, IP(우리 서버) 공유인가.

    계정 A 로 429 가 날 때까지 민 다음, **429 직후 즉시** 계정 B 로 1발 쏜다.
      B 가 200  → 제한은 **계정(키)별** (계정 늘리면 총량 증가)
      B 도 429  → 제한은 **IP/판매자 전역** (계정 늘려도 소용없음)
    두 계정 모두 같은 서버 IP 에서 나가므로, 이 테스트는 '계정별 vs 공유'를 가른다.
    (IP별 vs 전역을 더 가르려면 두 번째 IP 가 필요 — 현재 미확보)

    ★ 429 를 못 보면 판별 자체가 불가능하다 → verdict='판별불가(429 미발생)'
    """
    a, err = _args()
    if err:
        return err
    pb = (request.args.get("env_prefix_b") or "").strip()
    if not pb:
        return jsonify({"ok": False, "error": "env_prefix_b(두 번째 계정) 필요"}), 400
    # ★ 계정 B 는 **자기 소유 상품**으로 쏴야 한다.
    #   A 의 상품을 B 로 부르면 권한 없음(400)이라 판별 자체가 불가능하다 — 실제로 겪었다.
    pid_b = (request.args.get("product_id_b") or "").strip()
    oid_b = (request.args.get("option_id_b") or "").strip()
    if not pid_b or not oid_b:
        return jsonify({"ok": False,
                        "error": "product_id_b·option_id_b(계정 B 소유 상품) 필요 — "
                                 "A 의 상품을 B 로 부르면 권한없음 400 이라 판별 불가"}), 400
    conc = max(1, min(int(request.args.get("concurrency") or 16), _MAX_CONCURRENCY))
    duration = max(1.0, min(float(request.args.get("duration") or 25), _MAX_DURATION))
    from lemouton.markets.upload_rate_probe import noop_write

    cli, base, err = _prepare(a)
    if err:
        return err
    cli_b = _client(a["market"], pb)
    if cli_b is None:
        return jsonify({"ok": False, "error": f"계정 B({pb}) 클라이언트 생성 실패"}), 400

    import threading
    from concurrent.futures import ThreadPoolExecutor

    lock = threading.Lock()
    st = {"sent": 0, "ok": 0, "r429": 0, "other": 0,
          "b_status": None, "b_done": False, "first_429_at": None}
    deadline = time.monotonic() + duration

    # 계정 B 의 기준선(자기 상품) — 못 읽으면 판별 불가
    from lemouton.markets.upload_rate_probe import read_stock
    stock_b = read_stock(a["market"], client=cli_b, product_id=pid_b, option_id=oid_b)
    if stock_b is None:
        return jsonify({"ok": False,
                        "error": f"계정 B 상품({pid_b}/{oid_b}) 재고를 못 읽음 — "
                                 f"B 소유 상품이 맞는지 확인"}), 400

    def fire_b():
        """429 직후 즉시 계정 B 가 **자기 상품**으로 1발."""
        r = noop_write(a["market"], client=cli_b, product_id=pid_b,
                       option_id=oid_b, known_stock=stock_b)
        with lock:
            st["b_status"] = r.status
            st["b_elapsed_ms"] = round(r.elapsed_ms, 1)
            st["b_error"] = r.error

    def worker():
        c = _client(a["market"], a["env_prefix"]) or cli
        while time.monotonic() < deadline:
            with lock:
                if st["sent"] >= _MAX_CALLS_CAP:
                    return
                st["sent"] += 1
            r = noop_write(a["market"], client=c, product_id=a["product_id"],
                           option_id=a["option_id"], known_stock=base.original_stock)
            trigger = False
            with lock:
                if r.is_rate_limited:
                    st["r429"] += 1
                    if not st["b_done"]:
                        st["b_done"] = True
                        st["first_429_at"] = st["sent"]
                        trigger = True
                elif r.status == 200:
                    st["ok"] += 1
                else:
                    st["other"] += 1
            if trigger:
                fire_b()          # 락 밖에서 — B 호출이 A 스레드를 막지 않게

    t0 = time.monotonic()
    with ThreadPoolExecutor(max_workers=conc) as ex:
        for _ in range(conc):
            ex.submit(worker)
    wall = time.monotonic() - t0

    if st["r429"] == 0:
        verdict, reason = "판별불가(429 미발생)", "계정 A 가 한도에 안 닿아 비교 자체가 불가"
    elif st["b_status"] == 200:
        verdict, reason = "계정(키)별", "A 가 429 인 순간 B 는 정상 → 계정을 늘리면 총량이 는다"
    elif st["b_status"] == 429:
        verdict, reason = "IP/판매자 전역", "A 가 429 인 순간 B 도 429 → 계정을 늘려도 소용없다"
    else:
        verdict, reason = "판별불가", f"B 응답이 {st['b_status']} — 429/200 이 아니라 판정 불가"

    res = {"ok": True, "market": a["market"], "mode": "keytest",
           "account_a": a["env_prefix"] or "(기본)", "account_b": pb,
           "target_a": f"{a['product_id']}/{a['option_id']}",
           "target_b": f"{pid_b}/{oid_b}", "b_original_stock": stock_b,
           "concurrency": conc, "wall_sec": round(wall, 2),
           "sent": st["sent"], "success": st["ok"], "rate_limited_429": st["r429"],
           "other_errors": st["other"],
           "achieved_calls_per_sec": round(st["sent"] / max(0.001, wall), 2),
           "first_429_at_call": st["first_429_at"],
           "b_status": st["b_status"], "b_elapsed_ms": st.get("b_elapsed_ms"),
           "verdict": verdict, "reason": reason}
    return _finish(a, cli, base, res)


def _rate_headers(headers) -> dict:
    """한도 관련 헤더만 추린다(어떤 마켓이 뭘 주는지 모르니 후보를 넓게)."""
    if not headers:
        return {}
    want = ("ratelimit", "rate-limit", "retry-after", "quota", "x-rate",
            "gncp-gw", "throttle", "remaining")
    return {k: v for k, v in dict(headers).items()
            if any(w in str(k).lower() for w in want)}
