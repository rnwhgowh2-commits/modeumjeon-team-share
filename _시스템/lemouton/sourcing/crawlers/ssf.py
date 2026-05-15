"""SSF샵 (www.ssfshop.com) 단품 크롤러.

V7 (Chrome extension) 의 ssf 크롤링 로직을 Python 으로 1:1 포팅.

V7 원본 위치: ``크롤러_V7_쿠팡 반영/background/background.js``
  - ``crawlSSF(url, productName)`` — 탭 오픈 → ``ssfParseProduct`` 실행 → 행 반환
  - ``ssfParseProduct(productUrl, overrideName)`` — DOM 에서 메타·가격·옵션·재고 파싱

V7 흐름 한국어 요약 (변경 금지):
  1. 상품명 + 현재 컬러: ``div.gods-name`` innerText → ``split(' ')`` 마지막 토큰 = currentColor
       - productName = 마지막 토큰 제외한 나머지 (단어 1 개뿐이면 godsName 그대로)
       - 폴백: ``document.title.split('|')[0].trim()``
  2. 브랜드: ``h2.brand-name`` (없으면 'SSF샵')
  3. 가격:
       - originPrice (정가): ``del`` 의 텍스트에서 숫자만
       - salePrice  (할인가): ``em.price`` 텍스트에서 숫자만 (없으면 originPrice)
       - discountRate: ``span.ec-sale-rate`` 가 아닌, V7 SSF 는 originPrice/salePrice 로 계산
       - discountInfo: ``.tip-txt`` (없으면 ``즉시할인 {.discount}``)
  4. productId: URL 에서 ``/(BRAND)/(GOODSCD)/good`` 의 GOODSCD
       - 정규식 1: ``/([A-Z0-9]+)/good``
       - 정규식 2 (폴백): ``/([^/]+)/good``
  5. 컬러 목록: 단일 컬러 (현재 페이지 컬러만). SSF 는 컬러별 별도 URL 구조이므로
       ``colors = [{name: currentColor, soldOut: false}]``.
  6. 사이즈 목록: ``#optionDiv1 li a[optcd]`` 전체
       - name: ``optcd`` 속성 + 'mm'
       - soldOut: ``statcd`` 속성이 'SLDOUT' (판매중은 'SALE_PROGRS')
       - stock: 부모 li 의 innerText 에 ``품절임박 (N)`` 패턴 매칭 시 N
  7. 행 생성: 컬러 × 사이즈 데카르트 곱
       - isSoldOut = color.soldOut OR size.soldOut
       - stockStatus: '품절' / '재고있음'
       - stockQuantity: size.stock (품절임박 N 또는 None)
  8. 폴백 (사이즈 0개 → 단일 행): option1=currentColor, option2=''

Python 환경 한계 보강 (V7 의도 보존, 셀렉터 변경 없음):
  - V7 는 Chrome 탭에서 JS 렌더 후 DOM 을 읽지만, SSF 페이지는 핵심 정보 (상품명/가격/사이즈/
    statcd/품절임박) 가 raw HTML 에 모두 포함되어 있다. 따라서 ``curl_cffi`` (chrome120
    impersonate) 로 raw HTML 을 받아 BeautifulSoup 으로 V7 셀렉터를 그대로 적용한다.
  - Cloudflare bot detection 회피를 위해 ``curl_cffi`` 사용 (T11 무신사와 동일).
"""
from __future__ import annotations

import re
from typing import Optional

from curl_cffi import requests as cffi_requests
from bs4 import BeautifulSoup

from .base import AbstractCrawler, CrawlResult


# ─────────────────────────────────────────────────────────────
# V7 동등 상수
# ─────────────────────────────────────────────────────────────
DEFAULT_TIMEOUT = 30
IMPERSONATE = "chrome120"  # T11 musinsa 와 동일 — Cloudflare 통과

# V7: ``productUrl.match(/\/([A-Z0-9]+)\/good/)?.[1]``
PRODUCT_ID_PATTERN_STRICT = re.compile(r"/([A-Z0-9]+)/good")
# V7 폴백: ``productUrl.match(/\/([^/]+)\/good/)?.[1]``
PRODUCT_ID_PATTERN_LOOSE = re.compile(r"/([^/]+)/good")

