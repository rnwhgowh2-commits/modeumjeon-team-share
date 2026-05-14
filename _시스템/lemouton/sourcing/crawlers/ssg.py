"""SSG.COM (ssg.com / shinsegae.com) 단품 크롤러.

지원 도메인:
  - ``www.ssg.com``       — 본 크롤러가 우선 지원하는 도메인
  - ``m.ssg.com``         — canonical 자동 redirect (curl_cffi 가 따라감)
  - ``shinsegae.com``     — SSG 그룹 동일 인프라 (필요 시 추가)

URL 패턴:
  ``https://www.ssg.com/item/itemView.ssg?itemId={ITEM_ID}&siteNo=...&salestrNo=...``

크롤링 전략 (SSG 페이지 특성):
  - 핵심 데이터(상품명·브랜드·옵션·가격·재고)는 SSR HTML 내 ``<script>`` 인라인
    JS 의 ``uitemObj = {...}; uitemObjArr.push(uitemObj);`` 블록에 모두 포함된다.
    각 단품(uitemObj)는 ``uitemOptnNm1`` (색상), ``uitemOptnNm2`` (사이즈),
    ``sellprc`` (판매가/할인 후), ``bestAmt`` (최적가 / 즉시할인 적용가),
    ``usablInvQty`` (가용 재고) 를 직접 노출하므로 셀렉터보다 정규식 파싱이 견고하다.
  - sale_price 의 단일 진실 원천 우선순위 (사용자 명세 "할인가 = SSG MONEY 반영"):
      1순위 ``bestAmt``  — SSG 가 표시하는 "최적가" (상품 즉시할인 반영, 카드/쿠폰 제외)
      2순위 ``sellprc``  — bestAmt 가 0/누락이면 fallback
      cf. URL 1번 ``[비밀특가]`` 비회원 노출 sellprc=109900, bestAmt=109900 (동일)
          URL 2번 닥스 벨트 sellprc=126300, bestAmt=107355 (즉시할인 18,945 적용)
  - 카드혜택가 (있을 때만 노출 / 명세대로 표시 ✅ 적용 ❌):
      DOM 영역 ``div.mndtl_card_price`` > ``span.mndtl_price > em.ssg_price``
      → 정액 금액. 조건 텍스트는 ``span.mndtl_info_desc`` 에 "{최소금액}원 이상 결제 시 ..."
  - 카드혜택가 미노출 상품: 사용자 명세대로 **현대카드 2.73% fallback**
      → DB 시드 권장 (auto_card_discount dict 로 옵션에 박지 않고 별도 키 유지).
  - SSG MONEY 5% 적립 등은 명세상 sale_price 에 이미 반영 → 별도 차감 X.

옵션 dict 표준 키 (base.CrawlResult.options):
  - option_id, color_text, size_text, price, sale_price, stock
  - card_benefit_price / card_benefit_condition (옵션이 모두 동일하므로 옵션마다 박음)

2026-05-14 신규.
"""
from __future__ import annotations

import html as html_lib
import logging
import re
from typing import Optional

from curl_cffi import requests as cffi_requests
from bs4 import BeautifulSoup

from .base import AbstractCrawler, CrawlResult


logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# 상수
# ─────────────────────────────────────────────────────────────
DEFAULT_TIMEOUT = 30
IMPERSONATE = "chrome120"  # 다른 사이트 크롤러와 동일 (T10/T11/T12)

# SSG 인라인 JS: ``uitemObj = {itemId:'...', uitemId:'...', ...};``
# 각 단품(옵션 1개) 1 블록. 첫 번째(uitemId='00000') = 대표단품(전체 합산용) → 제외.
UITEM_BLOCK_PATTERN = re.compile(
    r"uitemObj\s*=\s*\{itemId\s*:\s*'([^']*)'\s*,\s*uitemId\s*:\s*'([^']*)'(.*?)\};\s*uitemObjArr\.push",
    re.DOTALL,
)

# uitemObj 블록 안에서 개별 필드 (single-quoted JS literal) 를 뽑는 정규식 모음.
#   uitemOptnNm1:'블랙(블랙아웃솔)', uitemOptnNm2:'225mm',
#   sellprc:parseInt('109900', 10) || 0,
#   bestAmt:'107355',
#   usablInvQty:'5',
def _build_field_re(name: str) -> re.Pattern[str]:
    # uitemOptnNm1 / usablInvQty / bestAmt 등 단순 single-quoted
    return re.compile(rf"{re.escape(name)}\s*:\s*'([^']*)'")


FIELD_OPTN1_RE = _build_field_re("uitemOptnNm1")
FIELD_OPTN2_RE = _build_field_re("uitemOptnNm2")
FIELD_OPTN_TYPE1_RE = _build_field_re("uitemOptnTypeNm1")
FIELD_OPTN_TYPE2_RE = _build_field_re("uitemOptnTypeNm2")
FIELD_USABL_INV_RE = _build_field_re("usablInvQty")
FIELD_BEST_AMT_RE = _build_field_re("bestAmt")
# sellprc 는 parseInt('NNNNN', 10) 형식
FIELD_SELLPRC_RE = re.compile(r"sellprc\s*:\s*parseInt\(\s*'([^']*)'")

