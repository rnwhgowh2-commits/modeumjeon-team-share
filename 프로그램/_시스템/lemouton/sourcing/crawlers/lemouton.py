"""르무통 공홈 (lemouton.co.kr / m.lemouton.co.kr) 크롤러.

V7 (Chrome extension) 의 lemouton 크롤링 로직을 Python으로 1:1 포팅.

원본 V7 위치:
  - background/background.js
      crawlLemoutonBundle()       — 색상+사이즈 혼합 버튼 구조 파서 (lemouton.co.kr 라우팅)
      lemoutonParseProduct()      — 단품(색상 1개) 파서 (폴백)

V7 로직 요약 (변경 금지):
  1. 라우팅: lemouton.co.kr 매칭 → 항상 Bundle 파서 진입
  2. 버튼 분류: ul.ec-product-button li
       - innerText 가 ``/mm$/i`` 매칭이면 사이즈
       - 아니면 색상
  3. 품절 판정: li.ec-product-soldout 클래스
  4. 색상 0 개 → 단품 파서 폴백 (productName 마지막 단어 = 색상)
  5. 가격 (V7 셀렉터, 우선순위 순):
       - 할인가:   strong.price-number
       - 원가:     span.txt_price.ProductPrice 또는 span.ProductPrice
       - 할인율:   span.ec-sale-rate (없으면 (1 - sale/origin) 계산)
  6. productId: URL 쿼리 파라미터 ``product_no``

Python 환경 한계 보강 (V7 로직 보존, 셀렉터 동일):
  - V7 는 페이지가 JS 렌더링된 후 셀렉터를 읽지만, requests 는 raw HTML 만 받는다.
  - ``strong.price-number`` / ``span.ec-sale-rate`` 는 JS 로 채워지므로 raw 단계에서 비어있다.
  - V7 와 동일한 가격 의미를 raw HTML 에서 가져오기 위해 다음 폴백 체인을 적용:
        sale: span.ProductPrice → meta[product:sale_price:amount] → JS var product_price
        orig: span.txt_price.ProductPrice → span.ProductPrice → meta[product:price:amount]
    (V7 셀렉터를 첫 우선순위로 그대로 사용, 비어있을 때만 등가 raw 출처로 대체)
  - 색상 클릭 시뮬레이션은 raw HTML 에서 색상·사이즈가 동시 노출되므로
    "모든 색상 × 모든 사이즈" 데카르트 곱으로 행을 생성한다 (V7 Bundle 의 결과와 동치).
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional
from urllib.parse import urlparse, parse_qs

import requests
from bs4 import BeautifulSoup

from .base import AbstractCrawler, CrawlResult, build_category_path


logger = logging.getLogger(__name__)


def _playwright_available() -> bool:
    """Playwright 패키지 + chromium 브라우저 모두 사용 가능한지 확인."""
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
        return True
    except ImportError:
        return False


# V7 와 동일한 데스크톱 UA (모바일 페이지도 동일하게 응답)
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
DEFAULT_TIMEOUT = 30

# V7: /mm$/i — innerText 끝이 mm 이면 사이즈
SIZE_PATTERN = re.compile(r"mm\s*$", re.IGNORECASE)


def _digits_only(text: str | None) -> str:
    """V7: replace(/[^0-9]/g, '')."""
    if not text:
        return ""
    return re.sub(r"[^0-9]", "", text)


def _to_int(text: str | None) -> int:
    """V7: parseInt(...) || 0."""
    s = _digits_only(text)
    if not s:
        return 0
    try:
        return int(s)
    except ValueError:
        return 0


def _extract_product_no(product_url: str) -> str:
    """V7: new URLSearchParams(productUrl.split('?')[1]).get('product_no')."""
    qs = parse_qs(urlparse(product_url).query)
    vals = qs.get("product_no", [])
    return vals[0] if vals else ""


def _parse_buttons(soup: BeautifulSoup) -> list[dict]:
    """V7 Bundle: ul.ec-product-button li → {name, soldOut, isMm}.

    버튼 텍스트가 비어있는 항목은 제거 (V7: ``filter(b => b.name)``).
    """
    btns: list[dict] = []
    for li in soup.select("ul.ec-product-button li"):
        name = li.get_text(strip=True)
        if not name:
            continue
        classes = li.get("class") or []
        btns.append({
            "name": name,
            "soldOut": "ec-product-soldout" in classes,
            "isMm": bool(SIZE_PATTERN.search(name)),
        })
    return btns


def _parse_product_name(soup: BeautifulSoup, override_name: Optional[str]) -> str:
    """V7 lemoutonParseProduct 의 상품명 추출 로직 1:1 포팅 + 모바일 보강.

    V7 원본 (PC 페이지 기준):
        h2 중 길이 2~100, '[' 시작 X,
        '확대'/'Ambassador'/'Natural'/'Travel'/'리뷰' 미포함 → 첫 번째 매칭이 상품명.
        폴백: ``document.title.split('-')[0]``.

    모바일 ``m.lemouton.co.kr`` 한정 보강:
        - 모바일에는 PC 와 다른 마케팅 섹션 h2 (NaturalStory, MerinoWool, Performance,
          상품상세 정보, 추가구성상품, WITH ITEM, 리뷰유도팝업 등) 가 깔려있고
          V7 필터로는 일부만 걸러진다.
        - 모바일 페이지의 ``meta[og:title]`` 은 V7 가 폴백으로 쓰던 ``document.title``
          과 정확히 동일한 의미(브라우저 탭 제목 = 페이지 헤드의 상품명)이다.
        - 따라서 모바일 마케팅 h2 가 V7 필터를 통과해 잘못 잡히는 것을 막기 위해
          제외어 목록을 확장한다 (V7 의도 = "상품명 h2 만" 유지, 셀렉터 변경 없음).
    """
    if override_name:
        return override_name

    # [2026-06-21] og:title 우선 — 페이지 head 의 정식 상품명. 르무통 PC 페이지의 '첫 h2'가
    #   '메인메뉴'(내비)라서 그게 상품명으로 잘못 잡히던 문제(상품명='메인메뉴' 사고). og:title 은
    #   PC·모바일 모두 정확한 상품명("르무통 메이트 발 편한 메리노울 운동화")이라 최우선으로 쓴다.
    og = soup.find("meta", attrs={"property": "og:title"})
    if og and og.get("content"):
        _ogt = og["content"].strip()
        if _ogt and 2 < len(_ogt) < 150:
            return _ogt

    # V7 원본 제외어 (background.js: '확대','Ambassador','Natural','Travel','리뷰')
    # + 모바일 페이지 전용 섹션·마케팅 헤더 (V7 PC 페이지엔 없던 h2 들 — 상품명이 아님).
    excluded_substrings = (
        # V7 원본 5개
        "확대", "Ambassador", "Natural", "Travel", "리뷰",
        # 모바일 추가 — generic 섹션 헤더
        "상품상세", "추가구성", "WITH ITEM",
        # 모바일 추가 — 마케팅 h2 (메리노울 모델 모음전 페이지 공통)
        "MerinoWool", "Performance", "Fiber", "LeMouton", "100%",
        # [2026-06-21] PC 페이지 내비 헤더 (상품명 아님)
        "메인메뉴",
    )
    for h2 in soup.find_all("h2"):
        t = h2.get_text(strip=True)
        if not t or not (2 < len(t) < 100):
            continue
        if any(s in t for s in excluded_substrings):
            continue
        if t.startswith("["):
            continue
        return t

    # V7 폴백 1: document.title.split('-')[0].trim()
    title_el = soup.find("title")
    if title_el:
        title = title_el.get_text(strip=True)
        if title:
            # V7 는 '-' 분리, 모바일 lemouton 은 '|' 분리 → 둘 다 시도
            for sep in ("-", "|"):
                if sep in title:
                    return title.split(sep)[0].strip()
            return title

    # V7 폴백 2 (Python 보강): meta[og:title] = V7 document.title 의 head 출처
    og = soup.find("meta", attrs={"property": "og:title"})
    if og and og.get("content"):
        return og["content"].strip()

    return ""


def _parse_category_path(soup: BeautifulSoup) -> str:
    """[2026-07-23 M3] Cafe24 '현재 위치' 빵부스러기 → '대>중>소'.

    실화면 확인(lemouton.co.kr 상품 페이지, 2026-07-23):
        <div class="xans-element- xans-product xans-product-headcategory path ">
          <span>현재 위치</span>
          <ol><li><a href="/">홈</a></li>
              <li><a href="/category/men/63/">Men</a></li>
              <li><a href="/category/클래식/64/">클래식</a></li>
              <li class="displaynone"><a href=""></a></li>   ← 빈 자리(4·5단계 미사용)
              <li class="displaynone"><strong><a href=""></a></strong></li></ol></div>

    빈 `displaynone` 항목은 텍스트가 없어 `build_category_path` 가 자동으로 걸러낸다.
    ⚠️ Cafe24 빵부스러기는 URL 의 `cate_no` 로 결정된다 — `cate_no` 없이 들어온 URL 은
       '홈' 만 남아 빈 문자열이 된다(= 카테고리 확인불가. 지어내지 않는다).
    """
    box = soup.select_one("div.xans-product-headcategory")
    if not box:
        return ""
    return build_category_path([a.get_text(strip=True) for a in box.select("ol li a")])


def _parse_prices(soup: BeautifulSoup, html: str) -> tuple[int, int, int]:
    """V7 가격 셀렉터 1:1 포팅 + raw-HTML 폴백.

    V7 셀렉터 (1순위):
        sale: strong.price-number
        orig: span.txt_price.ProductPrice  또는  span.ProductPrice
        rate: span.ec-sale-rate

    raw HTML 폴백 (1순위가 비었을 때만, 등가 의미 출처):
        sale: span.ProductPrice → meta[property=product:sale_price:amount]
              → JS var product_price = '...'
        orig: meta[property=product:price:amount]

    rate 는 V7 그대로: 셀렉터 없으면 ``round((1 - sale/origin) * 100)`` 계산.

    Returns: (sale_price, origin_price, discount_rate)
    """
    # V7: strong.price-number
    sale_el = soup.select_one("strong.price-number")
    sale_price = _to_int(sale_el.get_text() if sale_el else "")

    # V7: span.txt_price.ProductPrice, span.ProductPrice (CSV in V7 querySelector)
    orig_el = soup.select_one("span.txt_price.ProductPrice, span.ProductPrice")
    origin_price = _to_int(orig_el.get_text() if orig_el else "")

    # 폴백 체인 — V7 셀렉터가 비었을 때만 (raw HTML 환경 보강)
    if sale_price == 0:
        # span.ProductPrice 단일 (모바일 페이지)
        if origin_price > 0:
            sale_price = origin_price
        else:
            meta_sale = soup.find("meta", attrs={"property": "product:sale_price:amount"})
            if meta_sale and meta_sale.get("content"):
                sale_price = _to_int(meta_sale["content"])
            if sale_price == 0:
                m = re.search(r"var\s+product_price\s*=\s*'([^']+)'", html)
                if m:
                    sale_price = _to_int(m.group(1))

    if origin_price == 0:
        meta_orig = soup.find("meta", attrs={"property": "product:price:amount"})
        if meta_orig and meta_orig.get("content"):
            origin_price = _to_int(meta_orig["content"])

    # V7: originPrice || salePrice
    if origin_price == 0:
        origin_price = sale_price

    # V7: span.ec-sale-rate || 계산
    rate_el = soup.select_one("span.ec-sale-rate")
    if rate_el:
        discount_rate = _to_int(rate_el.get_text())
    elif origin_price > sale_price and sale_price > 0:
        discount_rate = round((1 - sale_price / origin_price) * 100)
    else:
        discount_rate = 0

    return sale_price, origin_price, discount_rate


def _parse_option_stock_data(html: str) -> list[dict] | None:
    """Cafe24 가 raw HTML 에 심어둔 ``var option_stock_data`` JSON 을 파싱.

    이 변수는 색상×사이즈 **실제 조합** 만 키로 가지며, 각 조합의 실재고
    (``stock_number``)·판매여부(``is_selling``)·노출여부(``is_display``)·
    조합가(``option_price``)·축원본값(``option_value_orginal`` = [색상, 사이즈]) 을 담는다.

    ``_parse_buttons`` 의 데카르트 곱(색상 × 사이즈 전체 → 미판매 사이즈까지 999 로 날조)과
    달리, 여기엔 그 색상이 **실제로 파는 사이즈만** 들어있다. 따라서 미판매 조합
    (예: 오렌지 260~290mm) 은 키 자체가 없어 원천적으로 제외되고, 품절(stock_number=0)·
    실수량(stock_number>0) 이 정확히 구분된다. 정적 HTML 만으로 Playwright 동등 정확도.

    Returns:
        조합 dict 리스트 ``[{color_text, size_text, price, stock}, ...]``.
        변수 부재(구형 템플릿)·파싱 실패·빈 데이터면 ``None`` → 호출자는 레거시 버튼 파서로 폴백.
    """
    m = re.search(r"var\s+option_stock_data\s*=\s*'(.*?)';", html, re.S)
    if not m:
        return None
    try:
        # JS 단일따옴표 문자열 본문 = JSON 문자열 본문(\" \\ \\uXXXX 이스케이프) → 2단 디코드.
        #   1단: json.loads('"' + 본문 + '"')  → JS 이스케이프 해제 → JSON 텍스트
        #   2단: json.loads(JSON 텍스트)        → dict
        data = json.loads(json.loads('"' + m.group(1) + '"'))
    except (ValueError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or not data:
        return None

    rows: list[dict] = []
    for entry in data.values():
        if not isinstance(entry, dict):
            continue
        # 페이지에 노출되지 않는 옵션(is_display=F)은 판매 대상이 아님 → 제외.
        if str(entry.get("is_display", "T")).upper() == "F":
            continue
        ov = entry.get("option_value_orginal")
        if not isinstance(ov, list) or not ov:
            continue
        # 축 순서 무관 분류: mm 로 끝나는 토큰 = 사이즈, 나머지 = 색상
        # (V7 버튼 분류 ``/mm$/i`` 와 동일 규칙 — 단품/사이즈만 옵션도 안전 처리).
        size_text = ""
        color_parts: list[str] = []
        for tok in ov:
            tok = (tok or "").strip()
            if not tok:
                continue
            if not size_text and SIZE_PATTERN.search(tok):
                size_text = tok
            else:
                color_parts.append(tok)
        color_text = " ".join(color_parts)

        # 재고: stock_number 가 실수량. 판매중지(is_selling=F)면 품절(0)로 표면화.
        try:
            stock = int(entry.get("stock_number"))
        except (TypeError, ValueError):
            stock = 0
        if stock < 0:
            stock = 0
        if str(entry.get("is_selling", "T")).upper() == "F":
            stock = 0

        try:
            price = int(entry.get("option_price"))
        except (TypeError, ValueError):
            price = 0

        rows.append({
            "color_text": color_text,
            "size_text": size_text,
            "price": price,
            "stock": stock,
        })
    return rows or None


class LemoutonCrawler(AbstractCrawler):
    """르무통 공식몰 크롤러 — Playwright 우선, 정적 HTML fallback.

    정확도 격차 (검증된 사실):
      - 정적 HTML: Cafe24 가 모든 사이즈를 ``ec-product-disabled`` 로 노출.
        ``ec-product-soldout`` 클래스는 색상 클릭 시점에 JS 가 동적으로 토글하므로
        정적 응답에는 색상별 사이즈 품절 정보가 들어있지 않다 → 모든 옵션을 "재고 있음"
        으로 잘못 보고할 수 있음.
      - Playwright: V7 ``crawlLemoutonBundle`` 과 동일하게 색상 버튼 클릭 → JS 토글 후
        사이즈를 다시 읽으므로 색상별 사이즈 품절을 정확하게 수집.

    Dispatcher 동작:
      1. Playwright 임포트 가능 → ``PlaywrightLemoutonCrawler.fetch`` 호출
      2. Playwright 임포트 실패 또는 런타임 에러 → 정적 HTML 파서로 fallback
         (단품 케이스는 정적 HTML 만으로도 정확)
    """

    source_name = "lemouton"

    def __init__(self, prefer_playwright: bool = True):
        self.prefer_playwright = prefer_playwright

    def fetch(self, product_url: str) -> CrawlResult:
        if self.prefer_playwright and _playwright_available():
            try:
                from .lemouton_playwright import PlaywrightLemoutonCrawler
                return PlaywrightLemoutonCrawler().fetch(product_url)
            except Exception as e:
                logger.warning(
                    "[lemouton] Playwright 크롤 실패 — 정적 HTML fallback. err=%s: %s",
                    type(e).__name__, e,
                )
        return self._fetch_static(product_url)

    def parse_html(self, html: str, product_url: str) -> CrawlResult:
        """받은 HTML 을 파싱해 CrawlResult 반환 (네트워크 없음 — A안 확장 진입점).

        _fetch_static 의 순수 파싱 부분을 분리한 메서드.
        fetch / _fetch_static 의 동작은 100% 불변.
        """
        soup = BeautifulSoup(html, "lxml")

        product_no = _extract_product_no(product_url)
        product_name = _parse_product_name(soup, override_name=None)
        sale_price, origin_price, discount_rate = _parse_prices(soup, html)
        category_path = _parse_category_path(soup)   # [2026-07-23 M3] 못 뽑으면 ''

        # ★ 1순위: Cafe24 ``option_stock_data`` (실조합·실재고).
        #   색상별 실제 판매 사이즈만 들어있어 미판매 사이즈가 원천 배제되고,
        #   품절/실수량이 정확. 버튼 데카르트 곱(전 색상 × 전 사이즈 = 999 날조)을 대체.
        stock_rows = _parse_option_stock_data(html)
        if stock_rows:
            name_parts = product_name.split(" ")
            fallback_color = name_parts[-1] if name_parts else ""
            options: list[dict] = []
            for r in stock_rows:
                color_text = r["color_text"] or fallback_color
                price = r["price"] or sale_price
                options.append({
                    "option_id": f"{product_no}|{color_text}|{r['size_text']}",
                    "color_text": color_text,
                    "size_text": r["size_text"],
                    "price": price,
                    "sale_price": price,
                    "stock": r["stock"],
                })
            return CrawlResult(
                source=self.source_name,
                product_url=product_url,
                product_name_raw=product_name,
                options=options,
                brand="르무통",
                discount_info=f"기본할인 {discount_rate}%" if discount_rate else "",
                category_path=category_path,
            )

        # 폴백: option_stock_data 부재(구형 템플릿/비정상 페이지) → 레거시 버튼 파서.
        #   ⚠️ 이 경로는 색상별 사이즈 가용 정보를 raw HTML 에서 알 수 없어 데카르트 곱을
        #   쓴다(미판매 사이즈가 999 로 섞일 수 있음). 정상 상품은 항상 1순위로 처리됨.
        logger.warning(
            "[lemouton] option_stock_data 없음 — 레거시 버튼 파서 폴백 (데카르트 곱). url=%s",
            product_url,
        )
        btns = _parse_buttons(soup)
        color_btns = [b for b in btns if not b["isMm"]]
        size_btns = [b for b in btns if b["isMm"]]

        options: list[dict] = []

        if color_btns and size_btns:
            # V7 crawlLemoutonBundle: 색상별 × 사이즈별 행 생성
            # 모바일 raw HTML 은 모든 색상·사이즈를 동시 노출하므로 클릭 시뮬레이션 불필요
            for color in color_btns:
                for size in size_btns:
                    is_sold_out = bool(color["soldOut"] or size["soldOut"])
                    options.append({
                        "option_id": f"{product_no}|{color['name']}|{size['name']}",
                        "color_text": color["name"],
                        "size_text": size["name"],
                        "price": sale_price,
                        "sale_price": sale_price,
                        "stock": 0 if is_sold_out else 999,
                    })
        elif size_btns and not color_btns:
            # V7 lemoutonParseProduct: 색상 없음 → productName 마지막 단어 = 색상
            name_parts = product_name.split(" ")
            color_name = name_parts[-1] if name_parts else ""
            for size in size_btns:
                options.append({
                    "option_id": f"{product_no}|{color_name}|{size['name']}",
                    "color_text": color_name,
                    "size_text": size["name"],
                    "price": sale_price,
                    "sale_price": sale_price,
                    "stock": 0 if size["soldOut"] else 999,
                })
        elif color_btns and not size_btns:
            # 사이즈 없음 (드문 케이스) — V7 에서도 size.name='' 단일 행
            for color in color_btns:
                options.append({
                    "option_id": f"{product_no}|{color['name']}|",
                    "color_text": color["name"],
                    "size_text": "",
                    "price": sale_price,
                    "sale_price": sale_price,
                    "stock": 0 if color["soldOut"] else 999,
                })
        else:
            # V7 단품 폴백: 행이 0개면 단일 행 — color = productName 마지막 단어
            name_parts = product_name.split(" ")
            color_name = name_parts[-1] if name_parts else ""
            options.append({
                "option_id": f"{product_no}|{color_name}|",
                "color_text": color_name,
                "size_text": "",
                "price": sale_price,
                "sale_price": sale_price,
                "stock": 999,
            })

        return CrawlResult(
            source=self.source_name,
            product_url=product_url,
            product_name_raw=product_name,
            options=options,
            brand="르무통",
            discount_info=f"기본할인 {discount_rate}%" if discount_rate else "",
            category_path=category_path,
        )

    def _fetch_static(self, product_url: str) -> CrawlResult:
        resp = requests.get(
            product_url,
            headers={"User-Agent": USER_AGENT},
            timeout=DEFAULT_TIMEOUT,
        )
        resp.raise_for_status()
        html = resp.text
        return self.parse_html(html, product_url)
