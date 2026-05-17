"""SSG Playwright 영구 프로필 우회 — curl_cffi 429 차단 시 대안.

사용자의 _ssg_pw_fetch2.py 패턴 활용:
  - data/profiles/ssg_ditodalal_pw 영구 프로필 (실 Chrome)
  - webdriver=undefined 우회
  - 스크롤 lazy load 트리거
  - page.content() raw HTML → SsgCrawler 내부 파싱 함수 재활용

⚠️ 운영 코드 ssg.py 는 안 건드림. 본 모듈은 docs 안 wrapper 만.
"""
from __future__ import annotations
import os, sys, io
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

SYSTEM = Path(r"C:\Users\seung\OneDrive\바탕 화면\모음전 관리 프로그램\프로그램\_시스템")
sys.path.insert(0, str(SYSTEM))
os.chdir(SYSTEM)

from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

# SsgCrawler 내부 함수들 재활용 (운영 로직 1:1)
from lemouton.sourcing.crawlers.ssg import (
    _extract_item_id,
    _extract_product_name,
    _extract_brand,
    _parse_card_benefit,
    _parse_ssg_money,
    _parse_product_coupon,
    _parse_uitem_options,
)
from lemouton.sourcing.crawlers.base import CrawlResult


USER_DATA_DIR = os.path.abspath('data/profiles/ssg_ditodalal_pw')


def fetch_via_playwright(product_url: str, headless: bool = False) -> CrawlResult:
    """Playwright 영구 프로필로 SSG 우회 fetch."""
    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(
            user_data_dir=USER_DATA_DIR,
            headless=headless,
            args=['--disable-blink-features=AutomationControlled'],
            viewport={'width': 1280, 'height': 900},
            locale='ko-KR',
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        )
        context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', { get: () => undefined })"
        )
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(product_url, wait_until='domcontentloaded', timeout=45000)
            page.wait_for_timeout(3000)
            # 스크롤 lazy load (할인내역/SSG MONEY 영역 노출)
            page.evaluate("""
                (async () => {
                    const total = document.body.scrollHeight;
                    let cur = 0;
                    while (cur < total) {
                        window.scrollTo(0, cur);
                        await new Promise(r => setTimeout(r, 300));
                        cur += 500;
                    }
                    window.scrollTo(0, 0);
                })();
            """)
            page.wait_for_timeout(3000)
            html = page.content()
        finally:
            context.close()

    # SsgCrawler 내부 파싱 1:1 재활용 (운영 코드와 동일 결과)
    soup = BeautifulSoup(html, "lxml")
    item_id = _extract_item_id(product_url, html)
    product_name = _extract_product_name(html, soup)
    brand = _extract_brand(html, soup)
    card_price, card_condition = _parse_card_benefit(soup)
    ssg_money = _parse_ssg_money(soup, html)
    product_coupon = _parse_product_coupon(soup)
    options = _parse_uitem_options(html, item_id)

    if not options:
        raise RuntimeError(f"[SSG-PW] 옵션 추출 실패 — itemId={item_id} html_len={len(html):,}")

    if card_price is not None:
        for opt in options:
            opt["card_benefit_price"] = card_price
            if card_condition:
                opt["card_benefit_condition"] = card_condition
    for opt in options:
        opt["ssg_money_rate"] = ssg_money["ssg_money_rate"]
        opt["ssg_money_amount"] = ssg_money["ssg_money_amount"]
        opt["ssg_money_already_applied"] = ssg_money["ssg_money_already_applied"]
        if ssg_money["ssg_money_text"]:
            opt["ssg_money_text"] = ssg_money["ssg_money_text"]
        for k, v in product_coupon.items():
            opt[k] = v

    return CrawlResult(
        source="ssg",
        product_url=product_url,
        product_name_raw=product_name,
        options=options,
        brand=brand,
    )


def smoke(url: str, label: str = ""):
    print(f"===== {label}\n     {url[:90]}")
    try:
        r = fetch_via_playwright(url, headless=True)
        print(f"  ✅ 성공  상품명={r.product_name_raw[:50]}")
        print(f"     브랜드={r.brand}  옵션 {len(r.options)}개")
        if r.options:
            o = r.options[0]
            print(f"     sale={o.get('sale_price'):,}원  stock={o.get('stock')}  color={o.get('color_text')[:20]!r}  size={o.get('size_text')!r}")
            ap = o.get('ssg_money_already_applied')
            print(f"     SSG MONEY: rate={o.get('ssg_money_rate')}% amount={o.get('ssg_money_amount')} already_applied={ap}")
            print(f"     SSG MONEY text: {(o.get('ssg_money_text') or '')[:80]!r}")
            if 'card_benefit_price' in o:
                print(f"     카드혜택가={o.get('card_benefit_price'):,}원  조건={o.get('card_benefit_condition')[:60] if o.get('card_benefit_condition') else None!r}")
            else:
                print(f"     카드혜택가: 미노출 (현대카드 2.73% fallback)")
            if 'product_coupon_rate' in o or 'product_coupon_amount' in o:
                print(f"     상품쿠폰: rate={o.get('product_coupon_rate')} amount={o.get('product_coupon_amount')} min_order={o.get('product_coupon_min_order')}")
    except Exception as e:
        print(f"  ❌ 실패: {type(e).__name__}: {e}")


if __name__ == "__main__":
    URLS = [
        ("[1] 나이키 리엑스 8", "https://www.ssg.com/item/itemView.ssg?itemId=1000809938058&siteNo=6009&salestrNo=1004"),
        ("[2] 밀레 카고팬츠 (패턴 A 즉시할인 이미 반영)", "https://www.ssg.com/item/itemView.ssg?itemId=1000807328520&siteNo=6009&salestrNo=1009"),
        ("[3] 나이키 카고팬츠", "https://www.ssg.com/item/itemView.ssg?itemId=1000644956258&siteNo=6009&salestrNo=1004"),
        ("[4] 닥스 벨트 (DB)", "https://www.ssg.com/item/itemView.ssg?itemId=1000631699134&siteNo=6009&salestrNo=1004"),
    ]
    for label, url in URLS:
        smoke(url, label)
        print()
