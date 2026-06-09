# -*- coding: utf-8 -*-
"""SSF(삼성물산 SSF SHOP) 소싱처 크롤링 가이드 초기 데이터 입력.

무신사 스크립트와 동일 패턴(populate_musinsa_guide.py). 2026-06-09 라이브 실측.
표면가·기프트포인트·멤버십포인트는 페이지 실측값. 결제 적립(토스페이 5%)은
SSF 결제 택1 로직 가정값(영수증 note 명기).

실행:
  cd 프로그램/_시스템
  python scripts/populate_ssf_guide.py
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

SOURCE_NAME = "SSF"

SSF_GUIDE = {
    "version": 3,
    "sample_urls": [
        {"url": "https://www.ssfshop.com/BEANPOLE-LADIES/GM0026021164119/good", "is_lead": True},   # 빈폴
        {"url": "https://www.ssfshop.com/LEMOUTON/GRG426021974780/good", "is_lead": False},          # 르무통 메이트
        {"url": "https://www.ssfshop.com/BAO-BAO-ISSEY-MIYAKE/GM0026032737731/good", "is_lead": False},  # 바오바오백
    ],
    "fields": {
        "thumbnail":     {"method": "crawl",            "locator": ".product-img img@src",                          "status": "ok",   "note": ""},
        "title":         {"method": "crawl",            "locator": "div.gods-name(상품명) · h2.brand-name(브랜드)",    "status": "ok",   "note": ""},
        "price":         {"method": "crawl",            "locator": "del(정가) · em.price(판매가)",                    "status": "ok",   "note": ""},
        "benefit":       {"method": "crawl_per_product", "locator": "정규식 기프트포인트 ([\\d,]+)원 · 멤버십포인트 ([\\d,]+)P", "status": "warn", "note": "멤버십 한정값 — 비로그인 '최대'표기. ssf.py 크롤러"},
        "option_stock":  {"method": "crawl",            "locator": "#optionDiv1 li a[optcd] · a@statcd=SLDOUT(품절)",  "status": "ok",   "note": ""},
        "detail_image":  {"method": "crawl",            "locator": ".goods_detail img",                             "status": "ok",   "note": ""},
    },
    "pricing": {
        "base_label": "표면 노출가",
        "benefit_collection": "per_product",
        "benefits": [
            {"name": "시즌·쇼핑위크 할인", "apply": "preapplied", "rule": "표면 노출가 → 베이스금액①(판매가) 자동 반영(시즌 %, 상품별)",      "status": "conditional"},
            {"name": "첫 구매 쿠폰",       "apply": "preapplied", "rule": "신규 한정 20% 쿠폰(택) → 베이스금액① 반영",                     "status": "optional"},
            {"name": "기프트포인트",       "apply": "deduct",     "rule": "베이스금액① × 10%(멤버십 한정 즉시할인, 상품별 유무)",            "status": "conditional"},
            {"name": "멤버십포인트 적립",  "apply": "accrue",     "rule": "베이스금액① × 적립%(0.5~5%, 상품별)",                          "status": "conditional"},
            {"name": "결제 적립",          "apply": "payment",    "rule": "베이스금액② × 5%(토스페이) · 택1(페이코/네이버페이)",            "status": "conditional"},
        ],
        "note": "기프트포인트=즉시할인 / 멤버십포인트=적립. 둘 다 매입가 차감. % 는 베이스금액 기준(무신사 로직). 결제는 택1.",
    },
    "verification": {
        "lead_cache": None,
        "last_new_check": None,
        "examples": [
            # 1. 빈폴 — 허니콤 칼라넥 풀오버 네이비
            {
                "url":          "https://www.ssfshop.com/BEANPOLE-LADIES/GM0026021164119/good",
                "name":         "빈폴 허니콤 칼라넥 풀오버",
                "surface_price": 199000,
                "pre": [
                    {"label": "시즌 할인 10%", "amount": -19900},
                ],
                "base1":        179100,
                "deducts": [
                    {"label": "기프트포인트 10%(즉시할인)", "amount": -17900},
                    {"label": "멤버십포인트 5% 적립",       "amount": -8955},
                ],
                "base2":        152245,
                "pay":          {"label": "토스페이 5%", "amount": -7610},
                "final_price":  144635,
                "note":         "기프트포인트 10% + 포인트 5%. 결제=토스페이 5% 가정(택1).",
                "captured_at":  "2026-06-09",
                "screenshot_url": None,
            },
            # 2. 르무통 메이트 — 메리노울 운동화 아이보리
            {
                "url":          "https://www.ssfshop.com/LEMOUTON/GRG426021974780/good",
                "name":         "르무통 메이트 운동화",
                "surface_price": 149000,
                "pre": [
                    {"label": "시즌 할인 20%", "amount": -29100},
                ],
                "base1":        119900,
                "deducts": [
                    {"label": "멤버십포인트 0.5% 적립", "amount": -599},
                ],
                "base2":        119301,
                "pay":          {"label": "토스페이 5%", "amount": -5960},
                "final_price":  113341,
                "note":         "포인트 0.5%만(기프트포인트 없음). 결제=토스페이 5% 가정(택1).",
                "captured_at":  "2026-06-09",
                "screenshot_url": None,
            },
            # 3. 바오바오백 — Prism Frost White Beige
            {
                "url":          "https://www.ssfshop.com/BAO-BAO-ISSEY-MIYAKE/GM0026032737731/good",
                "name":         "바오바오백 Prism Frost",
                "surface_price": 595000,
                "pre":          [],
                "base1":        595000,
                "deducts": [
                    {"label": "기프트포인트 10%(즉시할인)", "amount": -59500},
                    {"label": "멤버십포인트 2% 적립",       "amount": -11900},
                ],
                "base2":        523600,
                "pay":          {"label": "토스페이 5%", "amount": -26180},
                "final_price":  497420,
                "note":         "할인 없는 정상가. 기프트포인트 10% + 포인트 2%. 결제=토스페이 5% 가정(택1).",
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
        guide = cg.validate_guide(SSF_GUIDE)
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
