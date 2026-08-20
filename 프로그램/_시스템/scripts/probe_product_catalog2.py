# -*- coding: utf-8 -*-
"""상품관리 설계용 실측 2차 — 1차에서 남은 물음만 좁혀서 확인한다. 읽기 전용.

1차(probe_product_catalog.py) 결과로 확정된 것:
    · 스마트스토어 · 롯데온 → 상태별 총건수를 **즉답**한다(totalElements / dataCount).
    · 쿠팡 · 11번가 → 총건수 필드가 **없다**. 상태·상품명 필터는 먹는다.
    · ESM(옥션·G마켓) → totalItems 는 주는데 sellStatus·keyword 를 줘도 값이 **안 변한다**
      (전부 3260) = 필터가 조용히 무시되는 것으로 보인다. 여기서 확증한다.
    · 롯데온은 상품명 검색 파라미터 자체가 없다 → 가장 큰 마켓(14만)이 검색 불가.

이 스크립트가 답할 것:
    A. ESM 필터가 정말 무시되는가 (items 를 실제로 받아 내용으로 판별)
    B. 스마트스토어 상품명 검색의 진짜 요청 필드명은 무엇인가 (후보 대량 시도)
    C. 쿠팡·11번가 1계정을 실제로 페이징해 총건수와 소요를 잰다
"""
from __future__ import annotations

import json
import os
import time
from typing import Any

SEARCH_KEYWORD = "니트"


def _err(e: Exception) -> str:
    return f"{type(e).__name__}: {str(e)[:200]}"


def _pick(market: str) -> tuple[str, str] | None:
    """그 마켓의 활성 계정 1개(표본)."""
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


# ── A. ESM 필터 확증 ────────────────────────────────────────────
def probe_a_esm() -> dict:
    from lemouton.uploader.market_fetch import _esm_client
    from shared.platforms.esm.products import search_goods
    got = _pick("auction")
    if not got:
        return {"skip": "옥션 활성 계정 없음"}
    account_key, env_prefix = got
    c = _esm_client("auction", env_prefix)
    out: dict[str, Any] = {"account": account_key, "cases": {}}

    def snap(label: str, **kw):
        try:
            r = search_goods(client=c, market="auction", page_size=3, **kw)
            items = r.get("items") or []
            out["cases"][label] = {
                "totalItems": r.get("totalItems"),
                "first_names": [str(i.get("goodsName") or i.get("goodsNo"))[:40]
                                for i in items[:3]],
            }
        except Exception as e:
            out["cases"][label] = f"실패 {_err(e)}"

    snap("필터없음")
    snap("판매중(11)", sell_status="11")
    snap("품절(31)", sell_status="31")
    snap("판매중지(21)", sell_status="21")
    snap(f"키워드({SEARCH_KEYWORD})", keyword=SEARCH_KEYWORD)
    snap("키워드(zzzz없는말)", keyword="zzzzqqq없는말")
    # 판정: totalItems 가 전부 같고 첫 상품도 같으면 = 필터 무시(조용한 실패)
    tots = {k: v.get("totalItems") for k, v in out["cases"].items() if isinstance(v, dict)}
    out["판정"] = ("필터 무시됨 — 전부 같은 값" if len(set(tots.values())) == 1
                 else "필터 먹음 — 값이 갈림")
    out["totals"] = tots
    return out


# ── B. 스마트스토어 상품명 검색 필드 찾기 ──────────────────────────
def probe_b_smartstore() -> dict:
    from lemouton.uploader.market_fetch import _smartstore_client
    got = _pick("smartstore")
    if not got:
        return {"skip": "스마트스토어 활성 계정 없음"}
    account_key, env_prefix = got
    c = _smartstore_client(env_prefix)
    out: dict[str, Any] = {"account": account_key, "baseline": None, "tried": {}}

    def call(extra: dict) -> Any:
        return c.request("POST", "/external/v1/products/search",
                         body={"page": 1, "size": 1, **extra})

    try:
        out["baseline"] = call({}).get("totalElements")
    except Exception as e:
        return {"account": account_key, "fatal": _err(e)}

    # 네이버 커머스 API 문서·유사 API 에서 쓰이는 이름 후보를 전부 던져 본다.
    candidates = [
        {"searchKeywordType": "PRODUCT_NAME", "searchKeyword": SEARCH_KEYWORD},
        {"searchKeywordType": "CHANNEL_PRODUCT_NAME", "searchKeyword": SEARCH_KEYWORD},
        {"searchKeywordType": "SELLER_CODE", "searchKeyword": SEARCH_KEYWORD},
        {"productName": SEARCH_KEYWORD, "searchKeywordType": "PRODUCT_NAME"},
        {"keyword": SEARCH_KEYWORD},
        {"name": SEARCH_KEYWORD},
        {"sellerManagementCode": SEARCH_KEYWORD},
        {"productNames": [SEARCH_KEYWORD]},
    ]
    for cand in candidates:
        label = "+".join(cand.keys())
        try:
            tot = call(cand).get("totalElements")
            out["tried"][label] = {
                "hits": tot,
                "판정": ("무시됨(전체와 동일)" if tot == out["baseline"] else "★ 먹힘"),
            }
        except Exception as e:
            out["tried"][label] = f"거부 {_err(e)}"
    return out


