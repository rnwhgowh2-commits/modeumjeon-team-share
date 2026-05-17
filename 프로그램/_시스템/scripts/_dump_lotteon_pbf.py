"""롯데ON pbf API 응답 dump — 자동/미적용 쿠폰 식별 키 도출용."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.sync_api import sync_playwright  # type: ignore

URLS = {
    "lemouton": "https://www.lotteon.com/p/product/LO2158462914?sitmNo=LO2158462914_2158462915&mall_no=1&dp_infw_cd=SCH%5E%5E%EB%A5%B4%EB%AC%B4%ED%86%B5&areaCode=SCH",
    "cortez":   "https://www.lotteon.com/p/product/PD52903977?mall_no=1&dp_infw_cd=SCH%5E%5E%EB%82%98%EC%9D%B4%ED%82%A4%20%EC%BD%94%EB%A5%B4%ED%85%8C%EC%A6%88&areaCode=SCH",
}

PATHS = {
    "/product/v2/detail/search/base/sitm/": "base",
    "/product/v2/detail/option/mapping/": "option",
    "/product/v2/extlmsa/promotion/favorBox/benefits": "favor",
    "/product/v2/extlmsa/promotion/qtyChangeFavorInfoList": "qty",
    "/product/v2/extlmsa/promotion/additionFavorInfoList": "addition",
}

OUT_DIR = Path(__file__).resolve().parent / "_lotteon_pbf_dump"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def fetch(url: str, label: str) -> dict:
    captured: dict[str, dict] = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1440, "height": 900},
        )
        page = ctx.new_page()

        def on_response(resp):
            u = resp.url
            for path, key in PATHS.items():
                if path in u:
                    try:
                        ct = (resp.headers.get("content-type") or "").lower()
                        if "json" not in ct:
                            return
                        body = resp.text()
                        obj = json.loads(body)
                        if isinstance(obj, dict):
                            captured.setdefault(key, []).append(obj)
                    except Exception as e:
                        print(f"  [{label}] parse fail {key}: {e}")
                    return

        page.on("response", on_response)
        try:
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
            except Exception as e:
                print(f"  [{label}] goto warn: {e}")
            # let XHRs fire
            page.wait_for_timeout(7000)
        finally:
            browser.close()
    return captured


for label, url in URLS.items():
    print(f"=== Fetching {label} ===")
    captured = fetch(url, label)
    for key, payloads in captured.items():
        # take last response (some are called multiple times)
        last = payloads[-1]
        out_path = OUT_DIR / f"{label}_{key}.json"
        out_path.write_text(json.dumps(last, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  saved {out_path.name} ({len(payloads)} captures)")
    if not captured:
        print(f"  NO API CAPTURED for {label}")
