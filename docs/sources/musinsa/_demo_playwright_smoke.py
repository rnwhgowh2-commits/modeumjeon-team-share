"""Playwright 회원가 크롤러 — execution proof.

목적: musinsa_playwright.MusinsaPlaywrightCrawler 가 실제로 회원가를 추출하는지 확인.
세션: data/auth/musinsa_영빈.json
"""
from __future__ import annotations
import os, sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# 운영 path 셋업 (OneDrive 기존)
SYSTEM = Path(r"C:\Users\seung\OneDrive\바탕 화면\모음전 관리 프로그램\프로그램\_시스템")
sys.path.insert(0, str(SYSTEM))
os.chdir(SYSTEM)

from lemouton.sourcing.crawlers.musinsa_playwright import MusinsaPlaywrightCrawler

URL = sys.argv[1] if len(sys.argv) > 1 else "https://www.musinsa.com/products/4210142"
ACCOUNT = sys.argv[2] if len(sys.argv) > 2 else "영빈"

print(f"[TEST] URL={URL}")
print(f"[TEST] account={ACCOUNT}")
print(f"[TEST] 시작 (30~60초 소요)...\n")

c = MusinsaPlaywrightCrawler(account_name=ACCOUNT, headless=True)
try:
    r = c.fetch(URL)
    print(f"✅ 성공")
    print(f"   상품명: {r.product_name_raw[:60]}")
    print(f"   브랜드: {r.brand}")
    print(f"   discount_info: {r.discount_info}")
    print(f"   옵션 수: {len(r.options)}")
    if r.options:
        o = r.options[0]
        print(f"\n   [옵션 0]")
        print(f"      color={o.get('color_text')}  size={o.get('size_text')}")
        print(f"      original_price={o.get('original_price'):,}원")
        print(f"      sale_price={o.get('sale_price'):,}원")
        print(f"      benefit_price (회원가)={o.get('benefit_price'):,}원")
        print(f"      member_price={o.get('member_price')}  is_member_price={o.get('is_member_price')}")
        print(f"      login_marker_present={o.get('login_marker_present')}")
        bd = o.get('breakdown', {})
        if bd:
            print(f"\n   [가격 산식 디테일]")
            for k in ['grade_discount', 'coupon', 'grade_reward_amount', 'money_reward_amount',
                     'review_reward_fixed', 'purchase_extra_reward', 'base1_after_grade',
                     'base2_after_grade_rwd', 'base3_after_money', 'payment_source',
                     'is_no_benefit_product']:
                if k in bd:
                    print(f"      {k} = {bd[k]}")
except Exception as e:
    print(f"❌ 실패: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
