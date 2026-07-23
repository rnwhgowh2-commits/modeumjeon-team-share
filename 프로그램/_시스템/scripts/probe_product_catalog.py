# -*- coding: utf-8 -*-
"""상품관리 설계용 실측 — 마켓별·계정별 「등록 상품 몇 건인가 · 상태로 나눠 셀 수 있나 ·
상품명으로 찾을 수 있나」를 실제 호출로 확인한다.

★ 읽기 전용이다. 등록·수정·삭제 API 는 단 한 줄도 부르지 않는다.

왜 필요한가:
    상품관리 대시보드는 「마켓 > 계정 > 상태별 건수」를 보여줘야 한다. 그런데 그 숫자를
    **매번 마켓에 물어볼지, 미리 세어 저장할지**는 마켓이 「상태로 걸러 총건수만」 주는지에
    달려 있다. 총건수를 안 주는 마켓은 전 페이지를 훑어야 하므로 설계가 달라진다.
    또 「검색해서 모음전 상품으로 담기」는 마켓이 **상품명 검색**을 지원해야 성립한다.
    문서만 보고 정할 수 없어(지도의 params 가 플레이스홀더인 사례가 여럿) 실호출로 굳힌다.

실행: 라이브 서버 컨테이너 안에서 (마켓 API 는 서버 단일 IP 허용이라 로컬에선 막힌다)
    docker exec <컨테이너> python scripts/probe_product_catalog.py
"""
from __future__ import annotations

import json
import sys
import traceback
from typing import Any, Optional

# 통일 상태 4종 ← 마켓별 코드. 지도·어댑터 주석에서 확보한 값.
STATUS_CODES: dict[str, dict[str, Any]] = {
    "smartstore": {"판매중": "SALE", "품절": "OUTOFSTOCK",
                   "판매중지": "SUSPENSION", "승인대기": "WAIT"},
    "coupang": {"판매중": "APPROVED", "품절": None,
                "판매중지": "PARTIAL_APPROVED", "승인대기": "SAVED"},
    "lotteon": {"판매중": "SALE", "품절": "SOUT",
                "판매중지": "STP", "승인대기": None},
    "eleven11": {"판매중": "103", "품절": "104",
                 "판매중지": "105", "승인대기": "101"},
    # ESM(옥션·G마켓): 11=판매중 / 31=SKU품절 / 21=판매중지 / 승인대기 코드는 미확보
    "auction": {"판매중": "11", "품절": "31", "판매중지": "21", "승인대기": None},
    "gmarket": {"판매중": "11", "품절": "31", "판매중지": "21", "승인대기": None},
}

SEARCH_KEYWORD = "니트"   # 흔한 한글 낱말 — 0건이어도 '검색이 되는가'는 판별된다


def _err(e: Exception) -> str:
    return f"{type(e).__name__}: {str(e)[:200]}"


# ──────────────────────────────────────────────────────────────
#  마켓별 프로브 — 각각 {total, by_status{}, name_search} 를 채운다.
#  값이 None 이면 "그 마켓은 그 기능을 안 준다"는 뜻(0 과 구별해야 한다).
# ──────────────────────────────────────────────────────────────

def probe_smartstore(env_prefix: str) -> dict:
    from lemouton.uploader.market_fetch import _smartstore_client
    c = _smartstore_client(env_prefix)
    out: dict[str, Any] = {"total": None, "by_status": {}, "name_search": None,
                           "raw_keys": None, "notes": []}

    def call(body: dict) -> dict:
        return c.request("POST", "/external/v1/products/search", body=body)

    try:
        r = call({"page": 1, "size": 1})
        out["raw_keys"] = sorted(r.keys()) if isinstance(r, dict) else str(type(r))
        # 총건수 키 이름이 문서에 안 박혀 있어 후보를 전부 훑는다.
        for k in ("totalElements", "totalCount", "total", "totalElement"):
            if isinstance(r, dict) and r.get(k) is not None:
                out["total"] = r[k]
                out["notes"].append(f"총건수 키={k}")
                break
    except Exception as e:
        out["notes"].append(f"기본 조회 실패 {_err(e)}")
        return out

    for label, code in STATUS_CODES["smartstore"].items():
        if code is None:
            out["by_status"][label] = None
            continue
        try:
            r = call({"page": 1, "size": 1, "productStatusTypes": [code]})
            out["by_status"][label] = r.get("totalElements") if isinstance(r, dict) else None
        except Exception as e:
            out["by_status"][label] = f"실패 {_err(e)}"

    # 상품명 검색 — 필드명 후보를 순서대로 시도해 '먹히는 조합'을 찾는다.
    for cand in ({"searchKeywordType": "NAME", "searchKeyword": SEARCH_KEYWORD},
                 {"productName": SEARCH_KEYWORD},
                 {"searchKeyword": SEARCH_KEYWORD}):
        try:
            r = call({"page": 1, "size": 1, **cand})
            tot = r.get("totalElements") if isinstance(r, dict) else None
            # 전체건수와 같으면 필터가 무시된 것 — 되는 게 아니다(조용한 실패 판별).
            if tot is not None and out["total"] is not None and tot == out["total"]:
                out["notes"].append(f"{list(cand)} → 전체와 동일({tot}) = 무시된 듯")
                continue
            out["name_search"] = {"body": cand, "hits": tot}
            break
        except Exception as e:
            out["notes"].append(f"{list(cand)} → {_err(e)}")
    return out


