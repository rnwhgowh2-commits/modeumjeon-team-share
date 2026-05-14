"""롯데홈쇼핑 / 롯데IMALL / 롯데ON 단품 크롤러.

V7 (Chrome extension) 의 롯데 크롤링 로직을 Python 으로 1:1 포팅 + 롯데ON 확장.

지원 도메인:
  - ``www.lottehomeshopping.com`` / ``m.lottehomeshopping.com`` (V7 호환, SSR HTML)
  - ``www.lotteimall.com``                                       (V7 호환, SSR HTML)
  - ``www.lotteon.com``                                          (★ 2026-05-14 신규 — Playwright + pbf API)

롯데ON 분기 (2026-05-14):
  - lotteon.com 은 Vue SPA. SSR HTML 26KB 에는 schema.org JSON-LD (정가 only) 만 노출.
  - 실제 가격·옵션·혜택은 ``pbf.lotteon.com`` API 응답으로 fetch 됨:
      · ``/product/v2/detail/search/base/sitm/{sitmNo}``     — 기본 정보, 옵션 메타
      · ``/product/v2/detail/option/mapping/...``            — 옵션 mapping (색상·사이즈·재고)
      · ``/product/v2/extlmsa/promotion/favorBox/benefits``  — ★ 쿠폰별 할인 그룹 (사용자 명세 매칭)
      · ``/product/v2/extlmsa/promotion/qtyChangeFavorInfoList`` — 최종 적용가
  - ``favorBox/benefits.discountGroups[].discountApplyPromotionList[]`` 에서 쿠폰별 분리 추출:
      groupId = IMMD (스토어즉시할인) / IMMD_AND_PRODUCT_COUPON (즉시+상품쿠폰) /
                STORE_COUPON (스토어쿠폰) / ORDER (카드즉시할인/장바구니쿠폰 — 사용자 명세)
      각 항목: dcRt (%) + dcAmt (원) + dispTitle/dispName + mainFlag (조건 비트) +
              minPdAmt/maxPdAmt (주문금액 조건)
  - 사용자 명세: 카드즉시할인/장바구니쿠폰 (% 자동 X, 크롤링 O)
      → discountGroups 중 title == "카드즉시할인/장바구니쿠폰" (groupId=ORDER, prKndCd=CRD_IMMD)
        을 분리 추출 + discount_info 텍스트에 반영.

V7 원본 위치: ``크롤러_V7_쿠팡 반영/background/background.js``
  - ``crawlLotte(url, productName)`` — 탭 오픈 → ``lotteParseProduct`` 실행
  - ``lotteParseProduct(productUrl, overrideName)`` — DOM 파싱 (1224~1313행)
  - URL 라우팅 (895행): ``/lottehomeshopping\\.com|lotteimall\\.com/.test(url)``

V7 흐름 한국어 요약 (변경 금지):
  1. 상품명 우선순위:
       overrideName → ``div.title`` → ``span.ir_name`` 첫 번째 (단, length<80
       AND 텍스트가 ``[`` 로 시작 안 함) → ``document.title.split('|')[0]``
  2. 브랜드: ``div.name`` (없으면 '롯데홈쇼핑')
  3. 가격:
       - salePrice  : ``.final span.num`` 텍스트 → 숫자만
       - maxPrice   : ``.price > span.num`` 텍스트 → 숫자만 (없으면 salePrice)
       - originPrice: ``span.num`` 중 부모 className 에 'ir_price' 포함된 첫 번째
                      (없으면 maxPrice)
       - discountRate: originPrice > maxPrice AND maxPrice > 0 →
                       round((1 - maxPrice/originPrice) * 100). 그 외 0.
       - discountInfo: ``.max_discount_list`` 텍스트, 줄바꿈을 ' / ' 로
  4. productId: ``new URLSearchParams(url.split('?')[1]).get('goods_no')``
  5. 옵션:
       - optLists = ``div.inp_option.inpOptList`` 전체
       - colors = parseOptList(optLists[0]) (색상)
       - sizes  = parseOptList(optLists[1]) (사이즈)
       - parseOptList(el): el 안의 ``p.txt_option`` innerText. 단,
         정규식 ``/^(색상|사이즈)\\s*선택$/`` 매칭 텍스트 (헤더) 는 제외.
       - colors / sizes 가 비면 ``[{name:'',soldOut:false}]`` 단일 항목.
  6. 품절 판정:
       - soldOutColors = soldOutSizes = ``div.layer_option li.soldout p.txt_option``
         의 텍스트 집합 (V7 는 색상/사이즈 모두 같은 셀렉터 — 두 set 동일).
       - color.soldOut = soldOutColors.has(color.name)
       - size.soldOut  = soldOutSizes.has(size.name)
  7. 행 생성: colors × sizes 데카르트 곱.
       - isSoldOut = color.soldOut OR size.soldOut
       - option1 = color.name || productName  (V7: 색상 빈 문자열일 때만 productName 폴백)
       - option2 = size.name
       - originalPrice = originPrice || '-'
       - price         = maxPrice    || '-'
       - stockStatus   = '품절' / '재고있음'
  8. rows.length === 0 → 단일 폴백 행 (option1=productName, option2='', salePrice).

Python 환경 한계 보강 (V7 의도 보존, 셀렉터 변경 없음):
  - V7 는 Chrome 탭에서 JS 렌더 후 DOM 을 읽지만, 롯데홈쇼핑·IMALL 의 핵심
    옵션·가격 정보는 raw HTML 에 SSR 로 포함되어 있다 (V7 가 ``sleep(600)``
    이후 DOM 만 보면 충분한 것과 동일 가정). ``curl_cffi`` chrome120
    impersonate 로 raw HTML 을 받아 BeautifulSoup 으로 동일 셀렉터를 적용.
"""
from __future__ import annotations

