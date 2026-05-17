"""SSF샵 execution proof — 라이브 1상품 크롤 (멀티 색상 자동 발견)."""
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

from lemouton.sourcing.crawlers.ssf import SsfCrawler

URL = sys.argv[1] if len(sys.argv) > 1 else "https://www.ssfshop.com/LEMOUTON/GRG12345/good"
print(f"[TEST] URL={URL}\n[TEST] 시작 (curl_cffi + multi-color GRG discovery)...\n")

try:
    r = SsfCrawler().fetch(URL)
    print(f"✅ 성공")
    print(f"   상품명: {r.product_name_raw[:60]}")
    print(f"   브랜드: {r.brand}")
    print(f"   discount_info: {r.discount_info}")
    print(f"   옵션 수: {len(r.options)}")
    if r.options:
        o = r.options[0]
        print(f"\n   [옵션 0]")
        print(f"      color={o.get('color_text')!r}  size={o.get('size_text')!r}")
        print(f"      sale_price={o.get('sale_price'):,}원")
        print(f"      auto_card_discount={o.get('auto_card_discount')}")
        if 'gift_point_amount' in o:
            print(f"      gift_point_amount={o.get('gift_point_amount'):,}원")
        if 'point_rate' in o:
            print(f"      point_rate={o.get('point_rate')} ({o.get('point_amount'):,}P)")
        print(f"      stock={o.get('stock')}")
    print(f"\n💡 매입가 = sale_price - 리뷰 500 - 기프트포인트(변동) - 포인트(변동%) - 네페 1% - 현대카드 2.73%")
except Exception as e:
    print(f"❌ 실패: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
