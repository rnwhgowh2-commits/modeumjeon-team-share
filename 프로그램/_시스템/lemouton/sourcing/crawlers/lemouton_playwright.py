"""르무통 공홈 (lemouton.co.kr / m.lemouton.co.kr) — Playwright 크롤러.

V7 (Chrome extension) 의 ``crawlLemoutonBundle`` 흐름을 Playwright sync API 로 1:1 포팅.

V7 원본 위치:
  ``크롤러_V7_쿠팡 반영/background/background.js``
    - ``crawlLemoutonBundle(url, productName)`` (925~1029 행)
       1. ``ul.ec-product-button li`` 전체 수집 → 색상 / 사이즈 분류 (``/mm$/i``)
       2. 색상 0 개 → 단품 파서 (``lemoutonParseProduct``) 폴백
       3. 색상 ≥1 개 → 색상 버튼 **하나씩 클릭 → 사이즈 목록 다시 읽기**
          (Cafe24 JS 가 색상 클릭 시점에 ``ec-product-soldout`` 클래스를 사이즈에
          동적으로 토글하므로, 색상 단위로 사이즈 품절을 정확하게 수집할 수 있음)

정적 HTML 크롤러 (``lemouton.py``) 와의 정확도 격차:
  - 정적 HTML: 모든 사이즈가 초기 ``ec-product-disabled`` 상태로 노출됨.
    ``ec-product-soldout`` 은 색상 클릭 시점에 JS 가 동적으로 적용 → ``requests.get``
    응답에는 색상별 사이즈 품절 정보가 들어있지 않다. 데카르트 곱이 모두 "재고 있음"으로
    잘못 보고됨.
  - Playwright: V7 와 동일하게 색상 클릭 → ``ec-product-soldout`` 토글 후 사이즈
    재읽기 → V7 동등 정확도.

본 모듈은 ``LemoutonCrawler`` 와 **인터페이스 호환** 이며, ``fetch(product_url)`` 시그니처는
동일. 따라서 ``lemouton.py`` 의 dispatcher 가 Playwright 가용 시 본 모듈을 우선 호출.
"""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlparse, parse_qs

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

from .base import AbstractCrawler, CrawlResult


# V7 원본 상수 (lemouton.py 와 동일)
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
DEFAULT_NAV_TIMEOUT_MS = 30000
COLOR_CLICK_WAIT_MS = 600  # V7: ``await sleep(600)`` after click

# V7: ``/mm$/i`` — innerText 끝이 mm 이면 사이즈
SIZE_PATTERN_JS = "/mm\\s*$/i"


def _to_int(text: str | None) -> int:
    if not text:
        return 0
    s = re.sub(r"[^0-9]", "", text)
    if not s:
        return 0
    try:
        return int(s)
    except ValueError:
        return 0


def _extract_product_no(product_url: str) -> str:
    """V7: ``new URLSearchParams(productUrl.split('?')[1]).get('product_no')``."""
    qs = parse_qs(urlparse(product_url).query)
    vals = qs.get("product_no", [])
    return vals[0] if vals else ""


