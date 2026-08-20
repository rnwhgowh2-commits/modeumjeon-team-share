# -*- coding: utf-8 -*-
"""상품관리 설계용 실측 3차 — 지도 정독으로 찾은 것을 확증한다. 읽기 전용.

지도(판매처 > 데이터 코드 지도)를 전수 정독해 나온 것:

  ① ESM 상품목록 API 의 검색·상태 조건은 **`query` 객체 안에** 넣어야 한다.
     지도 example: {"query":{"sellStatus":[11]},"pageIndex":1,"pageSize":10}
     우리 코드(esm/products.py search_goods)는 최상위에 넣고 있다 → ESM 이 조용히 무시.
     2차 실측에서 없는 낱말로 검색해도 전체가 나온 이유가 이것으로 보인다. 여기서 확증한다.

  ② 롯데온 상품목록 응답은 지도상 `spdNo`(상품번호)·`slStatCd`(상태) 뿐이다.
     상품명이 없으면 **롯데온 14만 건은 이름으로 찾을 수 있는 캐시를 만들 수 없다**
     (상품마다 상세조회 = 14만 호출). 설계가 갈리는 지점이라 실제 응답을 열어 본다.

  ③ 쿠팡 `seller-products/inflow-status` 는 `registeredCount`(등록 상품수)를 준다.
     페이징 없이 총건수를 한 번에 얻는 길 — 대시보드에 그대로 쓸 수 있는지 본다.

  ④ 스마트스토어 상품명 검색 요청 필드명은 지도 params 가 비어 있어(플레이스홀더) 미상.
     후보를 더 던져 본다.
"""
from __future__ import annotations

import json
import os
from typing import Any

KEYWORD = "니트"


def _err(e: Exception) -> str:
    return f"{type(e).__name__}: {str(e)[:220]}"


def _pick(market: str):
    from shared.db import SessionLocal
    from lemouton.sourcing.models_v2 import UploadAccount
    s = SessionLocal()
    try:
        a = (s.query(UploadAccount)
             .filter(UploadAccount.is_active.is_(True), UploadAccount.market == market)
             .order_by(UploadAccount.account_key).first())
        return (a.account_key, a.env_prefix) if a else None
    finally:
        s.close()


# ── ① ESM: query 래퍼가 정답인가 ───────────────────────────────
def probe1_esm_query_wrapper() -> dict:
    from lemouton.uploader.market_fetch import _esm_client
    from shared.platforms import AUCTION
    got = _pick("auction")
    if not got:
        return {"skip": "옥션 계정 없음"}
    account_key, env_prefix = got
    c = _esm_client("auction", env_prefix)
    path = AUCTION["paths"]["search"]
    out: dict[str, Any] = {"account": account_key, "cases": {}}

    def call(label: str, body: dict):
        try:
            r = c.request(method="POST", path=path, body=body)
            data = r.get("data") if isinstance(r, dict) and "data" in r else r
            if isinstance(data, dict):
                out["cases"][label] = {"totalItems": data.get("totalItems"),
                                       "resultCode": r.get("resultCode")}
            else:
                out["cases"][label] = {"raw": str(r)[:200]}
        except Exception as e:
            out["cases"][label] = f"실패 {_err(e)}"

    base = {"pageIndex": 1, "pageSize": 3}
    call("A. 조건없음", dict(base))
    # 지금 우리 코드 방식(최상위) — 무시될 것으로 예상
    call("B. 최상위 sellStatus=11 (현재 코드 방식)", {**base, "sellStatus": "11"})
    # 지도 example 방식(query 래퍼 + 배열)
    call("C. query.sellStatus=[11] (지도 방식)", {**base, "query": {"sellStatus": [11]}})
    call("D. query.sellStatus=[21] 판매중지", {**base, "query": {"sellStatus": [21]}})
    call("E. query.sellStatus=[31] 품절", {**base, "query": {"sellStatus": [31]}})
    call("F. query.keyword=니트", {**base, "query": {"keyword": KEYWORD}})
    call("G. query.keyword=없는말", {**base, "query": {"keyword": "zzzzqqq없는말"}})
    call("H. query.siteId=[1] 옥션만", {**base, "query": {"siteId": [1]}})
    call("I. query.siteId=[2] 지마켓만", {**base, "query": {"siteId": [2]}})

    tots = {k: v.get("totalItems") for k, v in out["cases"].items() if isinstance(v, dict)}
    out["totals"] = tots
    vals = [v for k, v in tots.items() if k.startswith(("C", "D", "E", "F", "G"))]
    out["판정"] = ("★ query 래퍼가 정답 — 값이 갈림" if len(set(vals)) > 1
                 else "query 래퍼도 무시됨 — 다른 원인")
    return out