import json
import re
from typing import Optional
from urllib.parse import parse_qs, urlparse

from curl_cffi import requests as cffi_requests
from bs4 import BeautifulSoup, Tag

from .base import AbstractCrawler, CrawlResult


# dataBenefit JS 변수: 페이지 인라인 JSON. commonDiscountObj.benefitPrc 가
# "롯데홈쇼핑 최대할인가" (카드 청구할인 포함). 예: "120,320".
DATA_BENEFIT_PATTERN = re.compile(r"dataBenefit\s*=\s*\n?\s*(\{.+?\});", re.DOTALL)

# em.txt_em 텍스트 예시: "120,320원 (국민카드 5%)"
#   → 첫 그룹 = 카드사명 (한글), 두 번째 그룹 = 할인율 정수.
CARD_LABEL_PATTERN = re.compile(r"\(([가-힣A-Za-z]+카드)\s*(\d+(?:\.\d+)?)\s*%\)")


# ─────────────────────────────────────────────────────────────
# V7 동등 상수
# ─────────────────────────────────────────────────────────────
DEFAULT_TIMEOUT = 30
IMPERSONATE = "chrome120"  # T10 르무통 / T11 무신사 / T12 SSF 와 동일

# V7: ``filter(t => t && t.length < 80 && !/^\[/.test(t))``
IR_NAME_MAX_LEN = 80

# V7: ``filter(t => t && !/^(색상|사이즈)\s*선택$/.test(t))``
OPT_HEADER_PATTERN = re.compile(r"^(색상|사이즈)\s*선택$")


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
    """V7: ``new URLSearchParams(productUrl.split('?')[1]).get('goods_no') || ''``."""
    try:
        qs = urlparse(product_url).query
    except Exception:
        return ""
    if not qs:
        return ""
    params = parse_qs(qs)
    values = params.get("goods_no")
    if not values:
        return ""
    return values[0] or ""


# ─────────────────────────────────────────────────────────────
# 상품명 / 브랜드
# ─────────────────────────────────────────────────────────────
def _parse_product_name(soup: BeautifulSoup, override_name: Optional[str]) -> str:
    """V7: overrideName → div.title → ir_name 첫 번째 (필터 통과) → document.title.

    V7 원본:
        const irNames = [...document.querySelectorAll('span.ir_name')]
            .map(el => el.innerText?.trim())
            .filter(t => t && t.length < 80 && !/^\\[/.test(t));
        const productName = overrideName ||
            document.querySelector('div.title')?.innerText?.trim() ||
            irNames[0] ||
            document.title.split('|')[0].trim();
    """
    if override_name:
        return override_name

    title_el = soup.select_one("div.title")
    if title_el:
        t = title_el.get_text(strip=True)
        if t:
            return t

    for el in soup.select("span.ir_name"):
        t = el.get_text(strip=True)
        if not t:
            continue
        if len(t) >= IR_NAME_MAX_LEN:
            continue
        if t.startswith("["):
            continue
        return t

    # 최종 폴백: document.title.split('|')[0].trim()
    head_title = soup.find("title")
    if head_title:
        raw = head_title.get_text(strip=True)
        if raw:
            return raw.split("|")[0].strip()
    return ""


def _parse_brand(soup: BeautifulSoup) -> str:
    """V7: ``div.name`` (없으면 '롯데홈쇼핑')."""
    el = soup.select_one("div.name")
    if el:
        t = el.get_text(strip=True)
        if t:
            return t
    return "롯데홈쇼핑"


