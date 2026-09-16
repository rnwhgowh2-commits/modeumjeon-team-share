# -*- coding: utf-8 -*-
"""보이는 크롤 시연 — 한 모음전의 소싱처 URL을 진짜 브라우저(headful)로 띄워
각 옵션의 가격/재고를 긁는 현장을 눈으로 보여준다. (읽기 전용)

실행: python -m scripts.watch_crawl_demo
"""
from __future__ import annotations
import os
# ── 보이는 모드 강제 (브라우저 창 뜸) ──
os.environ["WATCH_CRAWL"] = "1"

import sys
# Windows 콘솔(cp949) 에서도 유니코드 출력 깨지지 않게 강제 UTF-8
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
from pathlib import Path
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config  # noqa: F401  (.env 로드)
from shared.db import SessionLocal
from lemouton.sourcing.models import Model


def pick_model():
    """소싱처 URL이 가장 많이 채워진 모음전 1개 선택."""
    s = SessionLocal()
    try:
        best = None
        best_n = 0
        for m in s.query(Model).all():
            n = sum(1 for src in ("lemouton", "musinsa", "ssf", "lotteon")
                    if getattr(m, f"url_{src}", None))
            if n > best_n:
                best, best_n = m, n
        if not best:
            return None, {}
        urls = {src: getattr(best, f"url_{src}", None)
                for src in ("lemouton", "musinsa", "ssf", "lotteon")
                if getattr(best, f"url_{src}", None)}
        return best.model_code, urls
    finally:
        s.close()


def make_crawler(source: str):
    if source == "lemouton":
        from lemouton.sourcing.crawlers.lemouton import LemoutonCrawler
        return LemoutonCrawler(prefer_playwright=True)
    if source == "musinsa":
        from lemouton.sourcing.crawlers.musinsa import MusinsaCrawler
        return MusinsaCrawler()
    if source == "ssf":
        from lemouton.sourcing.crawlers.ssf import SsfCrawler
        return SsfCrawler()
    if source == "lotteon":
        from lemouton.sourcing.crawlers.lotteon import LotteCrawler
        return LotteCrawler()
    return None


def main() -> int:
    code, urls = pick_model()
    print("=" * 70)
    print(f" 보이는 크롤 시연 — 모음전: {code}")
    print(f" 소싱처 {len(urls)}곳: {', '.join(urls.keys())}")
    print(" (브라우저 창이 떴다 닫혔다 하면서 가격/재고를 긁습니다)")
    print("=" * 70)
    if not urls:
        print("크롤할 URL이 있는 모음전이 없습니다.")
        return 1

    # 르무통(공개, 로그인 불필요) 먼저 → 가장 확실히 보임. 나머지는 로그인 필요할 수 있음.
    order = [s for s in ("lemouton", "musinsa", "ssf", "lotteon") if s in urls]
    for source in order:
        url = urls[source]
        print(f"\n[{source}] 크롤 시작 → {url[:75]}")
        crawler = make_crawler(source)
        if crawler is None:
            print(f"  (크롤러 없음 — 건너뜀)")
            continue
        try:
            result = crawler.fetch(url)
        except Exception as e:
            print(f"  ⚠️ {source} 크롤 실패: {type(e).__name__}: {e}")
            continue
        opts = getattr(result, "options", []) or []
        print(f"  ✅ '{getattr(result,'product_name_raw','?')}' — 옵션 {len(opts)}개")
        for o in opts[:30]:
            print(f"     · {o.get('color_text')}/{o.get('size_text')}  "
                  f"가격={o.get('price')}  재고={o.get('stock')}")
    print("\n" + "=" * 70)
    print(" 시연 종료.")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
