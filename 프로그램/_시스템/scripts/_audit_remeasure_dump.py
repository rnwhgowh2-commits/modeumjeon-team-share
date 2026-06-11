# -*- coding: utf-8 -*-
"""무신사·롯데온·SSG 가이드 예제 라이브 회원가 전수 크롤 덤프 (재측정용).

각 예제 URL 을 로그인 크롤러로 긁어 option[0] 의 회원가/혜택 구조를 JSON 으로
출력한다. 결과를 보고 영수증(표면→base1→deducts→base2→pay→final)을 재구성한다.

실행: cd 프로그램/_시스템 && python scripts/_audit_remeasure_dump.py
"""
from __future__ import annotations
import sys, io, json, traceback
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from pathlib import Path
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config  # noqa: F401

from lemouton.sourcing.crawlers.lotteon import LotteCrawler
from lemouton.sourcing.crawlers.ssg import SsgCrawler
try:
    from lemouton.sourcing.crawlers.musinsa_playwright import MusinsaPlaywrightCrawler
    _MUSINSA = MusinsaPlaywrightCrawler()
except Exception:
    from lemouton.sourcing.crawlers.musinsa import MusinsaCrawler
    _MUSINSA = MusinsaCrawler()

JOBS = [
    ("무신사", _MUSINSA, [
        ("르무통", "https://www.musinsa.com/products/4046672"),
        ("빈폴",   "https://www.musinsa.com/products/6538205"),
        ("마스마룰즈", "https://www.musinsa.com/products/4128817"),
        ("탑텐",   "https://www.musinsa.com/products/4941819"),
    ]),
    ("롯데온", LotteCrawler(), [
        ("에어포스", "https://www.lotteon.com/p/product/LE1217199730"),
        ("르무통",   "https://www.lotteon.com/p/product/LO2158462914"),
        ("스우시캡", "https://www.lotteon.com/p/product/PD59900747"),
    ]),
    ("SSG", SsgCrawler(), [
        ("에어포스", "https://www.ssg.com/item/itemView.ssg?itemId=1000799167650&siteNo=6009&salestrNo=1010"),
        ("르무통",   "https://www.ssg.com/item/itemView.ssg?itemId=1000607152603&siteNo=6004&salestrNo=6005"),
        ("된장",     "https://www.ssg.com/item/itemView.ssg?itemId=1000617901959&siteNo=6001&salestrNo=6005&ckwhere=ssg_naver"),
    ]),
]


def main():
    for src_name, crawler, items in JOBS:
        print("\n" + "#" * 76)
        print(f"# {src_name}  ({crawler.__class__.__name__})")
        print("#" * 76)
        for label, url in items:
            print(f"\n----- [{src_name}/{label}] {url}")
            try:
                r = crawler.fetch(url)
                opts = r.options or []
                print(f"  options={len(opts)} discount_info={getattr(r,'discount_info',None)}")
                if opts:
                    o0 = opts[0]
                    print(json.dumps(o0, ensure_ascii=False, indent=2, default=str))
            except Exception as e:
                print(f"  FAIL {repr(e)[:160]}")
                traceback.print_exc()


if __name__ == "__main__":
    main()