# ─────────────────────────────────────────────────────────────
# 가격
# ─────────────────────────────────────────────────────────────
def _extract_auto_card_discount(html: str, soup: BeautifulSoup) -> Optional[dict]:
    """롯데 자동 적용 카드 할인 정보 추출 (예: "국민카드 5% (6,330원)").

    출처 우선순위:
      1) dataBenefit JSON 의 ``fullDiscountObj.cardDiscountList[]`` —
         {"discountNm": "삼성카드 5% 청구할인", "discountCardNm": "삼성",
          "discountRt": 5, "discountAmount": "-6,330"}
         → 카드명·할인율·할인금액 셋 다 구조화돼 있어 최우선.
      2) ``em.txt_em`` 텍스트 — "120,320원 (국민카드 5%)" 패턴 (금액 없음)
      3) ``commonDiscountObj.benefitPrcLabelTxt`` (HTML 파싱 실패 시 폴백)

    Returns:
        {
            "issuer": "삼성카드",         # 카드사 풀네임
            "rate": 5.0,                  # %
            "amount": 6330,               # 청구할인 금액 (원)
            "label": "삼성카드 5%",
            "included_in_sale_price": True,
            "source": "dataBenefit.cardDiscountList",
        }
        또는 None.

    사용자 명세 매핑:
        카드 청구 할인 / %할인 / "X% (XXX원)" / 자동 ❌ / 크롤링 ✅
        → ``rate`` + ``amount`` 둘 다 박아서 UI 가 "5% (6,330원)" 텍스트
          생성 가능. 자동 적용 X (사용자 카드 보유 시만 적용) 라서
          ``included_in_sale_price=True`` 와 별개로 매트릭스 정책에서
          자동 ON 시키지 않음 (api_benefits 측 책임).
    """
    # 1) dataBenefit JSON 의 cardDiscountList — 가장 구조화된 출처
    db_meta = _parse_data_benefit(html)
    if db_meta is not None:
        data = db_meta.get("data") or {}
        full = data.get("fullDiscountObj") or {}
        card_list = full.get("cardDiscountList") or []
        # sumrDiscountObj.discountList 안에도 같은 카드 항목 있음 (백업 출처)
        if not card_list:
            sumr = data.get("sumrDiscountObj") or {}
            card_list = [
                it for it in (sumr.get("discountList") or [])
                if (it.get("discountNm") or "").endswith("청구할인")
                or "카드" in (it.get("discountNm") or "")
            ]
        if card_list:
            first = card_list[0]
            disc_nm = (first.get("discountNm") or "").strip()
            card_short = (first.get("discountCardNm") or "").strip()
            try:
                rate = float(first.get("discountRt") or 0)
            except (ValueError, TypeError):
                rate = 0.0
            amount = _to_int(first.get("discountAmount"))  # "-6,330" → 6330
            # 풀네임 (예: "삼성카드 5% 청구할인" → "삼성카드")
            issuer = ""
            mm = re.match(r"([가-힣A-Za-z]+카드)", disc_nm)
            if mm:
                issuer = mm.group(1)
            elif card_short:
                issuer = f"{card_short}카드"

            if rate > 0 and issuer:
                rate_text = f"{int(rate)}%" if rate == int(rate) else f"{rate:g}%"
                return {
                    "issuer": issuer,
                    "rate": rate,
                    "amount": amount,
                    "label": f"{issuer} {rate_text}",
                    "included_in_sale_price": True,
                    "source": "dataBenefit.cardDiscountList",
                }

    # 2) em.txt_em 텍스트 파싱 (구조화된 JSON 미존재 시 폴백)
    for em in soup.select("em.txt_em"):
        text = em.get_text(" ", strip=True)
        m = CARD_LABEL_PATTERN.search(text)
        if m:
            issuer = m.group(1)
            try:
                rate = float(m.group(2))
            except ValueError:
                continue
            return {
                "issuer": issuer,
                "rate": rate,
                "amount": 0,
                "label": f"{issuer} {m.group(2).rstrip('0').rstrip('.')}%" if "." in m.group(2) else f"{issuer} {int(rate)}%",
                "included_in_sale_price": True,
                "source": "em.txt_em",
            }

    # 3) commonDiscountObj.benefitPrcLabelTxt 폴백
    if db_meta is not None:
        cdo = (db_meta.get("data") or {}).get("commonDiscountObj") or {}
        label = (cdo.get("benefitPrcLabelTxt") or "").strip()
        if label:
            inner = CARD_LABEL_PATTERN.search(f"({label})")
            if inner:
                issuer = inner.group(1)
                try:
                    rate = float(inner.group(2))
                except ValueError:
                    rate = 0.0
                return {
                    "issuer": issuer,
                    "rate": rate,
                    "amount": 0,
                    "label": label,
                    "included_in_sale_price": True,
                    "source": "commonDiscountObj.benefitPrcLabelTxt",
                }

    return None


def _parse_data_benefit(html: str) -> Optional[dict]:
    """``dataBenefit`` JSON 페이로드 한 번만 파싱 + 캐싱 없음 (순수 helper)."""
    m = DATA_BENEFIT_PATTERN.search(html)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except (json.JSONDecodeError, ValueError):
        return None


def _extract_point_rewards(html: str) -> Optional[dict]:
    """롯데 구매 적립혜택 (구매적립 L.POINT) 추출.

    출처: ``dataBenefit.fullDiscountObj.lPointObj``
        - ``nMbrPoint``: 일반회원 구매적립 L.POINT (예: "+126P")
        - ``lMbrPoint``: L.CLUB(유료) 회원 구매적립 L.POINT (예: "+633P")
        - ``pointLabelTxt``: "구매적립 L.POINT" (라벨)

    사용자 명세 매핑:
        구매 적립혜택 / %적립금 / 0.5% (또는 사이트 표기) / 자동 ❌ / 크롤링 ✅
        → L.CLUB 회원 적립률이 통상 0.5% (사용자 명세) 와 일치.
          일반회원 0.1% 와 분리 노출.
        리뷰 적립은 명세상 **제외** — gdasLabelTxt / nMbrSaveamt / lMbrSaveamt
        는 무시.

    Returns:
        {
            "label": "구매적립 L.POINT",
            "default_point": 126,           # 일반회원 적립 P
            "club_point": 633,              # L.CLUB 회원 적립 P (없으면 0)
            "base_price": 126650,           # 적립률 계산용 base
            "default_rate": 0.10,           # % (소수점)
            "club_rate": 0.50,              # % (소수점)
            "source": "dataBenefit.lPointObj",
        } 또는 None.
    """
    db_meta = _parse_data_benefit(html)
    if db_meta is None:
        return None
    data = db_meta.get("data") or {}
    full = data.get("fullDiscountObj") or {}
    lp = full.get("lPointObj") or {}
    if not lp:
        return None

    default_p = _to_int(lp.get("nMbrPoint"))
    club_p = _to_int(lp.get("lMbrPoint"))
    label = (lp.get("pointLabelTxt") or "구매적립 L.POINT").strip()

    if default_p <= 0 and club_p <= 0:
        return None

    # 적립률 계산용 base = max_price (commonDiscountObj.benefitPrc 가 더 정확)
    # 단, benefitPrc 는 카드할인 포함가 → 적립률 base 로 부적절. 정가(ir_price)
    # 도 dataBenefit 에는 직접 없음 → discountList 의 "쿠폰할인" amount 를
    # commonDiscountObj.benefitPrc 에 더해 역산하거나, 단순히 점수 노출만 한다.
    # 여기서는 점수 + 라벨만 노출 (호출자가 base_price 알고 있으면 직접 계산).
    return {
        "label": label,
        "default_point": default_p,
        "club_point": club_p,
        "source": "dataBenefit.lPointObj",
    }


def _extract_max_price_from_databenefit(html: str) -> int:
    """dataBenefit JSON 의 commonDiscountObj.benefitPrc (예: "120,320") → int.

    페이지에 노출된 "롯데홈쇼핑 최대할인가" 와 1:1 일치 (카드 청구할인 포함).
    실패 시 0 (호출자가 다른 셀렉터로 폴백).
    """
    meta = _parse_data_benefit(html)
    if not meta:
        return 0
    cdo = (meta.get("data") or {}).get("commonDiscountObj") or {}
    return _to_int(cdo.get("benefitPrc"))


