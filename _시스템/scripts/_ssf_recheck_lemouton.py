"""SSF LEMOUTON GRG424102517741 재크롤링 검증 스크립트.

- ssf.py 의 SsfCrawler.fetch() 직접 호출 (curl_cffi 기반, auth 불필요)
- sale_price 가 109,900 으로 갱신되는지, point_amount, gift_point_amount 등 모두 출력
- 추가: 첫 구매 쿠폰 / 카드사별 혜택 안내 등 spec 외 텍스트가 raw HTML 에 포함됐는지 확인
"""
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import json
from lemouton.sourcing.crawlers.ssf import SsfCrawler

URL = "https://www.ssfshop.com/LEMOUTON/GRG424102517741/good"

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
print("[OPTIONS — 처음 5개만]")
for opt in result.options[:5]:
    print(json.dumps(opt, ensure_ascii=False, indent=2))
print()

# 최저가 / 노출 항목 요약
prices = sorted(set(o.get('sale_price') for o in result.options if o.get('sale_price')))
print(f"sale_price values: {prices}")

# raw HTML 에서 첫 구매 쿠폰 / 카드 안내 / 멤버십포인트 P 추출
import re
from curl_cffi import requests as cffi_requests
html = cffi_requests.get(URL, impersonate="chrome120", timeout=30).text

# spec 외 잠재 keyword 추출
print()
print("[RAW HTML 검사 — spec 외 가능한 노출 항목]")
patterns = [
    ("첫 구매", r"첫\s*구매[^<]{0,30}"),
    ("처음이라면", r"처음이라면[^<]{0,30}"),
    ("쿠폰 20", r"쿠폰[^<]*20\s*%"),
    ("카드사별 혜택", r"카드사별\s*혜택[^<]{0,30}"),
    ("멤버십포인트 P", r"멤버십포인트\s*[\d,]+\s*P"),
    ("적립률 %", r"적립[^<]*\d+(?:\.\d+)?\s*%"),
    ("기프트포인트", r"기프트포인트[^<]{0,80}"),
    ("무료배송", r"무료\s*배송"),
]
for label, pat in patterns:
    ms = re.findall(pat, html, re.DOTALL)
    if ms:
        print(f"  [{label}] hits={len(ms)} examples={ms[:3]}")
    else:
        print(f"  [{label}] (none)")
