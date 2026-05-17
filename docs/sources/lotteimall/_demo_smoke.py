"""롯데홈쇼핑 execution proof — lottehomeshopping/lotteimall SSR HTML 크롤."""
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

URL = sys.argv[1] if len(sys.argv) > 1 else "https://www.lotteimall.com/goods/viewGoodsDetail.lotte?goods_no=1234567890"
print(f"[TEST] URL={URL}\n[TEST] 시작 (SSR HTML + dataBenefit JSON)...\n")

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
        print(f"      sale_price (= base_for_policy)={o.get('sale_price'):,}원")
        print(f"      auto_card_discount={o.get('auto_card_discount')}")
        print(f"      point_rewards={o.get('point_rewards')}")
        print(f"      stock={o.get('stock')}")
    print(f"\n💡 매입가 = max_price (카드 청구할인 이미 반영) - L.POINT (일반 또는 L.CLUB)")
except Exception as e:
    print(f"❌ 실패: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