def _parse_prices(soup: BeautifulSoup, html: str = "") -> tuple[int, int, int, int]:
    """롯데홈쇼핑 / 롯데IMALL 가격 파싱.

    ★ 2026-05-13 수정 (사용자 확정 정책):
      "할인가 (크롤링 기준)" = 롯데홈쇼핑 최대할인가 (카드 청구할인 포함).
      예: 정가 149,000 → 15% 할인가 126,650 → **최대할인가 120,320** (국민카드 5% 적용).

    추출 우선순위 (max_price 기준):
      1) dataBenefit JSON 의 commonDiscountObj.benefitPrc — 페이지 표시와 1:1 일치
      2) (폴백) V7 셀렉터 ``.price > span.num`` — 15% 할인가 (카드 미적용)
      3) (최후 폴백) ``.final span.num`` — salePrice 동의어

    Returns: (sale_price, max_price, origin_price, discount_rate)
        - sale_price : ``.final span.num`` (V7 호환, 정보용)
        - max_price  : 사용자 정책의 sale_price (= 최대할인가, 정책 적용 base)
        - origin_price: 정가
    """
    # V7 호환 (정보용)
    final_el = soup.select_one(".final span.num")
    sale_price = _to_int(final_el.get_text() if final_el else "")

    # ★ 1순위: dataBenefit JSON benefitPrc (정확한 최대할인가)
    max_price = _extract_max_price_from_databenefit(html) if html else 0

    # 2순위: V7 셀렉터 ``.price > span.num``
    if max_price == 0:
        for price_el in soup.select(".price"):
            for child in price_el.find_all("span", recursive=False):
                if "num" in (child.get("class") or []):
                    max_price = _to_int(child.get_text())
                    break
            if max_price:
                break

    # 3순위: sale_price (.final span.num) 폴백
    if max_price == 0:
        max_price = sale_price

    # 정가
    origin_price = 0
    for span in soup.select("span.num"):
        parent = span.parent
        if not isinstance(parent, Tag):
            continue
        parent_classes = parent.get("class") or []
        joined = " ".join(parent_classes)
        if "ir_price" in joined:
            origin_price = _to_int(span.get_text())
            break
    if origin_price == 0:
        origin_price = max_price

    if origin_price > max_price and max_price > 0:
        discount_rate = round((1 - max_price / origin_price) * 100)
    else:
        discount_rate = 0

    return sale_price, max_price, origin_price, discount_rate


# ─────────────────────────────────────────────────────────────
# 옵션
# ─────────────────────────────────────────────────────────────
def _parse_opt_list(opt_list_el: Optional[Tag]) -> list[str]:
    """V7: ``el.querySelectorAll('p.txt_option')`` → 텍스트, 헤더 제외.

    V7 원본:
        const parseOptList = (el) => {
            if (!el) return [];
            return [...el.querySelectorAll('p.txt_option')]
                .map(p => p.innerText?.trim())
                .filter(t => t && !/^(색상|사이즈)\\s*선택$/.test(t));
        };
    """
    if opt_list_el is None:
        return []
    out: list[str] = []
    for p in opt_list_el.select("p.txt_option"):
        t = p.get_text(strip=True)
        if not t:
            continue
        if OPT_HEADER_PATTERN.match(t):
            continue
        out.append(t)
    return out


def _parse_soldout_names(soup: BeautifulSoup) -> set[str]:
    """V7: ``div.layer_option li.soldout p.txt_option`` 텍스트 집합."""
    out: set[str] = set()
    for p in soup.select("div.layer_option li.soldout p.txt_option"):
        t = p.get_text(strip=True)
        if t:
            out.add(t)
    return out


# ─────────────────────────────────────────────────────────────
# 롯데ON (lotteon.com) — Playwright + pbf.lotteon.com API
# ─────────────────────────────────────────────────────────────
LOTTEON_API_PATHS = (
    "/product/v2/detail/search/base/sitm/",
    "/product/v2/detail/option/mapping/",
    "/product/v2/extlmsa/promotion/favorBox/benefits",
    "/product/v2/extlmsa/promotion/qtyChangeFavorInfoList",
    "/product/v2/extlmsa/promotion/additionFavorInfoList",
)

# 롯데ON: 사용자 명세상 "카드즉시할인/장바구니쿠폰" 그룹 식별 키
#   - discountGroups[].title == "카드즉시할인/장바구니쿠폰"  →  groupId=ORDER
#   - prKndCd ∈ {CRD_IMMD, CPN_BSK_CPN}                     →  카드즉시할인 / 장바구니쿠폰
LOTTEON_CARD_COUPON_TITLE = "카드즉시할인/장바구니쿠폰"
LOTTEON_CRD_KINDS = {"CRD_IMMD", "CPN_BSK_CPN"}


def _is_lotteon(url: str) -> bool:
    """URL 이 롯데ON (lotteon.com) 인지 판별."""
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return False
    return "lotteon.com" in host


def _extract_lotteon_sitm_no(url: str) -> str:
    """롯데ON URL 에서 sitmNo 추출. 없으면 path 의 pdNo 사용.

    예:
      ?sitmNo=LO2158462914_2158462915&... → 'LO2158462914_2158462915'
      /p/product/PD52903977 (sitmNo 없음) → 'PD52903977'
    """
    try:
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        sitm = params.get("sitmNo")
        if sitm and sitm[0]:
            return sitm[0]
        # path: /p/product/{pdNo}
        m = re.search(r"/p/product/([A-Za-z0-9_]+)", parsed.path)
        if m:
            return m.group(1)
    except Exception:
        pass
    return ""


