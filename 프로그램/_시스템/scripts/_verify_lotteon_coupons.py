"""롯데ON 크롤러 재호출 검증 — 자동 적용 vs 미적용 쿠폰 분리."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lemouton.sourcing.crawlers.lotteon import LotteCrawler  # type: ignore

URLS = {
    "lemouton (URL #1)": "https://www.lotteon.com/p/product/LO2158462914?sitmNo=LO2158462914_2158462915&mall_no=1&dp_infw_cd=SCH%5E%5E%EB%A5%B4%EB%AC%B4%ED%86%B5&areaCode=SCH",
    "cortez (URL #2)":   "https://www.lotteon.com/p/product/PD52903977?mall_no=1&dp_infw_cd=SCH%5E%5E%EB%82%98%EC%9D%B4%ED%82%A4%20%EC%BD%94%EB%A5%B4%ED%85%8C%EC%A6%88&areaCode=SCH",
}

crawler = LotteCrawler(timeout=45)

for label, url in URLS.items():
    print("=" * 90)
    print(f"=== {label}")
    print(f"=== {url}")
    print("=" * 90)
    try:
        result = crawler.fetch(url)
    except Exception as e:
        print(f"FAIL: {e}")
        continue

    print(f"\n[product_name] {result.product_name_raw}")
    if result.options:
        opt = result.options[0]
        print(f"[sale_price ]  {opt.get('sale_price'):,}원")
        print(f"[max_price  ]  {opt.get('price'):,}원")
        print(f"[options    ]  {len(result.options)}개")

    print(f"\n[discount_info]\n  {result.discount_info}\n")

    coupons = (result.options[0].get("lotteon_coupons") or []) if result.options else []
    print(f"[lotteon_coupons] ({len(coupons)} items)")
    auto_sum = 0
    for i, c in enumerate(coupons, 1):
        print(f"  ── #{i} ────────────────────────────────────")
        print(f"     group         : {c.get('group')} / title={c.get('group_title')!r}")
        print(f"     name          : {c.get('name')}")
        print(f"     kind / type   : {c.get('kind')} / {c.get('type')}")
        print(f"     dc_tier       : {c.get('dc_tier')} (rate={c.get('dc_rate')}%, amount={c.get('dc_amount'):,}원)")
        print(f"     text          : {c.get('text')}")
        print(f"     applied       : {c.get('applied')}  (apply_yn={c.get('apply_yn')}, best_apply_yn={c.get('best_apply_yn')}, check={c.get('check_state')!r})")
        if c.get("unmet_reason"):
            print(f"     unmet_reason  : {c.get('unmet_reason')}")
        if c.get("condition_detail"):
            print(f"     condition_detail: {c.get('condition_detail')}")
        if c.get("is_card_coupon"):
            print(f"     is_card_coupon: True")
        if c.get("applied"):
            auto_sum += int(c.get("dc_amount") or 0)

    if result.options:
        opt = result.options[0]
        sp = int(opt.get("sale_price") or 0)
        # 정가는 first coupon 의 group 0 first dc 의 base 계산이 필요 — 간이 추론
        # qty.totSlPrc 가 정가. 여기선 lotteon_coupons 에는 정가가 없으므로 ratio 추산
    print(f"\n[verify] auto_applied 합계 = {auto_sum:,}원")
    print()