# V7: ``liText.match(/품절임박\s*\((\d+)\)/)``
NEAR_SOLDOUT_PATTERN = re.compile(r"품절임박\s*\((\d+)\)")

# 2026-05-14 — 기프트포인트 (멤버십 한정, 활성 시만 노출 / 변동값)
#   HTML 예시: ``<dt>기프트포인트</dt><dd>멤버십 고객 한정 최대 5,600원 할인(10%)``
#   ``\d{1,3}(?:,\d{3})*원`` — 콤마 포함 숫자 + '원'
GIFT_POINT_PATTERN = re.compile(
    r"기프트포인트\s*</dt>\s*<dd>[^<]*?([\d,]+)\s*원",
    re.DOTALL,
)

# 2026-05-15 — 포인트 적립 (멤버십 상품별 변동값, DB 0.5% 고정 폐기)
#   HTML 예시: ``<dt>포인트 적립</dt><dd><span class="point-item">멤버십포인트 2,802P``
#   상품마다 0.5% / 5% / 등 % 가 다르게 노출 — sale_price 로 나눠 rate 동적 계산.
POINT_AMOUNT_PATTERN = re.compile(
    r"포인트\s*적립\s*</dt>\s*<dd>.*?멤버십포인트\s*([\d,]+)\s*P",
    re.DOTALL,
)

# 2026-05-15 — 첫 구매 쿠폰: 사용자 명세 "제외"로 추출 자체 제거 (매입가 미반영).

# V7 statcd 상수
STATCD_SOLDOUT = "SLDOUT"


def _digits_only(text: str | None) -> str:
    """V7: ``replace(/[^0-9]/g, '')``."""
    if not text:
        return ""
    return re.sub(r"[^0-9]", "", text)


def _to_int(text: str | None) -> int:
    """V7: ``parseInt(...) || 0``."""
    s = _digits_only(text)
    if not s:
        return 0
    try:
        return int(s)
    except ValueError:
        return 0


def _extract_product_id(product_url: str) -> str:
    """V7: ``url.match(/\\/([A-Z0-9]+)\\/good/)?.[1] || url.match(/\\/([^/]+)\\/good/)?.[1] || ''``."""
    m = PRODUCT_ID_PATTERN_STRICT.search(product_url)
    if m:
        return m.group(1)
    m = PRODUCT_ID_PATTERN_LOOSE.search(product_url)
    if m:
        return m.group(1)
    return ""


def _parse_name_and_color(
    soup: BeautifulSoup, override_name: Optional[str]
) -> tuple[str, str]:
    """V7: ``div.gods-name`` innerText → ``split(' ')`` 마지막 = currentColor.

    Returns: (product_name, current_color)

    V7 원본:
        const godsName     = document.querySelector('div.gods-name')?.innerText?.trim() || '';
        const nameParts    = godsName.split(' ');
        const currentColor = nameParts.slice(-1)[0] || '';
        const productName  = overrideName ||
            (nameParts.length > 1 ? nameParts.slice(0, -1).join(' ') : godsName) ||
            document.title.split('|')[0].trim();
    """
    el = soup.select_one("div.gods-name")
    gods_name = el.get_text(strip=True) if el else ""
    name_parts = gods_name.split(" ") if gods_name else []
    current_color = name_parts[-1] if name_parts else ""

    if override_name:
        product_name = override_name
    elif len(name_parts) > 1:
        product_name = " ".join(name_parts[:-1])
    elif gods_name:
        product_name = gods_name
    else:
        # V7 폴백: ``document.title.split('|')[0].trim()``
        title_el = soup.find("title")
        if title_el:
            t = title_el.get_text(strip=True)
            product_name = t.split("|")[0].strip() if t else ""
        else:
            product_name = ""

    return product_name, current_color