# resultItemObj.itemNm / brandNm / brandId — 페이지 헤더 메타.
RESULT_ITEM_NM_RE = re.compile(r"itemNm\s*:\s*'((?:\\'|[^'])*)'")
RESULT_BRAND_NM_RE = re.compile(r"brandNm\s*:\s*'((?:\\'|[^'])*)'")

# itemId 추출 (URL fallback)
ITEM_ID_FROM_URL_RE = re.compile(r"[?&]itemId=([0-9]+)")

# 카드혜택가 — DOM 셀렉터로 추출.
#   <span class="mndtl_price"><em class="ssg_price">98,767</em> ...</span>
# 조건 텍스트: <span class="mndtl_info_desc">5만원 이상 결제 시 98,767원</span>


def _to_int(s: str | None) -> int:
    """콤마/공백/단위 제거 후 정수. 실패 시 0."""
    if not s:
        return 0
    digits = re.sub(r"[^0-9]", "", s)
    if not digits:
        return 0
    try:
        return int(digits)
    except ValueError:
        return 0


def _unescape(text: str) -> str:
    """JS string literal 안의 HTML entity(`&amp;` 등) + JS escape(`\\'`) 정리."""
    if not text:
        return ""
    # 1) JS escaped quote
    text = text.replace("\\'", "'").replace('\\"', '"').replace("\\\\", "\\")
    # 2) HTML entity (uitemNm 등이 `&amp;` 로 박혀 있음)
    text = html_lib.unescape(text)
    return text.strip()


def _extract_item_id(product_url: str, html: str) -> str:
    """itemId — 1순위 URL 파라미터, 2순위 페이지 hidden input."""
    m = ITEM_ID_FROM_URL_RE.search(product_url)
    if m:
        return m.group(1)
    # fallback: <input id="itemId" name="itemId" value="..." />
    m2 = re.search(r'id="itemId"[^>]*value="([0-9]+)"', html)
    if m2:
        return m2.group(1)
    return ""


def _extract_product_name(html: str, soup: BeautifulSoup) -> str:
    """상품명: ``span.cdtl_info_tit_txt`` (DOM) 우선, fallback 으로 인라인 ``itemNm``."""
    el = soup.select_one("span.cdtl_info_tit_txt")
    if el:
        text = el.get_text(strip=True)
        if text:
            return text
    m = RESULT_ITEM_NM_RE.search(html)
    if m:
        return _unescape(m.group(1))
    return ""


def _extract_brand(html: str, soup: BeautifulSoup) -> str:
    """브랜드: ``a.cdtl_info_tit_link`` 텍스트 → 인라인 ``brandNm`` fallback."""
    el = soup.select_one("a.cdtl_info_tit_link")
    if el:
        text = el.get_text(strip=True)
        if text:
            return text
    m = RESULT_BRAND_NM_RE.search(html)
    if m:
        return _unescape(m.group(1))
    return ""


def _parse_card_benefit(soup: BeautifulSoup) -> tuple[Optional[int], str]:
    """카드혜택가 + 조건 텍스트 추출.

    HTML 구조 (URL 2번 닥스 벨트 예시):
        <div class="mndtl_card_price">
            <dl class="mndtl_dl mndtl_toggle">
                <dt class="mndtl_dl_tit">카드혜택가</dt>
                <dd ...>
                    <button ...>
                        <span class="mndtl_price">
                            <em class="ssg_price">98,767</em> <span class="ssg_tx">원</span>
                        </span>
                    </button>
                    <div class="mndtl_card_cont">
                        ... 각 카드사별 dl.mndtl_card_info_dl ...
                          <dd>
                            <span class="mndtl_info_desc">5만원 이상 결제 시 98,767원</span>
                          </dd>
                    </div>
                </dd>
            </dl>
        </div>

    Returns:
        (정액 카드혜택가 정수, 조건 텍스트). 미노출이면 (None, "").
    """
    wrap = soup.select_one("div.mndtl_card_price")
    if not wrap:
        return None, ""
    price_el = wrap.select_one("span.mndtl_price em.ssg_price")
    if not price_el:
        return None, ""
    price = _to_int(price_el.get_text())
    if price <= 0:
        return None, ""
    # 조건 텍스트: 카드사별 행 중 첫 번째 mndtl_info_desc
    cond_el = wrap.select_one("span.mndtl_info_desc")
    cond_text = cond_el.get_text(" ", strip=True) if cond_el else ""
    # 줄바꿈/탭 정리
    cond_text = re.sub(r"\s+", " ", cond_text).strip()
    return price, cond_text


