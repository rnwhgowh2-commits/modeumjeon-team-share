# -*- coding: utf-8 -*-
"""롯데온(LOTTE ON) 소싱처 크롤링 가이드 초기 데이터 입력.

무신사 스크립트와 동일 패턴. 2026-06-09 라이브 실측(브라우저 롯데 로그인 상태 →
'나의 혜택가' = 카드/즉시할인 선반영값). 카드할인 사용조건·기간은 '자세히'에서
크롤 후 명기 필요(현재 note 처리). 캐시백 OK캐시백 1.1% 반영.

실행:
  cd 프로그램/_시스템
  python scripts/populate_lotteon_guide.py
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

SOURCE_NAME = "롯데온"

LOTTEON_GUIDE = {
    "version": 3,
    "sample_urls": [
        {"url": "https://www.lotteon.com/p/product/LE1217199730", "is_lead": True},   # 나이키 에어포스
        {"url": "https://www.lotteon.com/p/product/LO2158462914", "is_lead": False},  # 르무통 메이트
        {"url": "https://www.lotteon.com/p/product/PD59900747", "is_lead": False},    # 나이키 모자
    ],
    "fields": {
        "thumbnail":     {"method": "crawl",            "locator": "상품 대표 이미지 img@src",                       "status": "ok",   "note": ""},
        "title":         {"method": "crawl",            "locator": "API productNm (신) · div.title/span.ir_name (구)", "status": "ok",   "note": ""},
        "price":         {"method": "crawl",            "locator": "정상가 standardPrice · .final span.num(나의 혜택가)", "status": "ok",   "note": ""},
        "benefit":       {"method": "crawl_per_product", "locator": "favorBox/benefits API · dataBenefit cardDiscountList · em.txt_em '나의 혜택가'", "status": "warn", "note": "카드할인 '자세히'=특정금액 이상·기간 크롤 후 명기 필요. lotteon.py(Playwright+pbf API)"},
        "option_stock":  {"method": "crawl",            "locator": "div.inp_option.inpOptList[0/1] p.txt_option · li.soldout(품절)", "status": "ok",   "note": ""},
        "detail_image":  {"method": "crawl",            "locator": "상세 이미지 목록",                              "status": "ok",   "note": ""},
    },
    "pricing": {
        "base_label": "표면 노출가",
        "benefit_collection": "per_product",
        "benefits": [
            {"name": "스토어·롯데ON 즉시할인", "apply": "preapplied", "rule": "표면 노출가 → 베이스금액①(나의 혜택가) 선반영(스토어+롯데ON 즉시할인)", "status": "conditional"},
            {"name": "카드 즉시/청구할인",     "apply": "preapplied", "rule": "베이스금액①에 선반영(카드 최대 10%) · 자세히=특정 금액 이상·기간 확인", "status": "conditional"},
            {"name": "L.POINT 적립",          "apply": "accrue",     "rule": "베이스금액① 기준 적립(최대 1,000P + 송전결제 2%)",                "status": "conditional"},
            {"name": "OK캐시백",              "apply": "cashback",   "rule": "베이스금액② × 1.1%",                                            "status": "conditional"},
            {"name": "결제 적립",             "apply": "payment",    "rule": "택1 — L.PAY(제휴카드) / 네이버페이(현대카드)",                    "status": "conditional"},
        ],
        "note": "베이스금액①(나의 혜택가) = 즉시할인·카드할인 선반영(로그인값). % 는 베이스금액 기준(무신사 로직). 그 위에 OK캐시백 1.1% 차감.",
    },
    "verification": {
        "lead_cache": None,
        "last_new_check": None,
        "examples": [
            # 1. 나이키 에어포스 1 07 CW2288-111
            {
                "url":          "https://www.lotteon.com/p/product/LE1217199730",
                "name":         "나이키 에어포스 1 07",
                "surface_price": 149000,
                "pre": [
                    {"label": "카드할인 10%(롯데카드)", "amount": -14900},
                ],
                "base1":        134100,
                "deducts": [
                    {"label": "OK캐시백 1.1%", "amount": -1470},
                ],
                "base2":        132630,
                "pay":          None,
                "final_price":  132630,
                "note":         "나의 혜택가 134,100(롯데카드 결제=카드할인 10%). 카드할인 조건·기간은 '자세히' 크롤 필요.",
                "captured_at":  "2026-06-09",
                "screenshot_url": None,
            },
            # 2. 르무통 메이트 메리노울 운동화
            {
                "url":          "https://www.lotteon.com/p/product/LO2158462914",
                "name":         "르무통 메이트 운동화",
                "surface_price": 149000,
                "pre": [
                    {"label": "스토어+롯데ON 즉시할인", "amount": -29090},
                ],
                "base1":        119910,
                "deducts": [
                    {"label": "OK캐시백 1.1%", "amount": -1310},
                ],
                "base2":        118600,
                "pay":          None,
                "final_price":  118600,
                "note":         "나의 혜택가 119,910(스토어 즉시할인+롯데ON 즉시할인 선반영).",
                "captured_at":  "2026-06-09",
                "screenshot_url": None,
            },
            # 3. 나이키 드라이핏 ADV 클럽 스우시 캡 FB5636-010
            {
                "url":          "https://www.lotteon.com/p/product/PD59900747",
                "name":         "나이키 스우시 캡",
                "surface_price": 29250,
                "pre": [
                    {"label": "즉시할인 21%",            "amount": -6430},
                    {"label": "카드즉시할인(주문금액 부족)", "amount": -1000},
                ],
                "base1":        21820,
                "deducts": [
                    {"label": "OK캐시백 1.1%", "amount": -240},
                ],
                "base2":        21580,
                "pay":          None,
                "final_price":  21580,
                "note":         "나의 혜택가 21,820. 주문금액 부족으로 카드즉시할인 1,000원만 적용.",
                "captured_at":  "2026-06-09",
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
        guide = cg.validate_guide(LOTTEON_GUIDE)
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
