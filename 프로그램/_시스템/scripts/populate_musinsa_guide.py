# -*- coding: utf-8 -*-
"""무신사 소싱처 크롤링 가이드 초기 데이터 입력.

무신사 SourceRegistry 의 crawl_guide 에 샘플 URL 4개 + 혜택 5개 +
verification.examples 4개를 기록합니다. 기존 데이터는 덮어씁니다.

실행:
  cd 프로그램/_시스템
  python scripts/populate_musinsa_guide.py
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

import config  # noqa: F401  — loads env vars / DB URL
from shared.db import SessionLocal
from lemouton.sourcing.models_pricing import SourceRegistry
from lemouton.sourcing import crawl_guide as cg

MUSINSA_GUIDE = {
    "version": 3,
    "sample_urls": [
        {"url": "https://www.musinsa.com/products/4046672", "is_lead": True},   # 르무통 메이트
        {"url": "https://www.musinsa.com/products/6538205", "is_lead": False},  # 빈폴
        {"url": "https://www.musinsa.com/products/4128817", "is_lead": False},  # 마스마룰즈
        {"url": "https://www.musinsa.com/products/4941819", "is_lead": False},  # 탑텐
    ],
    "fields": {
        "thumbnail":     {"method": "crawl",           "locator": ".product-img img@src",       "status": "ok",   "note": ""},
        "title":         {"method": "crawl",           "locator": "h1.product_title",           "status": "ok",   "note": ""},
        "price":         {"method": "crawl",           "locator": "옵션별 매트릭스 가격",          "status": "ok",   "note": ""},
        "benefit":       {"method": "crawl_per_product", "locator": "회원가·적립금(오독주의)",     "status": "warn", "note": ""},
        "option_stock":  {"method": "crawl",           "locator": "옵션 드롭다운 → 품절",        "status": "ok",   "note": ""},
        "detail_image":  {"method": "crawl",           "locator": ".detail_view img",           "status": "ok",   "note": ""},
    },
    "pricing": {
        "base_label": "표면 노출가",
        "benefit_collection": "per_product",
        "benefits": [
            {"name": "등급 할인",  "apply": "preapplied", "rule": "선반영 — 나의 할인가에 자동 포함",                           "status": "conditional"},
            {"name": "상품 쿠폰",  "apply": "preapplied", "rule": "회원·등급·정기 제외 / 브랜드·카테고리 적용",                  "status": "conditional"},
            {"name": "구매적립",   "apply": "accrue",     "rule": "베이스금액① × 적립%(선할인 끄고 구매적립)",                   "status": "conditional"},
            {"name": "후기 적립",  "apply": "accrue",     "rule": "500원 고정(텍스트 후기)",                                    "status": "always"},
            {"name": "결제 적립",  "apply": "payment",    "rule": "택1 — 무신사머니 3% vs 현대카드 2.73% 큰 쪽",               "status": "conditional"},
        ],
        "note": "",
    },
    "verification": {
        "lead_cache": None,
        "last_new_check": None,
        "examples": [
            # 1. 르무통 메이트 4046672
            {
                "url":          "https://www.musinsa.com/products/4046672",
                "name":         "르무통 메이트",
                "surface_price": 126900,
                "pre":          [],
                "base1":        126900,
                "deducts": [
                    {"label": "구매적립 2.5%",    "amount": -3170},
                    {"label": "후기 적립(고정)",   "amount": -500},
                ],
                "base2":        123230,
                "pay":          {"label": "무신사머니 3%", "amount": -3690},
                "final_price":  119540,
                "note":         "",
                "captured_at":  None,
                "screenshot_url": None,
            },
            # 2. 빈폴 6538205
            {
                "url":          "https://www.musinsa.com/products/6538205",
                "name":         "빈폴",
                "surface_price": 179000,
                "pre": [
                    {"label": "등급할인 2.5%", "amount": -4470},
                ],
                "base1":        174530,
                "deducts": [
                    {"label": "구매적립 2.5%",    "amount": -4360},
                    {"label": "후기 적립(고정)",   "amount": -500},
                ],
                "base2":        169670,
                "pay":          {"label": "무신사머니 3%", "amount": -5090},
                "final_price":  164580,
                "note":         "",
                "captured_at":  None,
                "screenshot_url": None,
            },
            # 3. 마스마룰즈 4128817
            {
                "url":          "https://www.musinsa.com/products/4128817",
                "name":         "마스마룰즈",
                "surface_price": 52000,
                "pre": [
                    {"label": "잡화 7% 쿠폰",   "amount": -3640},
                    {"label": "등급할인 2.5%",   "amount": -1200},
                ],
                "base1":        47160,
                "deducts": [
                    {"label": "구매적립 2.5%",    "amount": -1170},
                    {"label": "후기 적립(고정)",   "amount": -500},
                ],
                "base2":        45490,
                "pay":          {"label": "무신사머니 3%", "amount": -1360},
                "final_price":  44130,
                "note":         "",
                "captured_at":  None,
                "screenshot_url": None,
            },
            # 4. 탑텐 4941819
            {
                "url":          "https://www.musinsa.com/products/4941819",
                "name":         "탑텐",
                "surface_price": 39900,
                "pre":          [],
                "base1":        39900,
                "deducts": [
                    {"label": "후기 적립(고정)", "amount": -500},
                ],
                "base2":        39400,
                "pay":          {"label": "현대카드 2.73%", "amount": -1070},
                "final_price":  38330,
                "note":         "구매적립·선할인 모두 불가 → 결제는 현대카드",
                "captured_at":  None,
                "screenshot_url": None,
            },
        ],
    },
    "updated_at": None,
}


def main():
    s = SessionLocal()
    try:
        src = s.query(SourceRegistry).filter(SourceRegistry.name == "무신사").first()
        if src is None:
            print("[오류] SourceRegistry 에 '무신사' 항목이 없습니다.")
            print("  → /sourcing-guide/ 에서 소싱처를 먼저 등록하세요.")
            sys.exit(1)
        guide = cg.validate_guide(MUSINSA_GUIDE)
        src.crawl_guide = cg.dumps(guide)
        s.commit()
        print(f"[완료] 무신사(id={src.id}) crawl_guide 저장됨.")
        print(f"       sample_urls: {len(guide['sample_urls'])}개")
        print(f"       benefits:    {len(guide['pricing']['benefits'])}개")
        print(f"       examples:    {len(guide['verification']['examples'])}개")
    finally:
        s.close()


if __name__ == "__main__":
    main()
