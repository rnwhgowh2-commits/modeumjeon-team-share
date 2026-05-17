"""스스 르무통 execution proof — brand.naver.com 라이브 1상품 크롤."""
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

from lemouton.sourcing.crawlers.ss_lemouton import SsLemoutonCrawler

URL = sys.argv[1] if len(sys.argv) > 1 else "https://brand.naver.com/lemouton/products/9496367527"
print(f"[TEST] URL={URL}\n[TEST] 시작 (curl_cffi + brand.naver.com inline JSON)...\n")

try:
    r = SsLemoutonCrawler().fetch(URL)
    print(f"✅ 성공")
    print(f"   상품명: {r.product_name_raw[:60]}")
    print(f"   discount_info: {r.discount_info}")
    print(f"   옵션 수: {len(r.options)}")
    if r.options:
        o = r.options[0]
        print(f"\n   [옵션 0]")
        print(f"      color={o.get('color_text')!r}  size={o.get('size_text')!r}")
        print(f"      original_price={o.get('original_price'):,}원")
        print(f"      sale_price={o.get('sale_price'):,}원  (discountedSalePrice)")
        print(f"      review_point_max={o.get('review_point_max'):,}원")
        print(f"      stock={o.get('stock')}")
    print(f"\n💡 매입가 = sale_price - review_point_max(변동) - 네페 1% - 현대카드 2.73%")
except Exception as e:
    print(f"❌ 실패: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