def _format_dc_amount(dc_type_cd: str | None, dc_rt, dc_amt) -> str:
    """할인 항목 → 사용자 명세 표기 "X% (XXX원)" / 정액일 때는 "XXX원" / 또는 X%."""
    try:
        rt = float(dc_rt) if dc_rt not in (None, "") else 0.0
    except (ValueError, TypeError):
        rt = 0.0
    try:
        amt = int(dc_amt) if dc_amt not in (None, "") else 0
    except (ValueError, TypeError):
        amt = 0
    if rt > 0 and amt > 0:
        rt_text = f"{int(rt)}%" if rt == int(rt) else f"{rt:g}%"
        return f"{rt_text} ({amt:,}원)"
    if rt > 0:
        return f"{int(rt)}%" if rt == int(rt) else f"{rt:g}%"
    if amt > 0:
        return f"{amt:,}원"
    return ""


def _build_coupon_condition_text(promo: dict) -> str:
    """쿠폰 사용조건 텍스트 빌드. JSON 에 노출된 조건 필드 종합.

    노출 가능한 조건 (lotteon API):
      · ``mainFlag.isFirstBuy``    → 첫구매 한정
      · ``mainFlag.isStrJJim``     → 스토어찜 한정
      · ``mainFlag.isLpntMb``      → L포인트 회원 한정
      · ``mainFlag.isAppOnly``     → 앱 전용
      · ``mainFlag.isClub``        → 롯데클럽 한정
      · ``minPdAmt``               → 최소 주문금액 (없으면 None)
      · ``maxPdAmt``               → 최대 할인금액 cap
      · ``pyMnsDtl``               → 결제수단 제한 (카카오페이/L.PAY 등)
    """
    bits: list[str] = []
    flag = promo.get("mainFlag") or {}
    if isinstance(flag, dict):
        if flag.get("isFirstBuy"):
            bits.append("첫구매 한정")
        if flag.get("isStrJJim"):
            bits.append("스토어찜 한정")
        if flag.get("isLpntMb"):
            bits.append("L포인트 회원")
        if flag.get("isAppOnly"):
            bits.append("앱 전용")
        if flag.get("isClub"):
            bits.append("롯데클럽 회원")
        if flag.get("isRcvAgr"):
            bits.append("수신동의 필요")
    min_amt = promo.get("minPdAmt")
    if min_amt:
        try:
            v = int(min_amt)
            if v > 0:
                bits.append(f"{v:,}원 이상 주문")
        except (ValueError, TypeError):
            pass
    max_amt = promo.get("maxPdAmt")
    if max_amt:
        try:
            v = int(max_amt)
            if v > 0:
                bits.append(f"최대 {v:,}원 할인")
        except (ValueError, TypeError):
            pass
    # pyMnsDtl 은 결제수단 코드 (예: pyMnsCd=61=카카오페이) — raw 노출 X.
    # 사용자 표시 결제수단 정보는 dispTitle / dispName 에 이미 한글로 들어있음 (예: "카카오페이 머니").
    return " / ".join(bits)


def _fetch_lotteon_via_playwright(product_url: str, timeout_sec: int) -> dict:
    """Playwright 로 lotteon.com 페이지 렌더 + pbf.lotteon.com API 응답 캡처.

    Returns:
        {
            'base': dict | None,    # detail/search/base/sitm  →  data
            'option': dict | None,  # detail/option/mapping     →  data
            'favor': dict | None,   # promotion/favorBox/benefits →  data
            'qty': dict | None,     # promotion/qtyChangeFavorInfoList → data
            'addition': dict | None,# promotion/additionFavorInfoList  → data
        }
    """
    # 지연 import — Playwright 미설치 환경 (CI 등) 대비
    from playwright.sync_api import sync_playwright

    captured: dict[str, dict] = {}
    pmap = {
        "/product/v2/detail/search/base/sitm/": "base",
        "/product/v2/detail/option/mapping/": "option",
        "/product/v2/extlmsa/promotion/favorBox/benefits": "favor",
        "/product/v2/extlmsa/promotion/qtyChangeFavorInfoList": "qty",
        "/product/v2/extlmsa/promotion/additionFavorInfoList": "addition",
    }

    page_title_fallback = ""

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1440, "height": 900},
        )
        page = ctx.new_page()

        def on_response(resp):
            u = resp.url
            for path, key in pmap.items():
                if path in u:
                    try:
                        ct = (resp.headers.get("content-type") or "").lower()
                        if "json" not in ct:
                            return
                        body = resp.text()
                        obj = json.loads(body)
                        # API 표준 응답: {data: ...}
                        if isinstance(obj, dict):
                            captured[key] = obj.get("data") or {}
                    except (json.JSONDecodeError, ValueError, OSError):
                        pass
                    return

        page.on("response", on_response)
        try:
            page.goto(product_url, wait_until="networkidle", timeout=timeout_sec * 1000)
            # 일부 API (favorBox 등) 는 networkidle 후에도 호출됨 — 짧게 대기
            page.wait_for_timeout(2000)
            # 폴백: base API 누락 시 사용할 페이지 제목 (예: "[상품명] : 롯데ON")
            try:
                page_title_fallback = (page.title() or "").strip()
            except Exception:
                page_title_fallback = ""
        finally:
            browser.close()

    return {
        "base": captured.get("base") or {},
        "option": captured.get("option") or {},
        "favor": captured.get("favor") or {},
        "qty": captured.get("qty") or {},
        "addition": captured.get("addition") or {},
        "page_title": page_title_fallback,
    }


