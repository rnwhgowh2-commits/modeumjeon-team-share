# -*- coding: utf-8 -*-
"""[DIAG] 스스(스마트스토어) inline __PRELOADED_STATE__ 에 per-SKU 재고가 있는지 확인.

목적: ss_lemouton 크롤러는 SKU별 재고를 못 받는다고 가정(상품 합계만). 정말 없는지,
optionCombinations 등 다른 경로에 SKU별 stockQuantity 가 있는지 실측한다.
"""
import json
import re
import sys

from curl_cffi import requests as cffi_requests

URL = "https://brand.naver.com/lemouton/products/5844147017"
PAT = re.compile(r"window\.__PRELOADED_STATE__\s*=\s*(.+?)</script>", re.DOTALL)
UNDEF = re.compile(r"(?<![\w\"])undefined(?![\w\"])")


def walk_find(obj, needle, path="", out=None, depth=0):
    """needle 이 키 이름에 포함된 모든 경로를 수집."""
    if out is None:
        out = []
    if depth > 8:
        return out
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{path}.{k}"
            if needle.lower() in str(k).lower():
                preview = v
                if isinstance(v, (list, dict)):
                    preview = f"<{type(v).__name__} len={len(v)}>"
                out.append((p, preview))
            walk_find(v, needle, p, out, depth + 1)
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:3]):
            walk_find(v, needle, f"{path}[{i}]", out, depth + 1)
    return out


def main():
    resp = cffi_requests.get(URL, impersonate="chrome120", timeout=30, allow_redirects=True)
    resp.raise_for_status()
    html = resp.text
    m = PAT.search(html)
    if not m:
        print("NO PRELOADED STATE")
        return
    raw = m.group(1).strip().rstrip(";")
    state = json.loads(UNDEF.sub("null", raw))
    simple = (state.get("simpleProductForDetailPage") or {}).get("A") or {}

    print("=== top-level simple A keys ===")
    print(sorted(simple.keys()))
    print()
    print("=== stockQuantity(상품합계) ===", simple.get("stockQuantity"))
    print("=== productStatusType ===", simple.get("productStatusType"))
    print()

    # SKU/조합/재고 관련 경로 전수 탐색
    for needle in ("optionCombination", "combination", "stockQuantity", "optionStandard", "soldOut", "soldout"):
        print(f"=== paths containing '{needle}' ===")
        found = walk_find(state, needle)
        for p, prev in found[:25]:
            print(f"  {p} = {prev}")
        print()

    # optionCombinations 가 있으면 첫 항목 샘플 통째로
    combos = None
    for key in ("optionCombinations", "optionCombinationGroups"):
        c = simple.get(key)
        if c:
            combos = c
            print(f"=== simple.{key} sample[0..2] ===")
            print(json.dumps(c[:3] if isinstance(c, list) else c, ensure_ascii=False, indent=1)[:2000])
            break
    if combos is None:
        # 깊은 곳에 있을 수 있음
        deep = walk_find(state, "optionCombination")
        print("=== optionCombination deep paths ===", [p for p, _ in deep][:10])


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
