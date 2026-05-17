"""musinsa 4677240 케이스 진단 — page DOM 의 가격 관련 모든 요소 덤프.

목적: sale_price 가 165,240 으로 잡히는 원인 찾기.
     사이트 표시: 정가 459,000 → 쿠폰적용가 220,320 → 나의 할인가 215,320
"""
from __future__ import annotations
import os, sys, json
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

SYSTEM = Path(r"C:\Users\seung\OneDrive\바탕 화면\모음전 관리 프로그램\프로그램\_시스템")
sys.path.insert(0, str(SYSTEM))
os.chdir(SYSTEM)

from playwright.sync_api import sync_playwright
from lemouton.sourcing.auth import has_state, new_context_with_state

URL = "https://www.musinsa.com/products/4677240"

# 덤프할 가격 후보 셀렉터들
DUMP_JS = r"""
async () => {
    // 페이지 lazy load 발동 (musinsa_playwright.py 패턴)
    document.querySelectorAll('[class*="Dimmed"], [class*="Modal"]').forEach(el => {
        try { el.remove(); } catch(_) {}
    });
    window.scrollTo(0, 800);
    await new Promise(r => setTimeout(r, 1500));
    window.scrollTo(0, 0);
    await new Promise(r => setTimeout(r, 1500));
    document.querySelectorAll('[class*="MaxBenefitPriceTitle__CollapseButton"]').forEach(el => {
        try { el.click(); } catch(_) {}
    });
    await new Promise(r => setTimeout(r, 800));
    // PointSummaryWrap 클릭 (적립 상세 펼침)
    for (let i = 0; i < 5; i++) {
        document.querySelectorAll('[class*="MaxBenefitPrice__PointSummaryWrap"]').forEach(el => {
            try { el.click(); } catch(_) {}
        });
        await new Promise(r => setTimeout(r, 500));
    }

    function dumpElem(selector) {
        const els = document.querySelectorAll(selector);
        const out = [];
        els.forEach((el, i) => {
            out.push({
                idx: i,
                cls: (el.className && el.className.baseVal !== undefined) ? el.className.baseVal : (el.className || ''),
                text: (el.innerText || '').slice(0, 300),
            });
        });
        return out;
    }

    // 가격 관련 후보 셀렉터들
    const targets = [
        '[class*="DiscountWrap"]',
        '[class*="CalculatedPrice"]',
        '[class*="CurrentPrice"]',
        '[class*="PriceTotal"]',
        '[class*="MaxBenefitPrice"]',
        '[class*="OriginalPrice"]',
        '[class*="SalePrice"]',
        '[class*="CouponApplied"]',
    ];
    const result = {};
    for (const sel of targets) {
        result[sel] = dumpElem(sel);
    }

    // body textContent 에서 215,320 / 220,320 / 165,240 / 459,000 위치 확인
    const body = document.body.textContent || '';
    const findNumberContext = (numStr) => {
        const idx = body.indexOf(numStr);
        if (idx < 0) return null;
        return body.slice(Math.max(0, idx - 80), idx + numStr.length + 80);
    };
    result._number_context = {
        "459,000": findNumberContext("459,000"),
        "220,320": findNumberContext("220,320"),
        "215,320": findNumberContext("215,320"),
        "165,240": findNumberContext("165,240"),
        "쿠폰적용가": findNumberContext("쿠폰적용가"),
        "나의 할인가": findNumberContext("나의 할인가"),
    };

    // body 전체 길이
    result._body_text_length = body.length;

    return result;
}
"""

print(f"[INFO] URL={URL}")
print(f"[INFO] account=영빈\n")

with sync_playwright() as pw:
    browser, context = new_context_with_state(pw, "musinsa", "영빈", browser=None)
    try:
        page = context.new_page()
        page.goto(URL, timeout=30000, wait_until="domcontentloaded")
        page.wait_for_selector('[class*="CalculatedPrice"], [class*="CurrentPrice"]', timeout=10000)
        raw = page.evaluate(DUMP_JS)
        page.close()
    finally:
        context.close()
        browser.close()

# 출력
print("=" * 70)
print("[1] 가격 관련 셀렉터 매칭 요소들 (각 최대 5개)")
print("=" * 70)
for sel, items in raw.items():
    if sel.startswith("_"):
        continue
    print(f"\n  {sel}: {len(items)}개 매칭")
    for it in items[:5]:
        print(f"    [{it['idx']}] cls={it['cls'][:80]}")
        print(f"          text={it['text'][:200]!r}")

print("\n" + "=" * 70)
print("[2] 핵심 숫자 주변 문맥 (body textContent 검색)")
print("=" * 70)
for num, ctx in raw["_number_context"].items():
    if ctx:
        print(f"\n  {num!r} 발견:")
        print(f"    ...{ctx}...")
    else:
        print(f"\n  {num!r}: ❌ body textContent 에 없음")

print(f"\n  body textContent 길이: {raw['_body_text_length']:,}")