def _parse_lotteon_options(option_data: dict, base_data: dict) -> tuple[list[dict], list[dict]]:
    """롯데ON optionInfo → (colors, sizes) 리스트.

    각 항목: {"name": str, "soldOut": bool}.
    sold-out 판정: ``options[].disabled == True``.
    """
    info = (option_data.get("optionInfo") or base_data.get("optionInfo") or {})
    opt_list = info.get("optionList") or []

    def _parse_axis(idx: int, default_title: str) -> list[dict]:
        if idx >= len(opt_list):
            return []
        ol = opt_list[idx] or {}
        out: list[dict] = []
        for o in ol.get("options") or []:
            label = (o.get("label") or "").strip()
            if not label:
                continue
            out.append({
                "name": label,
                "soldOut": bool(o.get("disabled")),
            })
        return out

    # 첫번째 axis = 색상, 두번째 = 사이즈 (롯데ON optionList 순서)
    colors = _parse_axis(0, "색상")
    sizes = _parse_axis(1, "사이즈")
    return colors, sizes


def _parse_lotteon_benefits(favor_data: dict) -> tuple[list[dict], str]:
    """롯데ON ``favorBox/benefits.discountGroups`` → 쿠폰별 분리 추출.

    Returns:
        (coupons, discount_info_text)
        coupons: 쿠폰별 dict 리스트 (UI/breakdown 용)
            {
              group: str,           # groupId (IMMD / IMMD_AND_PRODUCT_COUPON / STORE_COUPON / ORDER 등)
              group_title: str,     # discountGroup.title (사용자 노출용, 예: "카드즉시할인/장바구니쿠폰")
              name: str,            # dispTitle 또는 dispName 또는 prNm
              kind: str,            # prKndCd (PRD_SLR/CPN_PRD_CPN/CRD_IMMD 등)
              type: str,            # prTypCd (PRD_DC/DC_CPN/CRD_PR 등)
              dc_type: str,         # dcTypCd (FX/FL — 정액 vs 정률)
              dc_rate: float,       # % (없으면 0)
              dc_amount: int,       # 원 (없으면 0)
              text: str,            # 사용자 표시 텍스트 "X% (XXX원)"
              condition: str,       # 사용조건 텍스트 (조건 충족 안 해도 표시)
              is_card_coupon: bool, # 사용자 명세 "카드즉시할인/장바구니쿠폰" 그룹 여부
              coupon_no: str,       # 다운로드 가능한 쿠폰 번호 (있으면)
            }
        discount_info_text: 모음전 UI 에서 보여줄 통합 텍스트
            예: "스토어 즉시할인 6% (8,940원) / 카드즉시할인-롯데카드 7%"
    """
    coupons: list[dict] = []
    text_parts: list[str] = []

    for dg in favor_data.get("discountGroups") or []:
        group_title = (dg.get("title") or "").strip()
        is_card_coupon_group = (group_title == LOTTEON_CARD_COUPON_TITLE)

        for promo in dg.get("discountApplyPromotionList") or []:
            group_id = promo.get("groupId") or ""
            pr_knd = promo.get("prKndCd") or ""
            pr_typ = promo.get("prTypCd") or ""
            dc_typ = promo.get("dcTypCd") or ""
            try:
                dc_rate = float(promo.get("dcRt") or 0)
            except (ValueError, TypeError):
                dc_rate = 0.0
            try:
                dc_amount = int(promo.get("dcAmt") or 0)
            except (ValueError, TypeError):
                dc_amount = 0
            disp_title = (promo.get("dispTitle") or "").strip()
            disp_name = (promo.get("dispName") or "").strip()
            pr_nm = (promo.get("prNm") or "").strip()
            # 사용자 표시명: dispTitle 우선, 없으면 dispName, 그래도 없으면 prNm
            name = disp_title or disp_name or pr_nm
            value_text = _format_dc_amount(dc_typ, dc_rate, dc_amount)
            condition = _build_coupon_condition_text(promo)
            coupon_info = promo.get("couponInfo") or {}
            coupon_no = (coupon_info.get("cpnNo") if isinstance(coupon_info, dict) else "") or ""

            # 사용자 명세상 "카드즉시할인/장바구니쿠폰" 판정
            is_card_coupon = (
                is_card_coupon_group
                or pr_knd in LOTTEON_CRD_KINDS
                or pr_typ == "CRD_PR"
            )

            coupons.append({
                "group": group_id,
                "group_title": group_title,
                "name": name,
                "kind": pr_knd,
                "type": pr_typ,
                "dc_type": dc_typ,
                "dc_rate": dc_rate,
                "dc_amount": dc_amount,
                "text": value_text,
                "condition": condition,
                "is_card_coupon": is_card_coupon,
                "coupon_no": coupon_no,
            })

            # discount_info 텍스트 빌드
            #   name 에 이미 % 표기가 포함된 경우 (예: "스토어 즉시할인 6%") value_text 중복 회피.
            #   → name 끝에 "{rate}%" 가 있으면 value_text 만 남기되 이름 prefix 는 % 제외.
            if name and value_text:
                name_norm = name.rstrip()
                rate_int_token = f"{int(dc_rate)}%" if dc_rate == int(dc_rate) and dc_rate > 0 else None
                if rate_int_token and name_norm.endswith(rate_int_token):
                    # "스토어 즉시할인 6%" → "스토어 즉시할인" 으로 trim
                    prefix = name_norm[: -len(rate_int_token)].rstrip()
                    seg = f"{prefix} {value_text}".strip() if prefix else value_text
                else:
                    seg = f"{name} {value_text}"
                if condition:
                    seg += f" [{condition}]"
                text_parts.append(seg)
            elif name:
                text_parts.append(name)

    return coupons, " / ".join(text_parts)


