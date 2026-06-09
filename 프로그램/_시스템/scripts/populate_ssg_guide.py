# -*- coding: utf-8 -*-
"""SSG.COM 소싱처 크롤링 가이드 초기 데이터 입력.

무신사 스크립트와 동일 패턴. 2026-06-09 수집. SSG.COM 은 브라우저 자동화 차단(safety)
→ WebFetch(비로그인) 으로 표면가·카드혜택가·SSG MONEY·상품쿠폰만 수집.
상품쿠폰·쓱세일·제휴쿠폰(네이버 경유 8%)은 로그인/쿠폰다운 게이트 → note 처리,
영수증 final 은 게이트값 미반영분이라 '근사' 표기. 정확값은 ④ 신규 검증(로컬 크롤)로 갱신.

실행:
  cd 프로그램/_시스템
  python scripts/populate_ssg_guide.py
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

SOURCE_NAME = "SSG"

SSG_GUIDE = {
    "version": 3,
    "sample_urls": [
        {"url": "https://www.ssg.com/item/itemView.ssg?itemId=1000799167650&siteNo=6009&salestrNo=1010", "is_lead": True},   # 나이키 에어포스
        {"url": "https://www.ssg.com/item/itemView.ssg?itemId=1000607152603&siteNo=6004&salestrNo=6005", "is_lead": False},  # 르무통 메이트
        {"url": "https://www.ssg.com/item/itemView.ssg?itemId=1000617901959&siteNo=6001&salestrNo=6005&ckwhere=ssg_naver", "is_lead": False},  # 나이키 에어포스 된장(네이버 경유)
    ],
    "fields": {
        "thumbnail":     {"method": "crawl",            "locator": ".cdtl_thmb_imgw img@src",                       "status": "ok",   "note": ""},
        "title":         {"method": "crawl",            "locator": "span.cdtl_info_tit_txt · 정규식 itemNm",          "status": "ok",   "note": ""},
        "price":         {"method": "crawl",            "locator": "JS sellprc(판매가) · bestAmt(최적가)",            "status": "ok",   "note": ""},
        "benefit":       {"method": "crawl_per_product", "locator": "div.mndtl_card_price(카드혜택가) · dl.cdtl_cpn_wrap(상품쿠폰) · span.cdtl_benefit(SSG MONEY)", "status": "warn", "note": "상품쿠폰·쓱세일·제휴쿠폰=로그인/쿠폰다운 게이트. Chrome 차단→WebFetch 비로그인. ssg.py(쿠키 warming)"},
        "option_stock":  {"method": "crawl",            "locator": "JS uitemOptnNm1/2(색/사이즈) · usablInvQty(0=품절)", "status": "ok",   "note": ""},
        "detail_image":  {"method": "crawl",            "locator": "상세 이미지 목록",                              "status": "ok",   "note": ""},
    },
    "pricing": {
        "base_label": "표면 노출가",
        "benefit_collection": "per_product",
        "benefits": [
            {"name": "즉시할인(최적가)",  "apply": "preapplied", "rule": "표면 노출가 → 베이스금액①(최적가) 즉시할인 반영",                "status": "conditional"},
            {"name": "카드혜택가",        "apply": "preapplied", "rule": "베이스금액①에 SSG계열 카드(넥슨현대·SSG현카·SSG삼카·삼성ID) 혜택가 반영", "status": "conditional"},
            {"name": "상품쿠폰",          "apply": "deduct",     "rule": "베이스금액① × 12%(최대 2만)·쓱세일 — 쿠폰다운 필요",             "status": "conditional"},
            {"name": "제휴할인 쿠폰",     "apply": "deduct",     "rule": "베이스금액① × 8%(네이버 경유 ckwhere=ssg_naver)",               "status": "conditional"},
            {"name": "SSG MONEY 적립",   "apply": "accrue",     "rule": "베이스금액① × 적립%(상품별 5%~, SSG삼성카드 최대 10%)",           "status": "conditional"},
            {"name": "OK캐시백",          "apply": "cashback",   "rule": "베이스금액② × 2%",                                              "status": "conditional"},
            {"name": "결제 적립",         "apply": "payment",    "rule": "SSG PAY(넥슨현대 / SSG현카 / SSG삼카 / 삼성 ID)",                "status": "conditional"},
        ],
        "note": "% 는 베이스금액 기준(무신사 로직). 카드혜택가·상품쿠폰·제휴쿠폰은 로그인/쿠폰다운 게이트 → 영수증 final 은 게이트값 일부 미반영(근사). 정확값은 ④ 신규 검증으로 갱신.",
    },
    "verification": {
        "lead_cache": None,
        "last_new_check": None,
        "examples": [
            # 1. 우먼스 나이키 에어포스 1 07 DD8959-100
            {
                "url":          "https://www.ssg.com/item/itemView.ssg?itemId=1000799167650&siteNo=6009&salestrNo=1010",
                "name":         "나이키 에어포스 1 07 (우먼스)",
                "surface_price": 149000,
                "pre": [
                    {"label": "SSG삼성카드 카드혜택가", "amount": -14587},
                ],
                "base1":        134413,
                "deducts": [
                    {"label": "OK캐시백 2%", "amount": -2680},
                ],
                "base2":        131733,
                "pay":          None,
                "final_price":  131733,
                "note":         "근사: 상품쿠폰 12%·쓱세일(쿠폰다운/로그인) 미반영. 카드혜택가=SSG삼성카드 기준.",
                "captured_at":  "2026-06-09",
                "screenshot_url": None,
            },
            # 2. 르무통 메이트 메리노울 운동화
            {
                "url":          "https://www.ssg.com/item/itemView.ssg?itemId=1000607152603&siteNo=6004&salestrNo=6005",
                "name":         "르무통 메이트 운동화",
                "surface_price": 119900,
                "pre":          [],
                "base1":        119900,
                "deducts": [
                    {"label": "SSG MONEY 5% 적립", "amount": -5995},
                    {"label": "OK캐시백 2%",        "amount": -2390},
                ],
                "base2":        111515,
                "pay":          None,
                "final_price":  111515,
                "note":         "최적가 119,900. SSG MONEY 5% 적립 + OK캐시백 2%.",
                "captured_at":  "2026-06-09",
                "screenshot_url": None,
            },
            # 3. 나이키 에어포스 1 07 된장 (네이버 경유 제휴쿠폰 8%)
            {
                "url":          "https://www.ssg.com/item/itemView.ssg?itemId=1000617901959&siteNo=6001&salestrNo=6005&ckwhere=ssg_naver",
                "name":         "나이키 에어포스 된장 포스",
                "surface_price": 182000,
                "pre": [
                    {"label": "즉시할인(최적가)", "amount": -9100},
                ],
                "base1":        172900,
                "deducts": [
                    {"label": "제휴쿠폰 8%(네이버 경유)", "amount": -13830},
                    {"label": "OK캐시백 2%",            "amount": -3180},
                ],
                "base2":        155890,
                "pay":          None,
                "final_price":  155890,
                "note":         "근사: 제휴쿠폰 8%=네이버 경유(ckwhere=ssg_naver) 쿠폰다운 필요. 상품쿠폰 12%(최대 2만)는 택1.",
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
        guide = cg.validate_guide(SSG_GUIDE)
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
