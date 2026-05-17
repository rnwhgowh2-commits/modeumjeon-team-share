"""Phase B 시연 — yaml-driven v2 vs hardcoded 기존 크롤러 비교.

목적: docs/sources/musinsa/profile.yaml 만 보고 동일한 크롤 결과가 나오는지 검증.
범위: 비로그인 API 경로 (_fetch_via_api) 만. 회원가 Playwright 경로는 별도 세션.

사용: python docs/sources/musinsa/_demo_compare.py [PRODUCT_URL]
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

# Windows cp949 콘솔에서 UTF-8 / 이모지 출력 강제 (config.py 와 동일 패턴)
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import yaml
from curl_cffi import requests as cffi_requests

# ── 1) 경로 셋업 ── sys.path 에 _시스템/ 추가 + cwd 변경 (운영 import 가능)
ROOT = Path(__file__).resolve().parent.parent.parent.parent
SYSTEM = ROOT / "_시스템"
sys.path.insert(0, str(SYSTEM))
os.chdir(SYSTEM)

# ── 2) yaml 로드 ──
PROFILE_PATH = ROOT / "docs" / "sources" / "musinsa" / "profile.yaml"
profile = yaml.safe_load(PROFILE_PATH.read_text(encoding="utf-8"))


# ─────────────────────────────────────────────────────────────
# V2: yaml-driven 크롤러 (이 함수가 yaml 만 보고 동작)
# ─────────────────────────────────────────────────────────────
def _get_nested(obj, path):
    cur = obj
    for k in path.split("."):
        cur = cur.get(k) if isinstance(cur, dict) else None
        if cur is None:
            return None
    return cur


def v2_fetch_via_api(product_url: str, prof: dict) -> dict:
    """yaml 만 보고 비로그인 API 크롤. 하드코딩 0."""
    # product_id 추출
    pat = prof["urls"]["product_id_pattern"]
    m = re.search(pat, product_url)
    if not m:
        raise ValueError(f"product_id 추출 실패: {product_url}")
    pid = m.group(1)

    # HTTP 설정
    http = prof["http"]
    headers = dict(http["default_headers"])
    if http.get("referer_required"):
        headers["Referer"] = product_url

    api = prof["api"]
    base = api["base"]
    imp = http["impersonate"]
    to = http["timeout_sec"]

    # meta
    meta_ep = api["endpoints"]["meta"]
    meta_url = base + meta_ep["path"].format(product_id=pid)
    meta = cffi_requests.get(meta_url, impersonate=imp, headers=headers, timeout=to).json()
    f = meta_ep["response_fields"]
    name = _get_nested(meta, f["product_name"]) or ""
    brand = _get_nested(meta, f["brand"]) or ""
    sp = int(_get_nested(meta, f["sale_price"]) or 0)
    op = int(_get_nested(meta, f["original_price"]) or 0)
    if not op and sp:
        op = sp
    if not sp and op:
        sp = op

    # options
    opt_ep = api["endpoints"]["options"]
    opt_url = base + opt_ep["path"].format(product_id=pid)
    opts_raw = cffi_requests.get(opt_url, impersonate=imp, headers=headers, timeout=to).json()
    of = opt_ep["response_fields"]
    basic = _get_nested(opts_raw, of["basic_groups"]) or []
    items = _get_nested(opts_raw, of["option_items"]) or []

    # inventories
    inv_ep = api["endpoints"]["inventories"]
    all_nos = [int(v["no"]) for g in basic for v in (g.get("optionValues") or []) if v.get("no") is not None]
    inv_url = base + inv_ep["path"].format(product_id=pid)
    inv_headers = dict(headers, **{"Content-Type": "application/json"})
    inv_raw = cffi_requests.post(
        inv_url, json={"optionValueNos": all_nos},
        impersonate=imp, headers=inv_headers, timeout=to,
    ).json()
    inv_list = _get_nested(inv_raw, inv_ep["response_fields"]["items"]) or []
    inv_by_var = {int(x["productVariantId"]): x for x in inv_list if "productVariantId" in x}

    # 옵션 행 생성
    is_2 = len(basic) >= 2
    sep = prof["options"]["managed_code_separator"]
    stock_cfg = prof["options"]["stock"]
    out = []
    for it in items:
        vno = int(it.get("no") or 0)
        mc = it.get("managedCode") or ""
        if sep in mc:
            a, b = mc.split(sep, 1)
            a, b = a.strip(), b.strip()
        else:
            a, b = mc.strip(), ""
        if is_2:
            color, size = a, b
        else:
            parts = (name or "").rsplit(" ", 1)
            color = parts[-1] if len(parts) > 1 else ""
            size = a
        inv = inv_by_var.get(vno, {})
        if inv.get("outOfStock"):
            stock = stock_cfg["out_of_stock_default"]
        elif inv.get("remainQuantity") is None:
            stock = stock_cfg["no_remain_field_default"]
        else:
            r = inv["remainQuantity"]
            stock = int(r) if r >= 0 else 0
        out.append({
            "option_id": f"{pid}|{color}|{size}",
            "color_text": color, "size_text": size,
            "price": sp, "stock": stock,
        })
    if not out:
        out.append({
            "option_id": f"{pid}||",
            "color_text": "", "size_text": "",
            "price": sp, "stock": 999,
        })

    return {
        "source": "musinsa",
        "product_url": product_url,
        "product_name_raw": name,
        "brand": brand,
        "options": out,
    }


# ─────────────────────────────────────────────────────────────
# 기존 (hardcoded) 호출 — _fetch_via_api 직접 호출 (Playwright variant discovery 우회)
# ─────────────────────────────────────────────────────────────
def hardcoded_fetch_via_api(product_url: str) -> dict:
    from lemouton.sourcing.crawlers.musinsa import MusinsaCrawler
    c = MusinsaCrawler(prefer_member_price=False)
    r = c._fetch_via_api(product_url)
    return {
        "source": r.source,
        "product_url": r.product_url,
        "product_name_raw": r.product_name_raw,
        "brand": getattr(r, "brand", "") or "",
        "options": r.options,
    }


# ─────────────────────────────────────────────────────────────
# 비교
# ─────────────────────────────────────────────────────────────
def compare(url: str) -> int:
    print("=" * 60)
    print(f"[TEST URL] {url}")
    print("=" * 60)

    print("\n[1/2] 기존 (hardcoded) 크롤링 ...")
    try:
        r1 = hardcoded_fetch_via_api(url)
        print(f"   ✅ 상품명: {r1['product_name_raw'][:50]}")
        print(f"   ✅ 브랜드: {r1['brand']}  옵션: {len(r1['options'])}개")
    except Exception as e:
        print(f"   ❌ 실패: {type(e).__name__}: {e}")
        return 1

    print("\n[2/2] v2 (yaml-driven) 크롤링 ...")
    try:
        r2 = v2_fetch_via_api(url, profile)
        print(f"   ✅ 상품명: {r2['product_name_raw'][:50]}")
        print(f"   ✅ 브랜드: {r2['brand']}  옵션: {len(r2['options'])}개")
    except Exception as e:
        print(f"   ❌ 실패: {type(e).__name__}: {e}")
        return 1

    print("\n" + "=" * 60)
    print("[DIFF 비교]")
    print("=" * 60)
    a = json.dumps(r1, ensure_ascii=False, sort_keys=True, indent=2)
    b = json.dumps(r2, ensure_ascii=False, sort_keys=True, indent=2)
    if a == b:
        print("✅✅✅ 100% 일치 — yaml-driven v2 가 기존 크롤러와 동일하게 동작")
        print(f"   상품명·브랜드·옵션({len(r1['options'])}개) 모두 일치")
        return 0

    print("❌ 차이 발견 — 필드별 분석:")
    for key in ("source", "product_url", "product_name_raw", "brand"):
        if r1.get(key) != r2.get(key):
            print(f"  · {key}:")
            print(f"      기존: {r1.get(key)!r}")
            print(f"      v2  : {r2.get(key)!r}")
    if r1["options"] != r2["options"]:
        print(f"  · options 차이 (개수 기존={len(r1['options'])}, v2={len(r2['options'])})")
        n = min(len(r1["options"]), len(r2["options"]), 3)
        for i in range(n):
            if r1["options"][i] != r2["options"][i]:
                print(f"      [{i}] 기존: {r1['options'][i]}")
                print(f"      [{i}] v2  : {r2['options'][i]}")
    return 2


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "https://www.musinsa.com/products/4210142"
    sys.exit(compare(url))