class PlaywrightLemoutonCrawler(AbstractCrawler):
    """르무통 공홈 Playwright 크롤러.

    V7 ``crawlLemoutonBundle`` 절차를 sync_api 로 그대로 실행:
      1. 페이지 로드 → ``ul.ec-product-button`` 대기
      2. JS evaluate 로 색상 / 사이즈 버튼 분류
      3. 색상 0 → 단품 폴백 (정적 HTML 모듈 호출)
      4. 색상 ≥1 → 각 색상 click → wait → 사이즈 다시 읽기

    실패 시 (Playwright 부팅 실패 / timeout / 노드 누락 등) ``RuntimeError`` 전파.
    호출자는 ``LemoutonCrawler`` 정적 HTML fallback 으로 자동 전환.
    """

    source_name = "lemouton"

    def __init__(
        self,
        headless: bool = True,
        nav_timeout_ms: int = DEFAULT_NAV_TIMEOUT_MS,
        click_wait_ms: int = COLOR_CLICK_WAIT_MS,
        profile_dir: str | None = None,
    ):
        """
        Args:
            profile_dir: ★ Playwright user_data_dir (대표 크롤 계정 ProfileStore 경로).
                         지정 시 launch_persistent_context (회원가).
                         미지정 시 비회원가 일반 크롤.
        """
        self.headless = headless
        self.nav_timeout_ms = nav_timeout_ms
        self.click_wait_ms = click_wait_ms
        self.profile_dir = profile_dir

    def fetch(self, product_url: str) -> CrawlResult:
        # [2026-06-03] WATCH_CRAWL=1 (내 PC 보면서 크롤) 이면 headful(보이는 창)로 강제.
        import os as _os
        _hl = self.headless and _os.environ.get('WATCH_CRAWL') != '1'
        with sync_playwright() as pw:
            # ★ profile_dir 모드 — 영구 프로필 (로그인 유지)
            if self.profile_dir:
                from pathlib import Path
                if not Path(self.profile_dir).exists():
                    raise RuntimeError(f"프로필 디렉터리 없음: {self.profile_dir}")
                context = pw.chromium.launch_persistent_context(
                    user_data_dir=str(self.profile_dir),
                    headless=_hl,
                    user_agent=USER_AGENT,
                    args=["--disable-blink-features=AutomationControlled"],
                )
                try:
                    page = context.new_page()
                    try:
                        return self._crawl_with_page(page, product_url)
                    finally:
                        page.close()
                finally:
                    context.close()
                return  # unreachable

            # ── Legacy: 비로그인
            browser = pw.chromium.launch(headless=_hl)
            try:
                context = browser.new_context(user_agent=USER_AGENT)
                page = context.new_page()
                try:
                    return self._crawl_with_page(page, product_url)
                finally:
                    page.close()
                    context.close()
            finally:
                browser.close()

    def _crawl_with_page(self, page, product_url: str) -> CrawlResult:
        """주입받은 페이지로 V7 흐름 실행. 본 메서드는 page 라이프사이클을 관리하지 않음."""
        page.goto(product_url, wait_until="domcontentloaded", timeout=self.nav_timeout_ms)
        # V7 ``await sleep(1000)`` — JS 옵션 finder 초기화 시간 확보
        try:
            page.wait_for_selector("ul.ec-product-button li", timeout=self.nav_timeout_ms)
        except PWTimeout as e:
            raise RuntimeError(f"옵션 버튼 로드 타임아웃: {product_url}") from e
        # 가격은 별도 JS 로 늦게 채워질 수 있음 — 셀렉터 등장까지 짧게 대기 (실패해도 fallback)
        try:
            page.wait_for_selector("span.ProductPrice, strong.price-number", timeout=5000)
        except PWTimeout:
            pass
        # JS 의 각종 비동기 초기화 안정화
        page.wait_for_timeout(800)

        product_no = _extract_product_no(product_url)

        # V7: 상품명 / 가격 한번에 추출
        # 상품명 우선순위: og:title > document.title > 필터 통과한 h2 (모바일에서는 h2가 마케팅 섹션)
        # 가격 fallback 체인: V7 셀렉터 → span.ProductPrice → meta[product:sale_price:amount] → JS var
        meta = page.evaluate(
            """
            () => {
                let productName = '';
                const og = document.querySelector('meta[property="og:title"]');
                if (og) {
                    productName = (og.getAttribute('content') || '').trim();
                }
                if (!productName) {
                    const title = (document.title || '').trim();
                    productName = title.split(/[-|]/)[0].trim();
                }
                if (!productName) {
                    const excludedSubs = ['확대','Ambassador','Natural','Travel','리뷰',
                                           '상품상세','추가구성','WITH ITEM',
                                           'MerinoWool','Merino Wool','Performance','Fiber',
                                           'LeMouton','100%'];
                    const h2Els = [...document.querySelectorAll('h2')];
                    const nameEl = h2Els.find(el => {
                        const t = (el.innerText || '').trim();
                        return t && t.length > 2 && t.length < 100 &&
                               !excludedSubs.some(s => t.includes(s)) &&
                               !t.startsWith('[');
                    });
                    productName = nameEl ? nameEl.innerText.trim() : '';
                }

                // V7 셀렉터 (1순위): strong.price-number (할인가) / span.txt_price.ProductPrice or span.ProductPrice (정가)
                const saleEl = document.querySelector('strong.price-number');
                const origEl = document.querySelector('span.txt_price.ProductPrice, span.ProductPrice');
                const rateEl = document.querySelector('span.ec-sale-rate');

                let sale = saleEl ? saleEl.innerText.replace(/[^0-9]/g, '') : '';
                let orig = origEl ? origEl.innerText.replace(/[^0-9]/g, '') : '';

                // 폴백 1: meta tags
                if (!sale) {
                    const m = document.querySelector('meta[property="product:sale_price:amount"]');
                    if (m) sale = (m.getAttribute('content') || '').replace(/[^0-9]/g, '');
                }
                if (!orig) {
                    const m = document.querySelector('meta[property="product:price:amount"]');
                    if (m) orig = (m.getAttribute('content') || '').replace(/[^0-9]/g, '');
                }
                // 폴백 2: span.ProductPrice (정가 = 할인가 동일 경우)
                if (!sale && orig) sale = orig;
                if (!orig && sale) orig = sale;

                const rate = rateEl ? rateEl.innerText.replace(/[^0-9]/g, '') : '';
                return { productName, sale, orig, rate };
            }
            """
        )

        product_name = meta["productName"] or ""
        sale_price = _to_int(meta["sale"])
        origin_price = _to_int(meta["orig"]) or sale_price
        explicit_rate = _to_int(meta["rate"])
        if explicit_rate:
            discount_rate = explicit_rate
        elif origin_price > sale_price and sale_price > 0:
            discount_rate = round((1 - sale_price / origin_price) * 100)
        else:
            discount_rate = 0

        # ★ 2026-05-14 — 매입가 단일 진실 원천(api_benefits.compute_breakdown) 으로 통합.
        #   크롤러는 sale_price 만 제공. 매입가는 매트릭스 UI 가 breakdown API 로 별도 호출.
        if sale_price <= 0:
            raise RuntimeError(f"[르무통 공홈] sale_price 추출 실패 ({sale_price}) — Fail-safe")

        # V7 색상/사이즈 분류
        btn_groups = page.evaluate(
            """
            () => {
                const lis = [...document.querySelectorAll('ul.ec-product-button li')];
                const items = lis.map(li => ({
                    name: (li.innerText || '').trim(),
                    soldOut: li.classList.contains('ec-product-soldout'),
                    isMm: /mm\\s*$/i.test((li.innerText || '').trim()),
                })).filter(b => b.name);
                return {
                    colors: items.filter(b => !b.isMm),
                    sizes:  items.filter(b => b.isMm),
                };
            }
            """
        )
        colors: list[dict] = btn_groups["colors"]
        initial_sizes: list[dict] = btn_groups["sizes"]

        options: list[dict] = []

        # ★ 2026-05-13 잔여 #3a — 르무통 공홈 자동 카드 (혜택가 단계 적용, sale_price 미반영)
        _auto_card = {
            "issuer": "현대카드",
            "rate": 2.73,
            "label": "현대카드 2.73%",
            "included_in_sale_price": False,  # 캐시백 — sale_price 와 별개
        }

        if colors and initial_sizes:
            # V7: 색상별 클릭 → 사이즈 다시 읽기
            for color in colors:
                color_name = color["name"]
                # 색상이 자체 품절이면 사이즈 클릭 의미 없음 — 모든 사이즈를 품절 처리
                if color["soldOut"]:
                    for size in initial_sizes:
                        options.append({
                            "option_id": f"{product_no}|{color_name}|{size['name']}",
                            "color_text": color_name,
                            "size_text": size["name"],
                            "price": sale_price, "sale_price": sale_price,
                            "auto_card_discount": _auto_card,
                            "stock": 0,
                        })
                    continue

                # V7: 색상 클릭 (텍스트 일치하는 첫 li, isMm=false 인 항목)
                page.evaluate(
                    """
                    (name) => {
                        const lis = [...document.querySelectorAll('ul.ec-product-button li')];
                        const target = lis.find(li => {
                            const t = (li.innerText || '').trim();
                            return t === name && !/mm\\s*$/i.test(t);
                        });
                        if (target) target.click();
                    }
                    """,
                    color_name,
                )
                page.wait_for_timeout(self.click_wait_ms)

                sizes_after = page.evaluate(
                    """
                    () => {
                        return [...document.querySelectorAll('ul.ec-product-button li')]
                            .filter(li => /mm\\s*$/i.test((li.innerText || '').trim()))
                            .map(li => ({
                                name: (li.innerText || '').trim(),
                                soldOut: li.classList.contains('ec-product-soldout'),
                                disabled: li.classList.contains('ec-product-disabled'),
                            }));
                    }
                    """
                )
                for size in sizes_after:
                    # disabled = 색상에 그 사이즈가 아예 없음 → 품절 동등 처리
                    is_unavailable = bool(size["soldOut"] or size["disabled"])
                    options.append({
                        "option_id": f"{product_no}|{color_name}|{size['name']}",
                        "color_text": color_name,
                        "size_text": size["name"],
                        "price": sale_price, "sale_price": sale_price,
                        "auto_card_discount": _auto_card,
                        # 999 = 재고있음(수량 미상) — 타 소싱처(무신사/SSF/롯데온) 센티넬과 통일. 0 = 품절.
                        "stock": 0 if is_unavailable else 999,
                    })

        elif initial_sizes and not colors:
            # 색상 없음 — V7 lemoutonParseProduct: 상품명 마지막 단어 = 색상
            name_parts = product_name.split(" ")
            color_name = name_parts[-1] if name_parts else ""
            for size in initial_sizes:
                options.append({
                    "option_id": f"{product_no}|{color_name}|{size['name']}",
                    "color_text": color_name,
                    "size_text": size["name"],
                    "price": sale_price, "sale_price": sale_price,
                    "auto_card_discount": _auto_card,
                    "stock": 0 if size["soldOut"] else 999,
                })

        elif colors and not initial_sizes:
            # 사이즈 없음 — V7 와 동일하게 단일 행 (size 빈 문자열)
            for color in colors:
                options.append({
                    "option_id": f"{product_no}|{color['name']}|",
                    "color_text": color["name"],
                    "size_text": "",
                    "price": sale_price, "sale_price": sale_price,
                    "auto_card_discount": _auto_card,
                    "stock": 0 if color["soldOut"] else 999,
                })

        else:
            # V7 단품 폴백
            name_parts = product_name.split(" ")
            color_name = name_parts[-1] if name_parts else ""
            options.append({
                "option_id": f"{product_no}|{color_name}|",
                "color_text": color_name,
                "size_text": "",
                "price": sale_price, "sale_price": sale_price,
                "auto_card_discount": _auto_card,
                "stock": 999,
            })

        # discount_info: 기본할인 % 만 (혜택은 api_benefits 가 단일 진실 원천)
        return CrawlResult(
            source=self.source_name,
            product_url=product_url,
            product_name_raw=product_name,
            options=options,
            brand="르무통",
            discount_info=f"기본할인 {discount_rate}%" if discount_rate else "",
        )