def _parse_lotteon_prices(base_data: dict, qty_data: dict) -> tuple[int, int, int]:
    """롯데ON 가격 추출.

    Returns: (sale_price, max_price, origin_price)
        - origin_price : ``priceInfo.slPrc`` (정가)
        - max_price    : ``qty.immdDcAplyTotAmt`` (즉시할인 적용가, 사용자 명세상 "할인가")
                         없으면 ``qty.orderDcAplyTotAmt`` (쿠폰까지 적용) 폴백
                         그것도 없으면 origin_price
        - sale_price   : max_price 와 동일 (CrawlResult 인터페이스 호환용)

    사용자 명세 "카드즉시할인/장바구니쿠폰" 은 _자동_ 적용이 아니라 _크롤링만_ 하는 항목
    → max_price 는 즉시할인 (스토어 즉시할인) 까지만 반영. 카드즉시할인은 미반영.
    """
    price_info = base_data.get("priceInfo") or {}
    try:
        origin = int(price_info.get("slPrc") or 0)
    except (ValueError, TypeError):
        origin = 0

    # qty_data 에서 즉시할인 적용가 우선
    try:
        immd_total = int(qty_data.get("immdDcAplyTotAmt") or 0)
    except (ValueError, TypeError):
        immd_total = 0
    try:
        order_total = int(qty_data.get("orderDcAplyTotAmt") or 0)
    except (ValueError, TypeError):
        order_total = 0

    if immd_total > 0:
        max_price = immd_total
    elif order_total > 0:
        max_price = order_total
    else:
        max_price = origin

    sale_price = max_price
    return sale_price, max_price, origin


def _fetch_lotteon(product_url: str, timeout_sec: int) -> CrawlResult:
    """롯데ON (lotteon.com) 단품 크롤링 — Playwright + pbf API 캡처."""
    bundle = _fetch_lotteon_via_playwright(product_url, timeout_sec)
    base_data = bundle["base"]
    option_data = bundle["option"]
    favor_data = bundle["favor"]
    qty_data = bundle["qty"]

    # 기본 정보
    basic = base_data.get("basicInfo") or {}
    product_name = (basic.get("spdNm") or basic.get("pdNm") or "").strip()
    if not product_name:
        # 폴백: 페이지 <title> ("[상품명] : 롯데ON" → "상품명")
        title_raw = (bundle.get("page_title") or "").strip()
        if title_raw:
            product_name = title_raw.split(" : 롯데ON")[0].split("|")[0].strip()
    product_id = basic.get("spdNo") or basic.get("pdNo") or _extract_lotteon_sitm_no(product_url)
    sitm_no = basic.get("itmNo") or _extract_lotteon_sitm_no(product_url)

    # 가격
    sale_price, max_price, _origin_price = _parse_lotteon_prices(base_data, qty_data)
    if max_price <= 0:
        raise RuntimeError(
            f"[lotteon] sale_price/max_price 추출 실패 — sitmNo={sitm_no}, "
            f"base.keys={list(base_data.keys())[:8]}, qty.keys={list(qty_data.keys())[:8]}"
        )

    # 쿠폰별 분리 추출 + discount_info 텍스트
    coupons, discount_info_text = _parse_lotteon_benefits(favor_data)
    auto_card_discount = None
    # 사용자 명세상 카드즉시할인은 자동 적용 X — auto_card_discount 는 None 유지
    # (UI 가 coupons 안의 is_card_coupon=True 항목을 별도 표시)

    # 옵션
    colors, sizes = _parse_lotteon_options(option_data, base_data)
    if not colors:
        colors = [{"name": "", "soldOut": False}]
    if not sizes:
        sizes = [{"name": "", "soldOut": False}]

    options: list[dict] = []
    for color in colors:
        for size in sizes:
            is_sold_out = bool(color["soldOut"] or size["soldOut"])
            color_text = color["name"] if color["name"] else product_name
            size_text = size["name"]
            stock_int = 0 if is_sold_out else 999
            options.append({
                "option_id": f"{product_id}|{color_text}|{size_text}",
                "color_text": color_text,
                "size_text": size_text,
                "price": max_price,
                "sale_price": max_price,
                "auto_card_discount": auto_card_discount,
                # ★ 2026-05-14 — 롯데ON 쿠폰별 분리 추출 결과
                #   UI 가 쿠폰 표시/매트릭스 계산에 사용
                "lotteon_coupons": coupons,
                "stock": stock_int,
            })

    return CrawlResult(
        source="lotte",
        product_url=product_url,
        product_name_raw=product_name,
        options=options,
        # 사용자 명세상 "표시 ✓ / 적용 ✗" 원칙 → discount_info 에 모든 쿠폰 텍스트 포함
        discount_info=discount_info_text,
    )