def probe_coupang(env_prefix: str) -> dict:
    from lemouton.uploader.market_fetch import _coupang_client
    c = _coupang_client(env_prefix)
    vendor_id = getattr(c, "vendor_id", None) or getattr(c, "_cfg", {}).get("vendor_id")
    path = "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products"
    out: dict[str, Any] = {"total": None, "by_status": {}, "name_search": None,
                           "raw_keys": None, "notes": [f"vendorId={vendor_id}"]}

    def call(extra: str = "") -> dict:
        return c.request("GET", path, query=f"vendorId={vendor_id}&maxPerPage=1{extra}")

    try:
        r = call()
        out["raw_keys"] = sorted(r.keys()) if isinstance(r, dict) else str(type(r))
        # 쿠팡은 nextToken 페이징 — 총건수를 안 줄 가능성이 크다. 있으면 잡고, 없으면 명시.
        for k in ("totalCount", "total"):
            if isinstance(r, dict) and r.get(k) is not None:
                out["total"] = r[k]
                break
        if out["total"] is None:
            out["notes"].append("총건수 필드 없음 — nextToken 으로 전 페이지를 훑어야 셀 수 있음")
    except Exception as e:
        out["notes"].append(f"기본 조회 실패 {_err(e)}")
        return out

    for label, code in STATUS_CODES["coupang"].items():
        if code is None:
            out["by_status"][label] = None
            continue
        try:
            r = call(f"&status={code}")
            d = r.get("data") if isinstance(r, dict) else None
            out["by_status"][label] = {"status_accepted": True,
                                       "returned": len(d) if isinstance(d, list) else None}
        except Exception as e:
            out["by_status"][label] = f"실패 {_err(e)}"

    try:
        from urllib.parse import quote
        r = call(f"&sellerProductName={quote(SEARCH_KEYWORD)}")
        d = r.get("data") if isinstance(r, dict) else None
        out["name_search"] = {"param": "sellerProductName",
                              "returned": len(d) if isinstance(d, list) else None}
    except Exception as e:
        out["notes"].append(f"상품명 검색 → {_err(e)}")
    return out


def probe_lotteon(env_prefix: str) -> dict:
    from lemouton.uploader.market_fetch import _lotteon_client
    from shared.platforms import LOTTEON
    from datetime import datetime, timedelta
    c = _lotteon_client(env_prefix)
    cfg = getattr(c, "_cfg", None) or LOTTEON
    now = datetime.now()
    out: dict[str, Any] = {"total": None, "by_status": {}, "name_search": None,
                           "raw_keys": None,
                           "notes": ["상품명 검색 파라미터가 API 에 없음(지도·어댑터 확인)"]}

    def call(status: Optional[str] = None, days: int = 365) -> dict:
        body = {
            "trGrpCd": cfg.get("tr_grp_cd", "SR"),
            "trNo": cfg.get("tr_no", ""),
            "regStrtDttm": (now - timedelta(days=days)).strftime("%Y%m%d%H%M%S"),
            "regEndDttm": now.strftime("%Y%m%d%H%M%S"),
            "pageNo": 1, "rowsPerPage": 1,   # ★ 둘 다 필수 — 빼면 returnCode 9000
        }
        if status:
            body["slStatCd"] = status
        return c.request(method="POST", path=cfg["paths"]["list"], body=body)

    try:
        r = call()
        out["raw_keys"] = sorted(r.keys()) if isinstance(r, dict) else str(type(r))
        out["total"] = r.get("dataCount")
        if str(r.get("returnCode")) not in ("0000", "SUCCESS"):
            out["notes"].append(f"returnCode={r.get('returnCode')} msg={r.get('message')}")
    except Exception as e:
        out["notes"].append(f"기본 조회 실패 {_err(e)}")
        return out

    for label, code in STATUS_CODES["lotteon"].items():
        if code is None:
            out["by_status"][label] = None
            continue
        try:
            r = call(status=code)
            out["by_status"][label] = r.get("dataCount")
        except Exception as e:
            out["by_status"][label] = f"실패 {_err(e)}"
    return out


