"""SSG execution proof — 인라인 JS uitemObj + SSG MONEY 4 패턴 라이브 검증."""
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

from lemouton.sourcing.crawlers.ssg import SsgCrawler

URL = sys.argv[1] if len(sys.argv) > 1 else "https://www.ssg.com/item/itemView.ssg?itemId=1000631699134&siteNo=6009&salestrNo=1004"
print(f"[TEST] URL={URL}\n[TEST] 시작 (curl_cffi + uitemObj 정규식)...\n")

try:
    r = SsgCrawler().fetch(URL)
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
        print(f"      stock={o.get('stock')}")
        # SSG MONEY 4 패턴 결과
        ap = o.get('ssg_money_already_applied')
        print(f"\n   [SSG MONEY]")
        print(f"      rate={o.get('ssg_money_rate')}%  amount={o.get('ssg_money_amount')}원")
        print(f"      already_applied={ap}  {'(★ 이중차감 방지)' if ap else '(별도 차감 가능)'}")
        print(f"      text={o.get('ssg_money_text')!r}")
        # 카드혜택가
        if 'card_benefit_price' in o:
            print(f"\n   [카드혜택가]")
            print(f"      price={o.get('card_benefit_price'):,}원")
            print(f"      condition={o.get('card_benefit_condition')}")
        else:
            print(f"\n   [카드혜택가] 미노출 → 현대카드 2.73% fallback (DB)")
        # 상품쿠폰
        if 'product_coupon_rate' in o:
            print(f"\n   [상품쿠폰]")
            print(f"      rate={o.get('product_coupon_rate')*100:g}%  min_order={o.get('product_coupon_min_order'):,}원")
            print(f"      label={o.get('product_coupon_label')}")
except Exception as e:
    print(f"❌ 실패: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