def _parse_uitem_options(
    html: str,
    item_id_from_url: str,
) -> list[dict]:
    """SSG 인라인 JS ``uitemObj`` 블록을 모두 파싱.

    - uitemId='00000' (대표단품, 옵션명 없음) 은 건너뜀.
      단, 단일 옵션 상품(uitemObj 1개만)은 00000 을 사용.
    - sale_price: bestAmt 우선, 0 이면 sellprc.
    - stock: usablInvQty (정수, '0' 이면 품절).

    Returns:
        옵션 dict 리스트. CrawlResult.options 그대로 사용 가능 (price/sale_price/stock).
    """
    blocks = list(UITEM_BLOCK_PATTERN.finditer(html))
    if not blocks:
        return []

    # 대표단품(00000) 외 일반 단품이 있는지 확인
    real_blocks = [b for b in blocks if b.group(2) != "00000"]
    use_blocks = real_blocks if real_blocks else blocks  # 옵션 없는 상품 → 00000 1개

    out: list[dict] = []
    for m in use_blocks:
        block_item_id = m.group(1)
        uitem_id = m.group(2)
        body = m.group(3)

        optn1 = _unescape(FIELD_OPTN1_RE.search(body).group(1)) if FIELD_OPTN1_RE.search(body) else ""
        optn2 = _unescape(FIELD_OPTN2_RE.search(body).group(1)) if FIELD_OPTN2_RE.search(body) else ""
        type1_m = FIELD_OPTN_TYPE1_RE.search(body)
        type2_m = FIELD_OPTN_TYPE2_RE.search(body)
        type1 = _unescape(type1_m.group(1)) if type1_m else ""
        type2 = _unescape(type2_m.group(1)) if type2_m else ""

        sellprc_m = FIELD_SELLPRC_RE.search(body)
        bestamt_m = FIELD_BEST_AMT_RE.search(body)
        inv_m = FIELD_USABL_INV_RE.search(body)

        sellprc = _to_int(sellprc_m.group(1)) if sellprc_m else 0
        best_amt = _to_int(bestamt_m.group(1)) if bestamt_m else 0
        stock = _to_int(inv_m.group(1)) if inv_m else 0

        # sale_price 단일 진실 원천: bestAmt 우선, 없으면 sellprc
        sale_price = best_amt if best_amt > 0 else sellprc
        if sale_price <= 0:
            # 가격 0 은 비정상 — 옵션에서 제외 (전체 fail 은 상위에서 처리)
            continue

        # type1/type2 가 '색상'/'사이즈' 인 일반 케이스만 의미 부여.
        # 그 외는 type1 텍스트 자체를 color_text 칸에 넣음 (UI 가 그냥 보여줌).
        color_text = optn1 if (type1 == "색상" or not type1) else f"{type1}:{optn1}"
        size_text = optn2 if (type2 == "사이즈" or not type2) else (f"{type2}:{optn2}" if optn2 else "")

        option_id = f"{block_item_id or item_id_from_url}|{uitem_id}"

        out.append({
            "option_id": option_id,
            "color_text": color_text,
            "size_text": size_text,
            "price": sale_price,
            "sale_price": sale_price,
            "stock": stock,
        })
    return out


class SsgCrawler(AbstractCrawler):
    """SSG.COM 단품 크롤러.

    추출 항목:
      - 상품명 / 브랜드
      - 옵션별 sale_price (=bestAmt), 색상/사이즈, 재고
      - 카드혜택가 (있는 경우 정액 + 조건 텍스트) → 모든 옵션에 동일하게 첨부

    Fallback 룰 (사용자 명세):
      - 카드혜택가 미노출 → 현대카드 2.73% (DB source_benefit_templates 에 별도 시드 권장)
      - 카드혜택가 노출 + 조건 미충족 → 표시 ✅ / 적용 ❌ (옵션 dict 에 정보만 박음)
    """

    source_name = "ssg"

    def __init__(self, timeout: int = DEFAULT_TIMEOUT):
        self.timeout = timeout

    def _fetch_html(self, product_url: str) -> str:
        resp = cffi_requests.get(
            product_url,
            impersonate=IMPERSONATE,
            timeout=self.timeout,
            headers={
                "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        )
        resp.raise_for_status()
        return resp.text

    def fetch(self, product_url: str) -> CrawlResult:
        html = self._fetch_html(product_url)
        soup = BeautifulSoup(html, "lxml")

        item_id = _extract_item_id(product_url, html)
        product_name = _extract_product_name(html, soup)
        brand = _extract_brand(html, soup)

        # 카드혜택가 (전 옵션 공통)
        card_price, card_condition = _parse_card_benefit(soup)

        # 옵션 파싱
        options = _parse_uitem_options(html, item_id)

        if not options:
            raise RuntimeError(
                f"[SSG] 옵션 추출 실패 — itemId={item_id} url={product_url}"
            )

        # 카드혜택가 정보를 모든 옵션에 첨부.
        # 명세: 조건 미충족이어도 표시 ✅ — 옵션에 박아두면 UI 가 표시 결정.
        if card_price is not None:
            for opt in options:
                opt["card_benefit_price"] = card_price
                if card_condition:
                    opt["card_benefit_condition"] = card_condition

        # discount_info — 카드혜택가 노출 시 텍스트 요약
        discount_info = ""
        if card_price is not None:
            discount_info = f"카드혜택가 {card_price:,}원"
            if card_condition:
                discount_info += f" ({card_condition})"

        return CrawlResult(
            source=self.source_name,
            product_url=product_url,
            product_name_raw=product_name,
            options=options,
            brand=brand,
            discount_info=discount_info,
        )
