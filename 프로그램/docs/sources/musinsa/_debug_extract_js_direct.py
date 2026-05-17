"""직접 _EXTRACT_JS 를 page.evaluate 로 호출 → 진짜 반환값 확인."""
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
from lemouton.sourcing.auth import new_context_with_state
from lemouton.sourcing.crawlers.musinsa_playwright import _EXTRACT_JS  # ★ 운영 JS 그대로

URL = "https://www.musinsa.com/products/4677240"

print(f"[INFO] URL={URL}")
print(f"[INFO] _EXTRACT_JS 길이: {len(_EXTRACT_JS):,}자")

with sync_playwright() as pw:
    browser, context = new_context_with_state(pw, "musinsa", "영빈", browser=None)
    try:
        page = context.new_page()
        page.goto(URL, timeout=30000, wait_until="domcontentloaded")
        page.wait_for_selector('[data-mds="DropdownTriggerBox"], [class*="CalculatedPrice"]', timeout=10000)
        raw = page.evaluate(_EXTRACT_JS, {"dropdownWait": 200, "stockCap": 10})
        page.close()
    finally:
        context.close()
        browser.close()

print("\n[_EXTRACT_JS 반환값]")
print(f"  name             = {raw.get('name')!r}")
print(f"  brand            = {raw.get('brand')!r}")
print(f"  originalPrice    = {raw.get('originalPrice'):,}원")
print(f"  salePrice        = {raw.get('salePrice'):,}원  ★★★")
print(f"  benefitPriceFromUI = {raw.get('benefitPriceFromUI'):,}원")
print(f"  options 개수      = {len(raw.get('options') or [])}")
print(f"  expandResult     = {raw.get('expandResult')}")
print(f"\n[breakdown 핵심]")
bd = raw.get('breakdown') or {}
for k in ['coupon', 'coupon_skipped_regular', 'coupon_skipped_amount', 'coupon_skip_reason',
          'cart_coupons', 'grade_discount', 'grade_discount_rate',
          'wrap_found', 'text_length', 'has_my_discount_section',
          'my_discount_price', 'login_marker_present', 'is_no_benefit_product']:
    if k in bd:
        v = bd[k]
        print(f"  {k} = {v!r}")