# ── ② 롯데온: 목록이 상품명을 주는가 ────────────────────────────
def probe2_lotteon_row() -> dict:
    from lemouton.uploader.market_fetch import _lotteon_client
    from shared.platforms import LOTTEON
    from datetime import datetime, timedelta
    got = _pick("lotteon")
    if not got:
        return {"skip": "롯데온 계정 없음"}
    account_key, env_prefix = got
    c = _lotteon_client(env_prefix)
    cfg = getattr(c, "_cfg", None) or LOTTEON
    now = datetime.now()
    out: dict[str, Any] = {"account": account_key}
    try:
        r = c.request(method="POST", path=cfg["paths"]["list"], body={
            "trGrpCd": cfg.get("tr_grp_cd", "SR"), "trNo": cfg.get("tr_no", ""),
            "regStrtDttm": (now - timedelta(days=365)).strftime("%Y%m%d%H%M%S"),
            "regEndDttm": now.strftime("%Y%m%d%H%M%S"),
            "pageNo": 1, "rowsPerPage": 3,
        })
        data = r.get("data")
        rows = data if isinstance(data, list) else (
            next((v for v in (data or {}).values() if isinstance(v, list)), []))
        out["dataCount"] = r.get("dataCount")
        out["행_개수"] = len(rows)
        if rows:
            out["행_필드이름"] = sorted(rows[0].keys())
            out["행_샘플"] = {k: str(v)[:60] for k, v in list(rows[0].items())[:30]}
        out["상품명_있나"] = any(
            k for k in (rows[0].keys() if rows else [])
            if any(t in k.lower() for t in ("nm", "name", "title")))
    except Exception as e:
        out["fatal"] = _err(e)
    return out


# ── ③ 쿠팡: 등록 상품수를 한 번에 주는가 ────────────────────────
def probe3_coupang_inflow() -> dict:
    from lemouton.uploader.market_fetch import _coupang_client
    from shared.db import SessionLocal
    from lemouton.sourcing.models_v2 import UploadAccount
    s = SessionLocal()
    try:
        accs = (s.query(UploadAccount)
                .filter(UploadAccount.is_active.is_(True),
                        UploadAccount.market == "coupang")
                .order_by(UploadAccount.account_key).all())
        targets = [(a.account_key, a.env_prefix) for a in accs]
    finally:
        s.close()

    path = "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products/inflow-status"
    out: dict[str, Any] = {"계정별": {}}
    for account_key, env_prefix in targets:
        try:
            c = _coupang_client(env_prefix)
            vid = getattr(c, "vendor_id", None) or getattr(c, "_cfg", {}).get("vendor_id")
            r = c.request("GET", path, query=f"vendorId={vid}")
            d = (r or {}).get("data") or {}
            out["계정별"][account_key] = {"등록수": d.get("registeredCount"),
                                       "상한": d.get("permittedCount")}
        except Exception as e:
            out["계정별"][account_key] = f"실패 {_err(e)}"
    return out


# ── ④ 스마트스토어 검색 필드 2차 ────────────────────────────────
def probe4_smartstore_search() -> dict:
    from lemouton.uploader.market_fetch import _smartstore_client
    got = _pick("smartstore")
    if not got:
        return {"skip": "스마트스토어 계정 없음"}
    account_key, env_prefix = got
    c = _smartstore_client(env_prefix)
    out: dict[str, Any] = {"account": account_key, "tried": {}}

    def call(extra: dict):
        return c.request("POST", "/external/v1/products/search",
                         body={"page": 1, "size": 1, **extra})

    try:
        out["baseline"] = call({}).get("totalElements")
    except Exception as e:
        return {"account": account_key, "fatal": _err(e)}

    cands = [
        {"searchKeywordType": "SELLER_CODE", "searchKeyword": KEYWORD},
        {"searchKeywordType": "CHANNEL_PRODUCT_NO", "searchKeyword": "1"},
        {"productStatusTypes": ["SALE"], "searchKeywordType": "PRODUCT_NAME",
         "searchKeyword": KEYWORD},
        {"searchKeywordType": "NAME", "searchKeyword": KEYWORD, "orderType": "NO"},
        {"productNos": [1]},
        {"channelProductNos": [1]},
        {"sellerManagementCode": KEYWORD, "searchKeywordType": "SELLER_CODE"},
        {"periodType": "PROD_REG_DAY", "fromDate": "2026-07-01", "toDate": "2026-07-23"},
    ]
    for cand in cands:
        label = "+".join(f"{k}={v}" if not isinstance(v, list) else k
                         for k, v in cand.items())[:70]
        try:
            tot = call(cand).get("totalElements")
            out["tried"][label] = {
                "hits": tot,
                "판정": "무시됨(전체와 동일)" if tot == out["baseline"] else "★ 먹힘",
            }
        except Exception as e:
            out["tried"][label] = f"거부 {_err(e)}"
    return out


def main() -> int:
    only = (os.environ.get("ONLY_PART") or "").strip()
    parts = [("① ESM query 래퍼가 정답인가", probe1_esm_query_wrapper),
             ("② 롯데온 목록이 상품명을 주는가", probe2_lotteon_row),
             ("③ 쿠팡 등록 상품수 한 번에", probe3_coupang_inflow),
             ("④ 스마트스토어 검색 필드 2차", probe4_smartstore_search)]
    for title, fn in parts:
        if only and only not in title:
            continue
        print("\n" + "=" * 70)
        print("■ " + title)
        print("=" * 70)
        try:
            print(json.dumps(fn(), ensure_ascii=False, indent=2))
        except Exception as e:      # noqa: BLE001
            print(f"실패: {_err(e)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
