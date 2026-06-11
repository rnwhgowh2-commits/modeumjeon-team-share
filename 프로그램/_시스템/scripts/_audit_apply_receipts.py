# -*- coding: utf-8 -*-
"""무신사·롯데온·SSG 가이드 예제 영수증을 2026-06-11 라이브 실측값으로 갱신.

screenshot_url 은 보존(앞서 재생성한 R2 URL). 영수증 숫자만 patch.
old→new 최종가를 출력해 검증.
"""
from __future__ import annotations
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from pathlib import Path
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
import config  # noqa
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from lemouton.sourcing.models_pricing import SourceRegistry
from lemouton.sourcing import crawl_guide as cg

# 5432(세션 풀러 15한도) 우회 → 6543(트랜잭션 풀러) 단독 엔진 (일회성 쓰기)
from shared.db import engine as _base_engine
_url = str(_base_engine.url.render_as_string(hide_password=False)).replace(":5432/", ":6543/")
_engine = create_engine(_url, pool_size=1, max_overflow=0,
                        connect_args={"prepare_threshold": None})
SessionLocal = sessionmaker(bind=_engine)

D = "2026-06-11"

# (url -> 새 영수증 dict). screenshot_url/name/url 은 건드리지 않음.
NEW = {
 "무신사": {
   "https://www.musinsa.com/products/4046672": dict(
     surface_price=126900, pre=[], base1=126900,
     deducts=[{"label":"구매적립 3%","amount":-3807}], base2=123093,
     pay={"label":"무신사머니 3.5%","amount":-4308}, final_price=118785,
     note="라이브 회원가 실측(2026-06-11, 등급3%). 매입가=무신사 혜택가(적립금 사용 제외).", captured_at=D),
   "https://www.musinsa.com/products/6538205": dict(
     surface_price=173900, pre=[{"label":"등급할인 3%","amount":-5100}], base1=168800,
     deducts=[{"label":"구매적립","amount":-820}], base2=167980,
     pay={"label":"무신사머니 3.5%","amount":-5200}, final_price=162780,
     note="라이브 회원가 실측(2026-06-11, 등급3%). 매입가=무신사 혜택가(적립금 사용 제외).", captured_at=D),
   "https://www.musinsa.com/products/4128817": dict(
     surface_price=50520, pre=[{"label":"등급할인 3%","amount":-1480}], base1=49040,
     deducts=[{"label":"구매적립","amount":-240}], base2=48800,
     pay={"label":"무신사머니 3.5%","amount":-1510}, final_price=47290,
     note="라이브 회원가 실측(2026-06-11, 등급3%). 매입가=무신사 혜택가(적립금 사용 제외).", captured_at=D),
   "https://www.musinsa.com/products/4941819": dict(
     surface_price=39900, pre=[], base1=39900, deducts=[], base2=39900,
     pay=None, final_price=39900,
     note="라이브 실측(2026-06-11): 시즌 할인가 39,900, 페이지 추가 혜택 없음. 결제 현대카드 fallback은 매트릭스 별도.", captured_at=D),
 },
 "롯데온": {
   "https://www.lotteon.com/p/product/LE1217199730": dict(
     surface_price=149000, pre=[{"label":"카드할인 10%(롯데카드)","amount":-14900}], base1=134100,
     deducts=[{"label":"L.POINT 적립(최대 1,000P)","amount":-1000}], base2=133100,
     pay=None, final_price=133100,
     note="라이브 실측(2026-06-11): 나의 혜택가 134,100(롯데카드 결제). L.POINT 최대 1,000P + 충전결제 2% 적립 별도.", captured_at=D),
   "https://www.lotteon.com/p/product/LO2158462914": dict(
     surface_price=149000, pre=[{"label":"스토어+롯데ON 즉시할인","amount":-29090}], base1=119910,
     deducts=[{"label":"롯데오너스 1% 할인","amount":-1199},{"label":"L.POINT 적립(59P)","amount":-59}], base2=118652,
     pay=None, final_price=118652,
     note="라이브 실측(2026-06-11): 나의 혜택가 119,910. 롯데오너스 1% 할인+0.5% 적립 + L.POINT 59P + 충전결제 2% 별도.", captured_at=D),
   "https://www.lotteon.com/p/product/PD59900747": dict(
     surface_price=29250, pre=[{"label":"즉시할인 21%","amount":-6430},{"label":"카드즉시할인","amount":-1000}], base1=21820,
     deducts=[{"label":"L.POINT 적립(최대 1,000P)","amount":-1000}], base2=20820,
     pay=None, final_price=20820,
     note="라이브 실측(2026-06-11): 나의 혜택가 21,820(카카오페이 머니 결제). L.POINT 최대 1,000P + 충전결제 2% 별도.", captured_at=D),
 },
 "SSG": {
   "https://www.ssg.com/item/itemView.ssg?itemId=1000799167650&siteNo=6009&salestrNo=1010": dict(
     surface_price=119200, pre=[], base1=119200,
     deducts=[{"label":"카드혜택가(SSG PAY 7만원↑)","amount":-8344}], base2=110856,
     pay=None, final_price=110856,
     note="라이브 실측(2026-06-11): 최적가 119,200(상품가 하락) → 카드혜택가 110,856(SSG PAY). 상품쿠폰 12%(3만↑·최대2만)·SSG MONEY 충전 1.5% 조건부 별도.", captured_at=D),
   "https://www.ssg.com/item/itemView.ssg?itemId=1000607152603&siteNo=6004&salestrNo=6005": dict(
     surface_price=119900, pre=[], base1=119900,
     deducts=[{"label":"SSG MONEY 5% 적립","amount":-5995}], base2=113905,
     pay=None, final_price=113905,
     note="라이브 실측(2026-06-11): 최적가 119,900. SSG MONEY 5% 적립. (OK캐시백=외부적립, 페이지 미노출이라 제외)", captured_at=D),
   "https://www.ssg.com/item/itemView.ssg?itemId=1000617901959&siteNo=6001&salestrNo=6005&ckwhere=ssg_naver": dict(
     surface_price=172900, pre=[], base1=172900,
     deducts=[{"label":"카드혜택가(SSG PAY 7만원↑)","amount":-12103}], base2=160797,
     pay=None, final_price=160797,
     note="라이브 실측(2026-06-11): 최적가 172,900 → 카드혜택가 160,797(SSG PAY). 상품쿠폰 12%(1만↑)·SSG MONEY 충전 1.5% 별도.", captured_at=D),
 },
}

def main():
    s = SessionLocal()
    try:
        for name, urlmap in NEW.items():
            src = s.query(SourceRegistry).filter(SourceRegistry.name == name).first()
            g = cg.loads(src.crawl_guide)
            exs = (g.get("verification") or {}).get("examples") or []
            n = 0
            for ex in exs:
                patch = urlmap.get(ex.get("url"))
                if not patch:
                    continue
                old_final = ex.get("final_price")
                shot = ex.get("screenshot_url")
                ex.update(patch)
                ex["screenshot_url"] = shot  # 보존
                print(f"  [{name}] {ex['name']:20s} final {old_final} -> {ex['final_price']}  shot={'Y' if shot else '-'}")
                n += 1
            if n:
                src.crawl_guide = cg.dumps(cg.validate_guide(g))
                s.commit()
                print(f"=> {name}: {n}건 저장\n")
    finally:
        s.close()
    print("[완료] 무신사·롯데온·SSG 영수증 라이브 실측 반영")

if __name__ == "__main__":
    main()
