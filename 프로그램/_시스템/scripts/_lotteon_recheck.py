"""롯데온 (lotteon.com) 사용자 명세 검증 — 재크롤링 + dyn 키 dump.

산출물:
  - LotteCrawler.fetch(URL) 호출 결과 options[0] 의 모든 키 dump
  - save_crawl_result 통해 DB 갱신 (sp_id=12)
  - compute_breakdown 단계별 호출 결과
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lemouton.sourcing.crawlers.lotteon import LotteCrawler
from lemouton.sources.service import save_crawl_result
from lemouton.sources.models import SourceProduct
# FK 해결 위해 옵션 모델도 등록
from lemouton.sourcing.models import Option  # noqa: F401
from lemouton.sourcing.models_pricing import OptionSourceUrl  # noqa: F401
from shared.db import SessionLocal


URL = "https://www.lotteon.com/p/product/LO2158462914"


def main():
    crawler = LotteCrawler()
    print(f"=== Fetching {URL} ===")
    result = crawler.fetch(URL)

    print(f"\n--- CrawlResult ---")
    print(f"source: {result.source}")
    print(f"product_name_raw: {result.product_name_raw}")
    print(f"discount_info: {result.discount_info}")
    print(f"options count: {len(result.options)}")

    if not result.options:
        print("NO OPTIONS — fail")
        return 1

    opt0 = result.options[0]
    print(f"\n--- options[0] keys ---")
    for k in sorted(opt0.keys()):
        v = opt0[k]
        if isinstance(v, list) and v:
            print(f"  {k}: list len={len(v)}, first={v[0] if v else '-'}")
        elif isinstance(v, dict):
            print(f"  {k}: dict {list(v.keys())[:5]}")
        else:
            print(f"  {k}: {v!r}")

    print(f"\n--- 동적 혜택 신규 키 ---")
    for k in ('lotte_member_discount_rate', 'lotte_member_discount_label',
              'store_jjim_coupon_amount', 'store_jjim_coupon_label'):
        print(f"  {k}: {opt0.get(k)!r}")

    # DB 저장 — sp_id=12 매핑
    print(f"\n=== save_crawl_result (DB 갱신) ===")
    s = SessionLocal()
    try:
        sp = s.query(SourceProduct).filter_by(id=12).first()
        if not sp:
            print("sp_id=12 not found")
            return 1
        counts = save_crawl_result(s, source_product=sp, crawl_result=result)
        s.commit()
        print(f"counts: {counts}")

        # 갱신 후 dynamic_benefits_json 재확인
        s.refresh(sp)
        print(f"\n--- sp_id=12 갱신 후 ---")
        print(f"last_price: {sp.last_price}")
        print(f"dynamic_benefits_json: {sp.dynamic_benefits_json}")
        print(f"auto_card_discount_json: {sp.auto_card_discount_json}")
    finally:
        s.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