def _parse_prices(soup: BeautifulSoup) -> tuple[int, int, int]:
    """V7 가격 셀렉터 1:1 포팅.

    V7 원본:
        const originPrice  = parseInt(document.querySelector('del')?.innerText?.replace(/[^0-9]/g,'')) || 0;
        const salePrice    = parseInt(document.querySelector('em.price')?.innerText?.replace(/[^0-9]/g,'')) || originPrice;
        const discountRate = originPrice > salePrice && salePrice > 0
            ? Math.round((1 - salePrice / originPrice) * 100) : 0;

    Returns: (sale_price, origin_price, discount_rate)
    """
    del_el = soup.find("del")
    origin_price = _to_int(del_el.get_text() if del_el else "")

    em_el = soup.select_one("em.price")
    sale_price = _to_int(em_el.get_text() if em_el else "")
    # V7: ``|| originPrice``
    if sale_price == 0:
        sale_price = origin_price

    # V7 SSF: discount rate 는 셀렉터 없이 계산만
    if origin_price > sale_price and sale_price > 0:
        discount_rate = round((1 - sale_price / origin_price) * 100)
    else:
        discount_rate = 0

    return sale_price, origin_price, discount_rate


def _parse_brand(soup: BeautifulSoup) -> str:
    """V7: ``document.querySelector('h2.brand-name')?.innerText?.trim() || 'SSF샵'``."""
    el = soup.select_one("h2.brand-name")
    if el:
        text = el.get_text(strip=True)
        if text:
            return text
    return "SSF샵"


def _parse_discount_info(soup: BeautifulSoup) -> str:
    """V7: ``.tip-txt`` 텍스트 우선, 없으면 ``즉시할인 {.discount}``.

    V7 원본:
        const discountPct  = document.querySelector('.discount')?.innerText?.trim() || '';
        const discountInfo = document.querySelector('.tip-txt')?.innerText?.trim() ||
            (discountPct ? `즉시할인 ${discountPct}` : '');
    """
    tip = soup.select_one(".tip-txt")
    if tip:
        text = tip.get_text(strip=True)
        if text:
            return text
    pct = soup.select_one(".discount")
    if pct:
        text = pct.get_text(strip=True)
        if text:
            return f"즉시할인 {text}"
    return ""


def _parse_point_rate(html: str, sale_price: int) -> tuple[Optional[float], Optional[int]]:
    """포인트 적립률·금액 추출 (변동값, 상품별 노출).

    SSF HTML 예시:
        <dt>포인트 적립</dt><dd>
            <span class="point-item">멤버십포인트 2,802P&nbsp;</span>
        </dd>

    DB source_id=4 의 benefit_id=13 "구매적립금 (포인트)" 은 0.5% 고정으로
    seeding 돼 있으나, 실제로는 5% / 0.5% / 기타 % 가 상품마다 다르게 노출된다.
    따라서 raw HTML 에서 멤버십포인트 정액(P)을 뽑아 sale_price 로 나눠
    rate 를 동적으로 계산한다. (해당 dt/dd 블록은 ``card-decc`` 영역 밖에 단독
    구조이므로 BeautifulSoup 셀렉터 대신 raw HTML 정규식이 견고하다.)

    Args:
        html: 원본 HTML
        sale_price: 판매가 (rate 계산용)

    Returns:
        (rate, amount) — rate 는 소수(예: 0.05 == 5%), amount 는 정수 P
        노출 안 되면 (None, None).
    """
    m = POINT_AMOUNT_PATTERN.search(html)
    if not m:
        return None, None
    try:
        amount = int(m.group(1).replace(",", ""))
    except (ValueError, AttributeError):
        return None, None
    if amount <= 0 or sale_price <= 0:
        return None, amount if amount > 0 else None
    rate = round(amount / sale_price, 4)  # 0.0050, 0.0500 등 4자리
    return rate, amount


