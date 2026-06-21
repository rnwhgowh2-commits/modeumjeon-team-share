# -*- coding: utf-8 -*-
"""롯데아이몰(롯데홈쇼핑) 소싱처 크롤링 가이드 초기 데이터 입력.

무신사 스크립트와 동일 패턴. 2026-06-09 라이브 실측(브라우저 롯데 로그인 →
'최대할인가' = 할인혜택 + 카드 청구할인 선반영값). SourceRegistry 등록명 '롯데홈쇼핑'.

실행:
  cd 프로그램/_시스템
  python scripts/populate_lotteimall_guide.py
"""
from __future__ import annotations
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from pathlib import Path
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config  # noqa: F401
from shared.db import SessionLocal
from lemouton.sourcing.models_pricing import SourceRegistry
from lemouton.sourcing import crawl_guide as cg

SOURCE_NAME = "롯데아이몰"  # = 롯데홈쇼핑 (lotteimall.com)

LOTTEIMALL_GUIDE = {
    "version": 3,
    "sample_urls": [
        {"url": "https://www.lotteimall.com/goods/viewGoodsDetail.lotte?goods_no=2559329941", "is_lead": True},  # 르무통 메이트
    ],
    "fields": {
        "thumbnail":     {"method": "crawl",            "locator": "상품 대표 이미지 img@src",                       "status": "ok",   "note": ""},
        "title":         {"method": "crawl",            "locator": "div.title · span.ir_name (없으면 div.name=브랜드)", "status": "ok",   "note": ""},
        "price":         {"method": "crawl",            "locator": "span.ir_price 부모 span.num(정가) · .price>span.num(판매가) · dataBenefit benefitPrc(최대할인가)", "status": "ok",   "note": ""},
        "benefit":       {"method": "crawl_per_product", "locator": "dataBenefit JSON(benefitPrc·cardDiscountList·lPointObj) · em.txt_em", "status": "warn", "note": "카드사·청구할인율 상품별 상이. lotteon.py(curl_cffi SSR)"},
        "option_stock":  {"method": "crawl",            "locator": "div.inp_option.inpOptList p.txt_option · li.soldout(품절)", "status": "ok",   "note": ""},
        "detail_image":  {"method": "crawl",            "locator": "상세 이미지 목록",                              "status": "ok",   "note": ""},
    },
    "pricing": {
        "base_label": "표면 노출가",
        "benefit_collection": "per_product",
        "benefits": [
            {"name": "할인 혜택",      "apply": "preapplied", "rule": "표면 노출가 → 베이스금액①(판매가) 시즌 할인 % 선반영",          "status": "conditional"},
            {"name": "카드 청구할인",  "apply": "deduct",     "rule": "베이스금액① × X%(국민카드 등 청구할인) → 최대혜택가",            "status": "conditional"},
            {"name": "구매·리뷰 적립", "apply": "accrue",     "rule": "베이스금액② 기준 적립(최대 633P/600원, 상품별)",                "status": "conditional"},
            {"name": "무이자 할부",    "apply": "payment",    "rule": "최대 10개월 무이자(하나·롯데 등)",                            "status": "optional"},
        ],
        "note": "최대혜택가 = 할인 혜택 + 카드 청구할인 선반영(롯데홈쇼핑 최대혜택가). % 는 베이스금액 기준(무신사 로직). 롯데멤버스 카드 결제 시 현금 지급 이벤트 별도.",
    },
    "verification": {
        "lead_cache": None,
        "last_new_check": None,
        "examples": [
            # 1. 르무통 메이트 메리노울 운동화 다크네이비
            {
                "url":          "https://www.lotteimall.com/goods/viewGoodsDetail.lotte?goods_no=2559329941",
                "name":         "르무통 메이트 운동화",
                "surface_price": 149000,
                "pre": [
                    {"label": "할인 혜택 15%", "amount": -22350},
                ],
                "base1":        126650,
                "deducts": [
                    {"label": "삼성카드 7% 청구할인", "amount": -8870},
                ],
                "base2":        117780,
                "pay":          None,
                "final_price":  117780,
                "note":         "최대할인가 117,780 = 판매가 126,650 − 삼성카드 7% 청구할인. 구매/리뷰 적립 최대 633P/600원 별도. (2026-06-11 재측정: 국민5%→삼성7%)",
                "captured_at":  "2026-06-11",
                "screenshot_url": None,
            },
        ],
    },
    "updated_at": None,
}


def main():
    s = SessionLocal()
    try:
        src = s.query(SourceRegistry).filter(SourceRegistry.name == SOURCE_NAME).first()
        if src is None:
            print(f"[오류] SourceRegistry 에 '{SOURCE_NAME}' 항목이 없습니다.")
            sys.exit(1)
        guide = cg.validate_guide(LOTTEIMALL_GUIDE)
        src.crawl_guide = cg.dumps(guide)
        s.commit()
        print(f"[완료] {SOURCE_NAME}(id={src.id}) crawl_guide 저장됨.")
        print(f"       sample_urls: {len(guide['sample_urls'])}개")
        print(f"       benefits:    {len(guide['pricing']['benefits'])}개")
        print(f"       examples:    {len(guide['verification']['examples'])}개")
    finally:
        s.close()


if __name__ == "__main__":
    main()