def probe_esm(market: str, env_prefix: str) -> dict:
    from lemouton.uploader.market_fetch import _esm_client
    from shared.platforms.esm.products import search_goods
    c = _esm_client(market, env_prefix)
    out: dict[str, Any] = {"total": None, "by_status": {}, "name_search": None,
                           "raw_keys": None, "notes": []}
    try:
        r = search_goods(client=c, market=market, page_size=1)
        out["raw_keys"] = sorted(r.keys()) if isinstance(r, dict) else str(type(r))
        out["total"] = r.get("totalItems")
    except Exception as e:
        out["notes"].append(f"기본 조회 실패 {_err(e)}")
        return out

    for label, code in STATUS_CODES[market].items():
        if code is None:
            out["by_status"][label] = None
            continue
        try:
            r = search_goods(client=c, market=market, sell_status=code, page_size=1)
            out["by_status"][label] = r.get("totalItems")
        except Exception as e:
            out["by_status"][label] = f"실패 {_err(e)}"

    try:
        r = search_goods(client=c, market=market, keyword=SEARCH_KEYWORD, page_size=1)
        out["name_search"] = {"param": "keyword", "hits": r.get("totalItems")}
    except Exception as e:
        out["notes"].append(f"상품명 검색 → {_err(e)}")
    return out


def probe_eleven11(env_prefix: str) -> dict:
    from lemouton.uploader.market_fetch import _eleven11_client
    from shared.platforms.eleven11.products import search_products
    c = _eleven11_client(env_prefix)
    out: dict[str, Any] = {"total": None, "by_status": {}, "name_search": None,
                           "raw_keys": None,
                           "notes": ["응답이 상품 배열이라 '총건수' 필드가 있는지 확인 필요"]}
    try:
        rows = search_products(client=c, limit=1)
        out["total"] = f"(총건수 필드 없음 · limit=1 로 {len(rows)}건 반환)"
    except Exception as e:
        out["notes"].append(f"기본 조회 실패 {_err(e)}")
        return out

    for label, code in STATUS_CODES["eleven11"].items():
        if code is None:
            out["by_status"][label] = None
            continue
        try:
            rows = search_products(client=c, sale_status=code, limit=1)
            out["by_status"][label] = {"status_accepted": True, "returned": len(rows)}
        except Exception as e:
            out["by_status"][label] = f"실패 {_err(e)}"

    try:
        rows = search_products(client=c, name=SEARCH_KEYWORD, limit=5)
        out["name_search"] = {"param": "prdNm", "returned": len(rows)}
    except Exception as e:
        out["notes"].append(f"상품명 검색 → {_err(e)}")
    return out


PROBES = {
    "smartstore": probe_smartstore,
    "coupang": probe_coupang,
    "lotteon": probe_lotteon,
    "eleven11": probe_eleven11,
    "auction": lambda p: probe_esm("auction", p),
    "gmarket": lambda p: probe_esm("gmarket", p),
}


def main() -> int:
    from shared.db import SessionLocal
    from lemouton.sourcing.models_v2 import UploadAccount

    # 특정 마켓만 돌릴 때. `python -` 로 stdin 실행하면 argv 가 안 오므로 환경변수도 본다.
    import os
    only = (sys.argv[1] if len(sys.argv) > 1 else "") or os.environ.get("ONLY_MARKET", "")
    only = only.strip() or None

    s = SessionLocal()
    try:
        accounts = (s.query(UploadAccount)
                    .filter(UploadAccount.is_active.is_(True))
                    .order_by(UploadAccount.market, UploadAccount.account_key).all())
        targets = [(a.market, a.account_key, a.env_prefix) for a in accounts]
    finally:
        s.close()

    if only:
        targets = [t for t in targets if t[0] == only]

    print(f"■ 활성 판매처 계정 {len(targets)}개 — 읽기 전용 조회만 수행\n")
    results = []
    for market, account_key, env_prefix in targets:
        fn = PROBES.get(market)
        head = f"[{market}] {account_key} (env={env_prefix})"
        if fn is None:
            print(f"{head} → 프로브 미구현, 건너뜀")
            continue
        try:
            r = fn(env_prefix)
        except Exception as e:      # noqa: BLE001 — 한 계정 실패가 전체를 멈추면 안 된다
            r = {"fatal": _err(e), "trace": traceback.format_exc()[-600:]}
        r.update(market=market, account_key=account_key)
        results.append(r)
        print(f"{head}\n{json.dumps(r, ensure_ascii=False, indent=2)}\n")

    print("\n" + "=" * 70)
    print("■ 요약 — 마켓 | 계정 | 총건수 | 상태별 셀 수 있나 | 상품명 검색")
    print("=" * 70)
    for r in results:
        by = r.get("by_status") or {}
        ok_status = sum(1 for v in by.values() if isinstance(v, (int, dict)))
        print(f"{r.get('market'):11s} | {str(r.get('account_key'))[:22]:22s} | "
              f"{str(r.get('total'))[:26]:26s} | {ok_status}/4 | "
              f"{'가능' if r.get('name_search') else '불가'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