# ─────────────────────────────────────────────────────────────
# Crawler
# ─────────────────────────────────────────────────────────────
class LotteCrawler(AbstractCrawler):
    """롯데홈쇼핑 / 롯데IMALL 단품 크롤러 (V7 ``lotteParseProduct`` Python port).

    URL 패턴 예:
      - ``https://www.lotteimall.com/goods/viewGoodsDetail.lotte?goods_no=1234567890``
      - ``https://www.lottehomeshopping.com/p/product/{...}?goods_no=987...``
    """

    source_name = "lotte"

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
        # ★ 2026-05-14 — 도메인 라우팅:
        #   lotteon.com         → Playwright + pbf.lotteon.com API
        #   lottehomeshopping / lotteimall → 기존 V7 호환 SSR HTML 파싱
        if _is_lotteon(product_url):
            return _fetch_lotteon(product_url, self.timeout)

        product_id = _extract_product_id(product_url)
        # V7 는 빈 productId 도 허용 — 동일 동작 유지

        html = self._fetch_html(product_url)
        soup = BeautifulSoup(html, "lxml")

        # ── V7 lotteParseProduct 흐름 1:1 ────────────────────
        product_name = _parse_product_name(soup, override_name=None)
        _brand = _parse_brand(soup)  # V7 는 행에 brand 필드를 담지만, CrawlResult 에는 없음
        sale_price, max_price, _origin_price, _discount_rate = _parse_prices(soup, html)
        # ★ 2026-05-13: 사이트 자동 적용 카드 할인 (예: 국민카드 5%) 추출
        # ★ 2026-05-14: dataBenefit.cardDiscountList[] 기반 → 카드사·%·원 셋 다 박힘.
        auto_card_discount = _extract_auto_card_discount(html, soup)
        # ★ 2026-05-14: 구매 적립혜택 (구매적립 L.POINT) 추출. 리뷰 적립은 명세 제외.
        point_rewards = _extract_point_rewards(html)

        # ★ 2026-05-14 — 매입가 단일 진실 원천(api_benefits.compute_breakdown) 으로 통합.
        #   sale_price = "롯데홈쇼핑 최대할인가" (max_price 우선). 매입가는 매트릭스 UI 가 breakdown API 호출.
        base_for_policy = max_price if max_price > 0 else sale_price
        if base_for_policy <= 0:
            raise RuntimeError(f"[lotteimall] sale_price/max_price 추출 실패 ({sale_price}/{max_price}) — Fail-safe")

        # 옵션 파싱
        opt_lists = soup.select("div.inp_option.inpOptList")
        color_names = _parse_opt_list(opt_lists[0] if len(opt_lists) > 0 else None)
        size_names = _parse_opt_list(opt_lists[1] if len(opt_lists) > 1 else None)

        soldout_set = _parse_soldout_names(soup)

        # V7: colors / sizes 가 비면 단일 빈 항목
        if color_names:
            colors = [{"name": n, "soldOut": n in soldout_set} for n in color_names]
        else:
            colors = [{"name": "", "soldOut": False}]
        if size_names:
            sizes = [{"name": n, "soldOut": n in soldout_set} for n in size_names]
        else:
            sizes = [{"name": "", "soldOut": False}]

        options: list[dict] = []
        for color in colors:
            for size in sizes:
                is_sold_out = bool(color["soldOut"] or size["soldOut"])
                # V7: option1 = color.name || productName
                color_text = color["name"] if color["name"] else product_name
                size_text = size["name"]
                # 사용자 정책 (2026-05-06): 품절=0 / 충분 재고=999 (표시 없음)
                stock_int = 0 if is_sold_out else 999
                # CrawlResult.price: V7 는 maxPrice 사용 (옵션 표시 가격)
                # 단, maxPrice 가 0 일 수 있으므로 V7 의 ``maxPrice || '-'`` 분기는
                # 본 모듈에서는 0 그대로 유지 (CrawlResult 스키마는 int).
                options.append({
                    "option_id": f"{product_id}|{color_text}|{size_text}",
                    "color_text": color_text,
                    "size_text": size_text,
                    "price": base_for_policy,
                    "sale_price": base_for_policy,
                    # ★ 2026-05-13: 사이트 자동 적용 카드 할인 정보 (UI 표시용)
                    #   예: {"issuer": "삼성카드", "rate": 5.0, "amount": 6330,
                    #        "label": "삼성카드 5%", "included_in_sale_price": True}
                    "auto_card_discount": auto_card_discount,
                    # ★ 2026-05-14: 구매적립 L.POINT (일반/L.CLUB).
                    #   예: {"label": "구매적립 L.POINT", "default_point": 126,
                    #        "club_point": 633, "source": "dataBenefit.lPointObj"}
                    "point_rewards": point_rewards,
                    "stock": stock_int,
                })

        # V7: rows.length === 0 → 단일 폴백. 위 로직은 colors=[{빈}], sizes=[{빈}]
        # 으로도 1행을 만들기 때문에 별도 폴백 불필요. 그러나 V7 폴백은 salePrice
        # 를 쓰고, 위 행은 maxPrice 를 쓰므로 옵션 0 케이스에서는 V7 와 가격이
        # 다를 수 있다. V7 폴백 가격 의도 (salePrice) 를 보존하기 위해, 색상·
        # 사이즈 모두 비고 결과가 1행일 때 가격을 salePrice 로 교체.
        # 단일 폴백 행도 정책 적용된 가격 유지 (sale_price 로 덮지 않음)
        # (기존 V7 폴백 로직은 max_price 가 0 일 때 sale_price 로 보정했으나,
        #  현재 base_for_policy 가 이미 둘 중 양수 값을 사용하므로 불필요)

        # ★ 2026-05-14 — discount_info 텍스트 빌드 (UI 표시 요약, 정책 base 아님)
        #   사용자 명세 "카드 청구 할인 / 구매 적립혜택" 2개 항목 노출.
        #   매트릭스 정책·매입가 계산은 api_benefits.compute_breakdown 단일 진실 원천.
        info_parts: list[str] = []
        if auto_card_discount:
            rate = auto_card_discount.get("rate") or 0
            amt = auto_card_discount.get("amount") or 0
            issuer = auto_card_discount.get("issuer") or ""
            rate_text = f"{int(rate)}%" if rate == int(rate) else f"{rate:g}%"
            if amt > 0:
                info_parts.append(f"{issuer} 청구할인 {rate_text} ({amt:,}원)")
            else:
                info_parts.append(f"{issuer} 청구할인 {rate_text}")
        if point_rewards:
            label = point_rewards.get("label") or "구매적립 L.POINT"
            n_p = point_rewards.get("default_point") or 0
            l_p = point_rewards.get("club_point") or 0
            if l_p > 0 and n_p > 0:
                info_parts.append(f"{label} 일반 +{n_p:,}P / L.CLUB +{l_p:,}P")
            elif l_p > 0:
                info_parts.append(f"{label} +{l_p:,}P")
            elif n_p > 0:
                info_parts.append(f"{label} +{n_p:,}P")

        return CrawlResult(
            source=self.source_name,
            product_url=product_url,
            product_name_raw=product_name,
            options=options,
            discount_info=" / ".join(info_parts),
        )