# ── C. 쿠팡·11번가 총건수 실제 페이징 ───────────────────────────
def probe_c_coupang() -> dict:
    from lemouton.uploader.market_fetch import _coupang_client
    got = _pick("coupang")
    if not got:
        return {"skip": "쿠팡 활성 계정 없음"}
    account_key, env_prefix = got
    c = _coupang_client(env_prefix)
    vendor_id = getattr(c, "vendor_id", None) or getattr(c, "_cfg", {}).get("vendor_id")
    path = "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products"
    out: dict[str, Any] = {"account": account_key, "per_page": 100}
    total, calls, token, t0 = 0, 0, None, time.time()
    try:
        while True:
            q = f"vendorId={vendor_id}&maxPerPage=100"
            if token:
                q += f"&nextToken={token}"
            r = c.request("GET", path, query=q)
            calls += 1
            data = r.get("data") or []
            total += len(data)
            token = r.get("nextToken")
            if not token or not data or calls >= 400:   # 400콜 = 4만건 안전 상한
                break
        out.update(counted=total, calls=calls, seconds=round(time.time() - t0, 1),
                   완주=bool(not token))
    except Exception as e:
        out.update(fatal=_err(e), counted=total, calls=calls)
    return out


def probe_c_eleven11() -> dict:
    from lemouton.uploader.market_fetch import _eleven11_client
    from shared.platforms.eleven11.products import search_products
    got = _pick("eleven11")
    if not got:
        return {"skip": "11번가 활성 계정 없음"}
    account_key, env_prefix = got
    c = _eleven11_client(env_prefix)
    out: dict[str, Any] = {"account": account_key, "per_page": 100}
    total, calls, start, t0 = 0, 0, 1, time.time()
    try:
        while True:
            rows = search_products(client=c, limit=100, start=start, end=start + 99)
            calls += 1
            total += len(rows)
            if len(rows) < 100 or calls >= 300:
                break
            start += 100
        out.update(counted=total, calls=calls, seconds=round(time.time() - t0, 1))
    except Exception as e:
        out.update(fatal=_err(e), counted=total, calls=calls)
    return out


# ── D. DB 여유 ────────────────────────────────────────────────
def probe_d_db() -> dict:
    import sqlalchemy as sa
    from shared.db import SessionLocal
    s = SessionLocal()
    out: dict[str, Any] = {}
    try:
        out["총용량"] = s.execute(sa.text(
            "select pg_size_pretty(pg_database_size(current_database()))")).scalar()
        out["상위테이블"] = [
            {"table": r[0], "size": r[1], "rows": r[2]}
            for r in s.execute(sa.text("""
                select c.relname, pg_size_pretty(pg_total_relation_size(c.oid)),
                       c.reltuples::bigint
                from pg_class c join pg_namespace n on n.oid = c.relnamespace
                where n.nspname = 'public' and c.relkind = 'r'
                order by pg_total_relation_size(c.oid) desc limit 12"""))]
    except Exception as e:
        out["fatal"] = _err(e)
    finally:
        s.close()
    return out


def main() -> int:
    only = (os.environ.get("ONLY_PART") or "").strip().upper()
    parts = [("A. ESM 필터가 정말 무시되나", probe_a_esm),
             ("B. 스마트스토어 상품명 검색 필드", probe_b_smartstore),
             ("C1. 쿠팡 총건수 실제 페이징", probe_c_coupang),
             ("C2. 11번가 총건수 실제 페이징", probe_c_eleven11),
             ("D. DB 여유", probe_d_db)]
    for title, fn in parts:
        if only and not title.startswith(only):
            continue
        print("\n" + "=" * 70)
        print("■ " + title)
        print("=" * 70)
        try:
            print(json.dumps(fn(), ensure_ascii=False, indent=2))
        except Exception as e:      # noqa: BLE001 — 한 항목 실패가 전체를 멈추면 안 된다
            print(f"실패: {_err(e)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