def _parse_gift_point(html: str) -> Optional[int]:
    """기프트포인트 정액 추출 (활성 시만 노출 / 변동값).

    SSF HTML 예시:
        <dt>기프트포인트</dt><dd>멤버십 고객 한정 최대 5,600원 할인(10%) ...

    셀렉터(BeautifulSoup) 대신 raw HTML 정규식 사용 — V7 에는 없는 항목이고,
    노출 시 dl/dt/dd 구조가 ``card-decc`` 영역 밖에 단독으로 박혀 있어
    raw HTML 정규식이 가장 견고하다.

    Returns:
        정수 원 금액 (예: 5600) 또는 None (노출 안 됨).
    """
    m = GIFT_POINT_PATTERN.search(html)
    if not m:
        return None
    try:
        return int(m.group(1).replace(",", ""))
    except (ValueError, AttributeError):
        return None


def _parse_sizes(soup: BeautifulSoup) -> list[dict]:
    """V7: ``#optionDiv1 li a[optcd]`` → {name, soldOut, stock}.

    V7 원본:
        const sizeEls = [...document.querySelectorAll('#optionDiv1 li a[optcd]')];
        sizeEls.map(a => {
            const li = a.closest('li');
            const liText = li ? li.innerText || '' : '';
            const soldOut = a.getAttribute('statcd') === 'SLDOUT';
            let stock = null;
            const qtyMatch = liText.match(/품절임박\\s*\\((\\d+)\\)/);
            if (qtyMatch) stock = parseInt(qtyMatch[1]);
            return {
                name:    (a.getAttribute('optcd') || '') + 'mm',
                soldOut,
                stock,
            };
        }).filter(s => s.name)
    """
    out: list[dict] = []
    for a in soup.select("#optionDiv1 li a[optcd]"):
        # V7: ``a.closest('li')`` — 가장 가까운 li 조상
        li = a.find_parent("li")
        li_text = li.get_text(" ", strip=True) if li else ""
        statcd = a.get("statcd") or ""
        sold_out = statcd == STATCD_SOLDOUT

        stock: Optional[int] = None
        m = NEAR_SOLDOUT_PATTERN.search(li_text)
        if m:
            try:
                stock = int(m.group(1))
            except ValueError:
                stock = None

        optcd = a.get("optcd") or ""
        name = f"{optcd}mm"
        # V7: ``filter(s => s.name)`` — optcd 가 비면 'mm' 만 남으므로 optcd 빈 케이스 제외
        if not optcd:
            continue
        out.append({"name": name, "soldOut": sold_out, "stock": stock})
    return out


