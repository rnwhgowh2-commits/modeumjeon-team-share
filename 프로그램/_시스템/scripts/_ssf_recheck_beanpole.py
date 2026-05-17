"""SSF BEANPOLE GM0026031110607 재크롤링 + 첫 구매 쿠폰 검출 스크립트.

- ssf.py 의 SsfCrawler.fetch() 직접 호출
- raw HTML 에서 "첫 구매 / 처음이라면 / 20% 쿠폰 / 카드사별 혜택" 등 spec 외 항목을 정규식으로 enumerate
- 옵션 dict 가 첫 구매 쿠폰 (first_purchase_coupon_rate) 을 포함하는지 확인
"""
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import json
from lemouton.sourcing.crawlers.ssf import SsfCrawler

URL = "https://www.ssfshop.com/BEANPOLE-KIDS/GM0026031110607/good"

print("=" * 70)
print(f"[CRAWL] {URL}")
print("=" * 70)

crawler = SsfCrawler()
result = crawler.fetch(URL)

print(f"product_name_raw: {result.product_name_raw}")
print(f"brand:           {result.brand}")
print(f"discount_info:   {result.discount_info}")
print(f"options count:   {len(result.options)}")
print()
print("[OPTIONS — 처음 3개만]")
for opt in result.options[:3]:
    print(json.dumps(opt, ensure_ascii=False, indent=2))
print()

prices = sorted(set(o.get('sale_price') for o in result.options if o.get('sale_price')))
print(f"sale_price values: {prices}")

# raw HTML 검사
import re
from curl_cffi import requests as cffi_requests
html = cffi_requests.get(URL, impersonate="chrome120", timeout=30).text

print()
print("[RAW HTML 검사 — 잠재 노출 항목]")
patterns = [
    ("첫 구매", r"첫\s*구매[^<]{0,80}"),
    ("처음이라면", r"처음이라면[^<]{0,80}"),
    ("쿠폰 20", r"쿠폰[^<]*20\s*%"),
    ("20% 쿠폰", r"20\s*%\s*쿠폰"),
    ("카드사별 혜택", r"카드사별\s*혜택[^<]{0,80}"),
    ("멤버십포인트 P", r"멤버십포인트\s*[\d,]+\s*P"),
    ("기프트포인트", r"기프트포인트[^<]{0,150}"),
    ("first_purchase keyword", r"first[_\s]?purchase"),
    ("쿠폰", r"쿠폰[^<]{0,60}"),
    ("바로가기", r"바로가기"),
    ("무료배송", r"무료\s*배송"),
]
for label, pat in patterns:
    ms = re.findall(pat, html, re.DOTALL | re.IGNORECASE)
    if ms:
        print(f"  [{label}] hits={len(ms)} examples={ms[:5]}")
    else:
        print(f"  [{label}] (none)")

# 첫 구매 쿠폰 영역 컨텍스트 dump (있으면)
print()
print("[첫 구매 컨텍스트 ±200자 — 있으면]")
for kw in ("첫 구매", "처음이라면"):
    idx = html.find(kw)
    if idx >= 0:
        start = max(0, idx - 200)
        end = min(len(html), idx + 400)
        snippet = html[start:end]
        print(f"--- '{kw}' @ {idx} ---")
        print(snippet)
        print("-" * 40)
