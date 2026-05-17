"""롯데ON execution proof — Vue SPA + pbf API 캡처 라이브 1상품 크롤."""
from __future__ import annotations
import os, sys
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

from lemouton.sourcing.crawlers.lotteon import LotteCrawler

URL = sys.argv[1] if len(sys.argv) > 1 else "https://www.lotteon.com/p/product/{sitmNo}"
print(f"[TEST] URL={URL}\n[TEST] 시작 (Playwright + pbf.lotteon.com API 캡처 — 30~60초)...\n")

try:
    r = LotteCrawler().fetch(URL)
    print(f"✅ 성공")
    print(f"   상품명: {r.product_name_raw[:60]}")
    print(f"   discount_info: {r.discount_info}")
    print(f"   옵션 수: {len(r.options)}")
    if r.options:
        o = r.options[0]
        print(f"\n   [옵션 0]")
        print(f"      color={o.get('color_text')!r}  size={o.get('size_text')!r}")
        print(f"      sale_price={o.get('sale_price'):,}원")
        print(f"      stock={o.get('stock')}")
        # 카드즉시할인/장바구니쿠폰 추출됐는지
        if 'card_immediate_discount' in o:
            print(f"      card_immediate_discount={o.get('card_immediate_discount')}")
        if 'cart_coupons' in o:
            print(f"      cart_coupons={o.get('cart_coupons')}")
    print(f"\n💡 매입가 = sale_price - 카드즉시할인/장바구니쿠폰 (조건 충족 시만)")
except Exception as e:
    print(f"❌ 실패: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