class SsfCrawler(AbstractCrawler):
    """SSF샵 단품 크롤러 (V7 ``ssfParseProduct`` Python port).

    SSF 의 단품 URL 패턴: ``https://www.ssfshop.com/{BRAND}/{GOODSCD}/good``
    (컬러별로 별도 GOODSCD — V7 도 ``colors = [{currentColor}]`` 단일 컬러 처리)
    """

    source_name = "ssf"

    def __init__(self, timeout: int = DEFAULT_TIMEOUT):
        self.timeout = timeout

    def _fetch_html(self, product_url: str) -> str:
        resp = cffi_requests.get(
            product_url,
            impersonate=IMPERSONATE,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.text

    def fetch(self, product_url: str) -> CrawlResult:
        # 페이지에서 같은 모델의 다른 색상 GRG 코드 자동 발견 → 4 URL 모두 fetch
        try:
            base_html = self._fetch_html(product_url)
            import re
            grg_codes = set(re.findall(r'/LEMOUTON/(GRG\d+)/', base_html))
            if len(grg_codes) > 1:
                # 다중 색상 — 모든 GRG 페이지 fetch + 옵션 통합
                merged_options = []
                product_name_first = None
                brand_first = ""
                for grg in sorted(grg_codes):
                    sub_url = f"https://www.ssfshop.com/LEMOUTON/{grg}/good"
                    try:
                        sub = self._fetch_one_page(sub_url)
                        if not product_name_first:
                            product_name_first = sub.product_name_raw
                            brand_first = sub.brand
                        merged_options.extend(sub.options)
                    except Exception as e:
                        import logging as _lg
                        _lg.getLogger(__name__).warning("[SSF] %s fetch 실패: %s", grg, e)
                if merged_options:
                    return CrawlResult(
                        source=self.source_name,
                        product_url=product_url,
                        product_name_raw=product_name_first or "",
                        options=merged_options,
                        brand=brand_first,
                    )
        except Exception as _e:
            import logging as _lg
            _lg.getLogger(__name__).debug("[SSF] 다중 색상 자동 발견 실패: %s", _e)
        # 단일 페이지 fallback
        return self._fetch_one_page(product_url)

    def _fetch_one_page(self, product_url: str) -> CrawlResult:
        product_id = _extract_product_id(product_url)
        html = self._fetch_html(product_url)
        soup = BeautifulSoup(html, "lxml")

        # V7 ssfParseProduct 흐름 1:1
        product_name, current_color = _parse_name_and_color(soup, override_name=None)
        sale_price, _origin_price, _discount_rate = _parse_prices(soup)
        brand = _parse_brand(soup)
        discount_info = _parse_discount_info(soup)
        # 기프트포인트 (활성 시만 노출 / 변동값) — V7 에는 없는 항목
        gift_point_amount = _parse_gift_point(html)
        # 포인트 적립 (멤버십포인트, 상품별 변동값) — DB 0.5% 고정 폐기 (2026-05-15)
        point_rate, point_amount = _parse_point_rate(html, sale_price)

        # ★ 2026-05-14 — 매입가 단일 진실 원천(api_benefits.compute_breakdown) 으로 통합.
        #   크롤러는 sale_price 만 제공. 매입가는 매트릭스 UI 가 breakdown API 로 별도 호출.
        if sale_price <= 0:
            raise RuntimeError(f"[SSF] sale_price 추출 실패 ({sale_price}) — Fail-safe")

        # V7: 컬러는 항상 단일 (현재 페이지 컬러)
        sizes = _parse_sizes(soup)

        options: list[dict] = []

        # ★ 2026-05-13 잔여 #3a — SSF 자동 카드 (혜택가 단계, sale_price 미반영)
        _auto_card = {
            "issuer": "현대카드",
            "rate": 2.73,
            "label": "현대카드 2.73%",
            "included_in_sale_price": False,  # 캐시백 — sale_price 와 별개
        }

        def _build_option(option_id: str, color: str, size: str, stock: int) -> dict:
            opt = {
                "option_id": option_id,
                "color_text": color,
                "size_text": size,
                "price": sale_price,
                "sale_price": sale_price,
                "auto_card_discount": _auto_card,
                "stock": stock,
            }
            # 기프트포인트 — 노출된 상품만 (변동값, sale_price 와 별개)
            if gift_point_amount is not None and gift_point_amount > 0:
                opt["gift_point_amount"] = gift_point_amount
            # 포인트 적립 — 사이트 노출값(상품별 변동) / DB 0.5% 고정 polyfill 폐기
            if point_rate is not None and point_rate > 0:
                opt["point_rate"] = point_rate
            if point_amount is not None and point_amount > 0:
                opt["point_amount"] = point_amount
            return opt

        if sizes:
            # V7: colors.forEach × sizes.forEach
            for size in sizes:
                is_sold_out = bool(size["soldOut"])  # color.soldOut 는 항상 False
                # 사용자 정책 (2026-05-06):
                #   - statcd=SLDOUT (품절): 0
                #   - 품절임박 (N): N (실제 잔여 재고)
                #   - 표시 없음: 충분 재고 → 999 (placeholder)
                if is_sold_out:
                    stock_int = 0
                elif size["stock"] is not None:
                    stock_int = int(size["stock"])
                else:
                    stock_int = 999
                options.append(_build_option(
                    f"{product_id}|{current_color}|{size['name']}",
                    current_color,
                    size["name"],
                    stock_int,
                ))
        else:
            # V7 폴백: rows.length === 0 → 단일 행
            options.append(_build_option(
                f"{product_id}|{current_color}|",
                current_color,
                "",
                999,
            ))

        return CrawlResult(
            source=self.source_name,
            product_url=product_url,
            product_name_raw=product_name,
            options=options,
            brand=brand,
            discount_info=discount_info,
        )
