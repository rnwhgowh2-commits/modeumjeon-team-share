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

from .base import (
    AbstractCrawler, CrawlResult, build_category_path, build_image_urls,
    pick_img_src, sanitize_detail_html,
)


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


def _parse_category_path(soup: BeautifulSoup) -> str:
    """[2026-07-23 M3] 롯데아이몰 빵부스러기 → '대>중>소'.

    실화면 확인(www.lotteimall.com 상품 페이지, 2026-07-23) — 화면 표시
    「홈 › 패션슈즈 › 스니커즈/운동화 › 런닝화/워킹화」의 마크업::

        <div class="location">
          <a class="home">홈</a>
          <div class="his"><a class="one">패션슈즈</a>
            <div class="hislayer">…형제 카테고리 목록…</div></div>
          <div class="his"><a class="one">스니커즈/운동화</a> …</div>
          <div class="his"><a class="one">런닝화/워킹화</a> …</div>
        </div>

    ⚠️ 함정: 각 ``div.his`` 안의 ``div.hislayer`` 는 그 단계의 **형제 카테고리**
    드롭다운(여성브랜드의류·패션잡화 …)이라 경로가 아니다. SSG 와 같은 구조라
    같은 방어를 쓴다 — ``div.location`` 의 **직계** ``a.home`` 과
    ``div.his`` 의 **직계** ``a.one`` 만 읽는다.
    맨 앞 '홈'은 공통 조립기가 제외한다. 못 찾으면 빈 문자열(추측 금지).
    """
    loc = soup.select_one("div.location")
    if loc is None:
        return ""
    parts: list[str] = []
    for child in loc.find_all(recursive=False):
        if child.name == "a":
            parts.append(child.get_text(strip=True))
        elif child.name == "div" and "his" in (child.get("class") or []):
            a = child.find("a", recursive=False)
            if a is not None:
                parts.append(a.get_text(strip=True))
    return build_category_path(parts)


# ─────────────────────────────────────────────────────────────
# [2026-07-23 M4-4] 이미지·상세 (롯데아이몰)
# ─────────────────────────────────────────────────────────────
# 롯데아이몰 상품사진 CDN 은 한 장을 3가지 렌디션으로 낸다 — 실측(2026-07-23):
#     .../goods/79/86/79/2474798679_H{n}.jpg   (og:image 가 쓰는 판)
#     .../goods/79/86/79/2474798679_L{n}.jpg   (본문 큰 이미지 = 화면 대표)
#     .../goods/79/86/79/2474798679_S{n}.jpg   (썸네일 줄)
#   `{n}` 은 사진 번호(첫 장은 없음, 둘째부터 1·2·3…).
_LOTTEIMALL_THUMB_RE = re.compile(r"^(.*/goods/.*?)_S(\d*)(\.[A-Za-z]{3,4})$")
# `onerror` 로 갈아끼우는 '이미지 없음' 회색판. src 속성 자체가 이걸 가리키는 경우가 있어
#   대표이미지가 회색 네모로 등록되는 걸 막는다(공통 필터의 `noimage` 규칙엔 안 걸린다).
_LOTTEIMALL_NOIMG = "/goods/common/no_"


def _lotteimall_thumb_to_large(url: str) -> str:
    """썸네일(`_S…`) → 본문 큰 이미지(`_L…`). 패턴이 아니면 **그대로 둔다**.

    🔴 다른 소싱처에서는 이런 치환을 금지했다(르무통: `/small/` → `/big/` 은 404).
       여기서만 하는 이유 = **HEAD 로 실측했기 때문**이다(2026-07-23, 상품 5건 ·
       썸네일 17장 전수):

         · 썸네일이 있는 번호는 `_L{n}` 도 전부 200 (17/17, 실패 0)
         · 크기 비교 예: `_S`=6,845B / `_H`=27,331B / `_L`=67,446B
           → 마켓 대표이미지로 쓸 만한 건 `_L` 이다(썸네일은 너무 작다)

    ★ [2026-07-23 리뷰지적 M1] 안전한 진짜 근거는 **번호를 지어내지 않는다**는 것이다 —
      DOM 에 **실제로 있는 썸네일 번호만** `_S`→`_L` 로 바꾼다(`_1`·`_2`… 훑기 없음).
      (종전 서술 「없는 번호는 307 이라 안전」은 근거가 못 된다. 307 은 리다이렉트라
       따라가면 대체 이미지로 200 이 날 수 있어, '없다'의 증거가 아니다.)
    """
    m = _LOTTEIMALL_THUMB_RE.match(url or "")
    if not m:
        return url
    return f"{m.group(1)}_L{m.group(2)}{m.group(3)}"


def _parse_image_urls(soup: BeautifulSoup, product_url: str) -> list[str]:
    """[2026-07-23 M4-4] 롯데아이몰 상품 이미지 URL 목록. 대표가 첫 원소.

    실측 구조(www.lotteimall.com 상품 페이지, 2026-07-23)::

        div.area_thumb
          ├ div.thumb_product  > a > img   ← 큰 대표 이미지 (`{goods_no}_L{n}.jpg`)
          └ div.list_thumb ul.slide_cont li a img  ← 썸네일 줄 (`{goods_no}_S{n}.jpg`)

    - 대표 = `div.thumb_product img`. (`meta[og:image]` 는 같은 사진의 `_H` 판이라
      **일부러 안 쓴다** — 대표와 추가가 다른 렌디션으로 섞이면 마켓에서 같은 사진이
      두 번 실린다. 르무통 I6 과 같은 함정.)
    - 추가 = 썸네일 줄을 `_S→_L` 로 올려 대표와 같은 렌디션으로 맞춘 뒤 순서유지 dedup.
      (사진이 1장뿐인 상품은 썸네일 = 대표와 같은 파일이 되어 여기서 걸러진다.)

    ⚠️ `div.thumb_product` 로 좁힌 근거 — 같은 페이지에 롯데 **기획전 배너**
      (`/upload/corner/…`)·**추천상품 썸네일**(`/upload/event/detail/…`)·
      cre.ma 리뷰 위젯 이미지가 널려 있다. 페이지 전체 `img` 를 긁으면 그게 대표가 된다.

    🔴 지연로딩 — [리뷰지적 I3] 종전 `src or data-src` 는 **base64 placeholder 가
      truthy** 라 `data-src` 를 영영 안 봤다. 갤러리가 지연로딩으로 오는 순간
      대표이미지 0장(+로그 무음) → 6마켓 등록 차단. 상세정리기와 **같은 규칙**
      (`base.pick_img_src`)을 쓴다. 같은 페이지 상세엔 이미 speedycat base64 가 온다.

    ★ 지재권 — URL 문자열만 만든다. 파일은 내려받지 않는다.
    """
    cands: list[str] = []
    for sel in ("div.thumb_product img", "div.list_thumb img"):
        for tag in soup.select(sel):
            src = pick_img_src(tag)
            if not src or _LOTTEIMALL_NOIMG in src:
                continue          # '이미지 없음' 회색판 — 대표이미지로 쓰면 오등록
            cands.append(_lotteimall_thumb_to_large(src))
    return build_image_urls(cands, product_url)


def _parse_detail_html(soup: BeautifulSoup, product_url: str) -> str:
    """[2026-07-23 M4-4] 롯데아이몰 상품상세 HTML. 못 찾으면 빈 문자열.

    실측 구조(2026-07-23)::

        div.detail
          ├ div.detail_info.v2 / div.ifr_info
          ├ div.tdy_snd_banner            ← 🔴 롯데 「오늘의 방송」 배너(남의 몰 홍보)
          └ div.area_statem > div.box_statem
                └ div#speedycat_container_root   ← 셀러 상세 원문(이미지 46장)

    `div.detail` 을 통째로 쓰면 배너가 딸려 오므로 **`#speedycat_container_root`** 로
    좁힌다(그게 없는 셀러를 위해 `div.box_statem` → `div.area_statem` 순 폴백).

    ★ 지연로딩 — 롯데의 이미지 최적화(speedycat)가 `src` 에 2×2 base64 placeholder 를
      넣고 실주소를 `data-src` 에 둔다
      (`//ca.lotteimall.com/S/ai.esmplus.com/…jpg?sh=1280&imw=780`).
      그대로면 마켓 상세가 백지 — 공통 `sanitize_detail_html` 이 `data-src` 를 살린다.
    """
    node = (soup.select_one("#speedycat_container_root")
            or soup.select_one("div.area_statem div.box_statem")
            or soup.select_one("div.area_statem"))
    if node is None:
        return ""
    return sanitize_detail_html(node, product_url)


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
            "included_in_sale_price": False,
            "source": "dataBenefit.cardDiscountList",
        }
        또는 None.

    사용자 명세 매핑:
        카드 청구 할인 / %할인 / "X% (XXX원)" / 자동 ❌ / 크롤링 ✅
        → ``rate`` + ``amount`` 둘 다 박아서 UI 가 "5% (6,330원)" 텍스트 생성 가능.

    ★ 2026-07-18 — ``included_in_sale_price`` 를 True→**False** 로 정정.
      crawled_price 가 최대할인가(카드 포함) → 표면노출가(카드 미적용) 로 바뀌었으므로
      카드할인은 더 이상 판매가에 반영돼 있지 않다. 이 플래그가 True 로 남으면
      ``api_pricing.py`` 의 "카드 OFF 시 가격 환원"(price / (1-rate)) 이 걸려
      **이미 카드가 빠진 가격을 한 번 더 부풀린다**. False 가 사실이자 안전값.
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
                    "included_in_sale_price": False,
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
                "included_in_sale_price": False,
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
                    "included_in_sale_price": False,
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


def _parse_download_coupons(soup: BeautifulSoup) -> list:
    """PDP 「쿠폰받기」 레이어의 다운로드 쿠폰 목록 → ``[{label, rate|amount}]``.

    [2026-07-23 라이브 실측] goods_no=2559138690 (사장님 질문에서 출발)
        <div class="layer_down_coupon"> … <div class="coupon_list"><ul><li>
          <span class="coupon">
            <span class="price">5<span class="per">%</span></span>   ← per 가 '%' 면 정률
            <span class="name">[르무통] 5% 다운로드 쿠폰</span>
            <button class="btn btnCouponDown">쿠폰받기</button>

    ★ **추가 API 호출이 필요 없다** — 확장이 same-origin fetch 로 이미 받아오는
      원본 SSR HTML(403KB) 안에 이 레이어가 들어 있다(라이브 fetch 로 확인).

    ⚠️ 이 쿠폰이 들어가는 칸은 **「플러스 할인쿠폰」**이다(2026-07-23 주문서 실측).
       표면가에 이미 반영된 「할인쿠폰」과는 **동시 적용**되고, 대신 경유
       「네이버 N%플러스할인쿠폰」과 **택1**이다(쿠폰함 문구: 플러스/즉시적립 1개).
       차감액 계산은 `resolve_download_coupon_saving`.

    못 읽으면 빈 목록 — 예외를 던지지 않는다(쿠폰 실패가 가격·재고 크롤을 죽이면 안 됨).
    """
    box = soup.select_one("div.layer_down_coupon, .layer_down_coupon")
    if box is None:
        return []
    out: list = []
    for li in box.select(".coupon_list li"):
        name_el = li.select_one(".name")
        price_el = li.select_one(".price")
        if name_el is None or price_el is None:
            continue
        label = name_el.get_text(strip=True)
        per_el = price_el.select_one(".per")
        unit = per_el.get_text(strip=True) if per_el is not None else ""
        # `.price` 는 값+단위가 합쳐진 텍스트 → 단위 부분을 떼어 숫자만 남긴다.
        raw = price_el.get_text(strip=True)
        if unit and raw.endswith(unit):
            raw = raw[: -len(unit)]
        num = _to_int(raw)
        if not label or num <= 0:
            continue
        if "%" in unit:
            out.append({"label": label, "rate": num / 100.0})
        else:
            out.append({"label": label, "amount": num})
    return out


def _parse_preapplied_coupon_amount(html: str) -> int:
    """표면가에 **이미 반영된** 쿠폰할인 금액. 없으면 0.

    출처: ``dataBenefit.fullDiscountObj.discountList[]`` 중 ``discountNm`` 에
    '쿠폰' 이 들어간 항목의 ``discountAmount``.
    실측: ``{"discountNm":"쿠폰할인","discountAmount":"-29,100"}`` → 29100.

    이 값이 있어야 다운로드 쿠폰과의 **택1 비교**가 가능하다. 못 읽으면 0 —
    0 이면 "할인쿠폰 칸이 비었다"고 보고 다운로드 쿠폰을 그대로 쓰게 되므로,
    파싱 실패가 매입가를 **과소**하게 만든다. 그래서 이름·금액 두 필드가 붙어
    있는 형태만 인정하고, 이름이 유니코드 이스케이프여도 풀어서 본다.
    """
    total = 0
    pattern = (r'"discountNm"\s*:\s*"([^"]*)"\s*,\s*'
               r'"discountAmount"\s*:\s*"([^"]*)"')
    for m in re.finditer(pattern, html or ""):
        name, amt = m.group(1), m.group(2)
        try:
            name = json.loads('"%s"' % name)
        except ValueError:
            pass
        if "쿠폰" not in name:
            continue
        total = max(total, _to_int(amt.replace("-", "")))
    return total


def resolve_download_coupon_saving(*, surface_price, coupons, rival_saving=0) -> int:
    """PDP 다운로드 쿠폰 차감액. 없으면 0.

    ■ 어느 칸인가 — **「플러스 할인쿠폰」 칸** (2026-07-23 사장님 주문서 실측으로 확정)
      처음엔 「할인쿠폰」 칸으로 잘못 봤다. 실제 주문서:
          총 주문금액        149,000
          할인쿠폰 6장       −29,100   ← 표면가(119,900)에 이미 반영된 그것
          플러스 할인쿠폰    − 6,000   ← **[르무통] 5% 다운로드 쿠폰이 여기로 들어간다**
          최종결제금액       113,900
      → 할인쿠폰과 **택1이 아니라 동시 적용**이고, 기준은 정가가 아니라
        **할인쿠폰 적용 후 금액(=표면노출가)** 이다: 119,900 × 5% = 5,995 ≈ 6,000.

    ■ 대신 여기가 택1이다 — 쿠폰함 공식 문구 "**플러스/즉시적립할인은 1개만 적용**".
      경유 「네이버 N%플러스할인쿠폰」도 **같은 플러스 칸**이라 둘 중 하나만 쓴다.
      그 경쟁 차감액을 `rival_saving` 으로 받아 **더 큰 쪽이 이길 때만** 값을 낸다
      (진 경우 0 — 호출부가 반대쪽을 주입한다).

    쿠폰이 여러 장이어도 1장만 쓸 수 있으므로 가장 큰 1장으로 계산한다.
    값이 없거나 이상하면 0(안 깎음 = 매입가 과대 = 안전 방향, §4 폴백 금지).
    ⚠️ 단수는 내림(`int`)으로 둔다 — 실측 6,000 vs 계산 5,995 의 5원 차이는
       최종 매입가 백원 버림 단계에서 사라지고, 덜 깎는 쪽이 안전하다.
    """
    try:
        surface = int(surface_price or 0)
    except (TypeError, ValueError):
        return 0
    if surface <= 0 or not coupons:
        return 0
    best = 0
    for c in coupons or []:
        if not isinstance(c, dict):
            continue
        try:
            rate = float(c.get("rate") or 0)
            amount = int(c.get("amount") or 0)
        except (TypeError, ValueError):
            continue
        if rate > 0:
            cut = int(surface * rate)
        elif amount > 0:
            cut = amount
        else:
            continue
        best = max(best, cut)
    if best <= 0:
        return 0
    try:
        rival = int(rival_saving or 0)
    except (TypeError, ValueError):
        rival = 0
    # 플러스 칸 택1 — 경유 쿠폰이 더 크면 그쪽이 쓰이므로 여기선 0.
    return best if best > rival else 0


def _extract_point_rewards(html: str) -> Optional[dict]:
    """롯데 구매 적립혜택 (구매적립 L.POINT) + 리뷰작성 적립금 추출.

    출처: ``dataBenefit.fullDiscountObj.lPointObj``
        - ``nMbrPoint``  : 일반회원 구매적립 L.POINT (예: "+126P")
        - ``lMbrPoint``  : L.CLUB(유료) 회원 구매적립 L.POINT (예: "+633P")
        - ``pointLabelTxt``: "구매적립 L.POINT" (라벨)
        - ``nMbrSaveamt``: 일반회원 리뷰 적립금 (예: "+300원")
        - ``lMbrSaveamt``: L.CLUB 회원 리뷰 적립금 (예: "+600원")
        - ``gdasLabelTxt``: "리뷰작성 적립금" (라벨)

    사용자 명세 매핑 (2026-05-15 갱신):
        구매 적립혜택 / %적립금 / 0.5% (또는 사이트 표기) / 자동 ❌ / 크롤링 ✅
        → L.CLUB 회원 적립률이 통상 0.5% (사용자 명세) 와 일치.
          일반회원 0.1% 와 분리 노출.
        리뷰 적립금 / 정액 / 사이트 노출 (300원 일반 / 600원 L.CLUB)
        → 표시는 하되 활성/비활성은 사용자가 매트릭스 토글로 결정 (dyn).

    Returns:
        {
            "label": "구매적립 L.POINT",
            "default_point": 126,           # 일반회원 적립 P
            "club_point": 633,              # L.CLUB 회원 적립 P (없으면 0)
            "review_label": "리뷰작성 적립금",
            "review_default": 300,          # 일반 리뷰 적립금 (원)
            "review_club": 600,             # L.CLUB 리뷰 적립금 (원)
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

    # ★ 2026-05-15 — 리뷰작성 적립금 (사이트 노출 항목, 정액)
    review_default = _to_int(lp.get("nMbrSaveamt"))
    review_club = _to_int(lp.get("lMbrSaveamt"))
    review_label = (lp.get("gdasLabelTxt") or "리뷰작성 적립금").strip()

    if default_p <= 0 and club_p <= 0 and review_default <= 0 and review_club <= 0:
        return None

    return {
        "label": label,
        "default_point": default_p,
        "club_point": club_p,
        "review_label": review_label,
        "review_default": review_default,
        "review_club": review_club,
        "source": "dataBenefit.lPointObj",
    }


def _extract_max_price_from_databenefit(html: str) -> int:
    """dataBenefit JSON 의 commonDiscountObj.benefitPrc (예: "108,720") → int.

    페이지에 노출된 "롯데홈쇼핑 최대할인가" 와 1:1 일치 (★ 카드 청구할인 **포함**).
    ⚠️ 표면노출가가 아니다. 표면가는 ``_resolve_surface_price`` 로 구할 것.
    실패 시 0.
    """
    meta = _parse_data_benefit(html)
    if not meta:
        return 0
    cdo = (meta.get("data") or {}).get("commonDiscountObj") or {}
    return _to_int(cdo.get("benefitPrc"))


def _selector_discounted_price(soup: BeautifulSoup) -> int:
    """V7 셀렉터 ``.price > span.num`` (할인가). 없으면 0."""
    for price_el in soup.select(".price"):
        for child in price_el.find_all("span", recursive=False):
            if "num" in (child.get("class") or []):
                v = _to_int(child.get_text())
                if v:
                    return v
    return 0


def _resolve_surface_price(
    soup: BeautifulSoup,
    html: str,
    card: Optional[dict],
) -> tuple[int, str]:
    """★ 2026-07-18 (사용자 확정) — 롯데아이몰 **표면노출가 = 카드 미적용 할인가**.

    배경(왜 바꿨나):
      2026-05-13 정책은 ``commonDiscountObj.benefitPrc`` (= 롯데홈쇼핑 "최대할인가",
      카드 청구할인 **포함**) 를 crawled_price 로 담았다. 그런데 현대H몰(hmall.py)은
      표면가 = ``bbprc`` (카드 미포함) + 카드할인은 ``hmall_card_discount`` 로 분리한다.
      즉 두 소싱처가 같은 "표면노출가" 슬롯에 의미가 다른 값을 넣어 매트릭스 비교가
      성립하지 않았다. → 롯데아이몰을 H몰 규약(카드 미적용가)에 맞춘다.

    라이브 예시 (르무통 메이트 메리노울 운동화):
      정가 149,000 → 할인 −32,100 → **116,900 (22% 할인가) = 표면노출가**
                   → 삼성카드 7% 청구할인 −8,180 → 108,720 (= benefitPrc, 최대할인가)

    산출 규칙 (★ 추정·폴백 금지):
      A) 카드 청구할인이 걸린 페이지 (card.rate > 0):
           benefitPrc 는 카드가 이미 빠진 값이므로 그대로 쓰면 안 된다.
           표면가 = ``benefitPrc + cardDiscountList[0].discountAmount``.
           ↑ 항등식 근거: 사이트 노출값이 정확히 이 관계다.
             · 본 파일 헤더의 실측 예시: 최대할인가 120,320 = 할인가 126,650 − 6,330(국민카드 5%)
               (126,650 × 5% = 6,332.5 → 10원 절사 6,330 ✓)
             · 사용자 제공 실측 예시: 108,720 = 116,900 − 8,180(삼성카드 7%)
               (116,900 × 7% = 8,183 → 10원 절사 8,180 ✓)
           둘 중 하나라도 결측(benefitPrc==0 또는 amount==0)이면 **0 반환 → 호출자가 실패**.
           (카드율만 알고 금액을 모를 때 나눗셈으로 역산하면 사이트의 10원 절사 때문에
            원 단위가 어긋난다. 금전 직결이라 '틀린 값'보다 '실패'를 택한다.)
      B) 카드 청구할인이 없는 페이지:
           노출가 자체가 이미 카드 미적용가다 → benefitPrc → ``.price > span.num``
           → ``.final span.num`` 순으로 채택.

    Returns:
        (surface_price, source_tag). 확정 불가 시 (0, 사유).
    """
    max_price = _extract_max_price_from_databenefit(html) if html else 0
    sel_price = _selector_discounted_price(soup)
    final_el = soup.select_one(".final span.num")
    final_price = _to_int(final_el.get_text() if final_el else "")

    card_rate = float((card or {}).get("rate") or 0)
    card_amount = _to_int(str((card or {}).get("amount") or 0))

    # A) 카드 청구할인 있음 → benefitPrc 는 카드 포함가라 표면가가 아니다.
    if card and card_rate > 0:
        if max_price > 0 and card_amount > 0:
            return max_price + card_amount, "benefitPrc+cardDiscountAmount"
        return 0, (
            "카드 청구할인이 노출됐으나 표면가 복원 불가 "
            f"(benefitPrc={max_price}, card_amount={card_amount})"
        )

    # B) 카드 청구할인 없음 → 노출가 = 카드 미적용가
    #    ⚠️ 단, "카드 파싱이 실패한 것"과 "카드가 정말 없는 것"을 구분해야 한다.
    #    dataBenefit 에 cardDiscountList 항목이 있는데 card 가 None 이면 파싱 실패다.
    #    이때 benefitPrc 를 표면가로 쓰면 카드 포함가를 표면가로 둔갑시킨다 → 실패 처리.
    if not card:
        _meta = _parse_data_benefit(html) if html else None
        _raw_cards = ((_meta or {}).get("data") or {}).get("fullDiscountObj") or {}
        if _raw_cards.get("cardDiscountList"):
            return 0, "cardDiscountList 존재하나 카드할인 구조화 실패 — 표면가 확정 불가"

    if max_price > 0:
        return max_price, "benefitPrc(카드할인 없음)"
    if sel_price > 0:
        return sel_price, ".price>span.num(카드할인 없음)"
    if final_price > 0:
        return final_price, ".final span.num(카드할인 없음)"
    return 0, "가격 소스 전무"


def _parse_prices(soup: BeautifulSoup, html: str = "") -> tuple[int, int, int, int]:
    """롯데홈쇼핑 / 롯데IMALL 가격 파싱.

    ⚠️ 2026-07-18 — 여기서 나오는 ``max_price`` 는 **최대할인가(카드 청구할인 포함)** 라
      표면노출가가 **아니다**. crawled_price 로 담는 표면가는 ``_resolve_surface_price``
      가 단일 진실 원천. 본 함수는 정가·할인율 등 부가 정보용으로만 남는다.

    추출 우선순위 (max_price 기준):
      1) dataBenefit JSON 의 commonDiscountObj.benefitPrc — 사이트 "최대할인가" 와 1:1
      2) (폴백) V7 셀렉터 ``.price > span.num``
      3) (최후 폴백) ``.final span.num``

    Returns: (sale_price, max_price, origin_price, discount_rate)
        - sale_price : ``.final span.num`` (V7 호환, 정보용)
        - max_price  : 최대할인가 (카드 포함)
        - origin_price: 정가
    """
    # V7 호환 (정보용)
    final_el = soup.select_one(".final span.num")
    sale_price = _to_int(final_el.get_text() if final_el else "")

    # ★ 1순위: dataBenefit JSON benefitPrc (정확한 최대할인가)
    max_price = _extract_max_price_from_databenefit(html) if html else 0

    # 2순위: V7 셀렉터 ``.price > span.num``
    if max_price == 0:
        max_price = _selector_discounted_price(soup)

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


# ★ 2026-06-25 — 롯데아이몰 실재고 3상태(품절0/실수량N/충분)
#   페이지 JS 배열 ``itemInvQtyInfo = [{opt_cd_0,opt_val_cd_0,item_no,inv_qty,master_yn}]``
#   에 옵션별 실재고(inv_qty)가 들어있다. opt_val_cd_0 = 옵션 li 의 id ``<grp>_<N>`` 의 N.
#   → DOM soldout(품절/있음 2상태) 대신 inv_qty 로 실수량까지 포착(라이브 검증: 0 위치가
#      DOM 품절과 정확 일치, 240mm=17·270mm=9·255mm=5 등 실수량).
_ITEM_INV_QTY_PATTERN = re.compile(
    r"opt_val_cd_0\s*:\s*'?(\d+)'?[\s\S]{0,80}?inv_qty\s*:\s*(\d+)")
_OPT_LI_ID_PATTERN = re.compile(r"\d+_(\d+)$")
_SIZE_PAREN_PATTERN = re.compile(r"\s*\(.*?\)\s*")

# ★ 2026-07-13 — 롯데아이몰 재고 3상태 기준을 '사이트 자체 JS'에 정렬(경계 5).
#   근거: 라이브 상품 페이지 JS 원문(goods 2559329941, 실측)이 재고 라벨을 이렇게 붙인다.
#       if (optInvQty <= 0)       → ' (품절)'
#       else if (optInvQty > 500) → ' (판매중)'        # 충분(대량)
#       else if (optInvQty < 5)   → ' (N개 남음)'       # ★ 한정 = 실수량 노출
#       else (5 <= inv_qty <= 500)→ 라벨 없음 = 충분
#   → 사이트가 "N개 남음"(한정)으로 보는 경계는 inv_qty<5 뿐이다. 5~500 은 그냥 '있음/충분'.
#   [구 로직 폐기] 이전엔 '30 상한→50 표기'였는데, 이는 특정 상품(97조합) 1회 관찰에서
#     최댓값이 우연히 30이었던 것을 상한으로 오일반화한 것. 그 결과 inv_qty 10 같은
#     '충분' 재고를 "10개 남음"으로 오표기 → 진짜 한정(2개)과 구분 불가(사용자 리포트).
#   충분 센티넬 = 999(프로젝트 표준: 품절0 / 실수량N / 충분999). '확인 불가'는 별도(-1).
_LOTTEIMALL_LIMITED_THRESHOLD = 5   # inv_qty < 5 → 한정(실수량 노출)
_LOTTEIMALL_SUFFICIENT_DISP = 999   # inv_qty >= 5 → 충분


def _lotteimall_disp_qty(inv_qty: int) -> int:
    """롯데아이몰 재고 3상태 표기값(사이트 JS 기준):
    품절(<=0)→0 · 한정(0<inv_qty<5)→실수량 그대로 · 충분(>=5)→999."""
    if inv_qty <= 0:
        return 0
    if inv_qty < _LOTTEIMALL_LIMITED_THRESHOLD:
        return inv_qty
    return _LOTTEIMALL_SUFFICIENT_DISP


def _extract_item_inv_qty(html: str) -> dict[str, int]:
    """``itemInvQtyInfo`` → {opt_val_cd_0(str): inv_qty(int)}. 없으면 {}."""
    out: dict[str, int] = {}
    for m in _ITEM_INV_QTY_PATTERN.finditer(html or ""):
        out[m.group(1)] = int(m.group(2))
    return out


def _build_inv_qty_by_size(soup: BeautifulSoup, html: str) -> dict[str, int]:
    """옵션 li id(``<grp>_<N>``) + inv_qty(opt_val_cd_0=N) → {size_text: inv_qty}.

    단일 색상(사이즈 단일축) 상품에서 size 텍스트로 실재고를 직접 찾기 위함.
    다색상(색×사이즈)은 size 가 색마다 중복돼 모호 → 호출부에서 단일색일 때만 사용.
    """
    inv_map = _extract_item_inv_qty(html)
    if not inv_map:
        return {}
    out: dict[str, int] = {}
    for li in soup.select(".inp_option.inpOptList li[id]"):
        m = _OPT_LI_ID_PATTERN.match(li.get("id", "") or "")
        if not m:
            continue
        cd = m.group(1)
        if cd not in inv_map:
            continue
        p = li.select_one("p.txt_option")
        raw = (p.get_text(strip=True) if p else li.get_text(strip=True)) or ""
        size = _SIZE_PAREN_PATTERN.sub("", raw).strip()   # "260mm (품절)" → "260mm"
        if size and not OPT_HEADER_PATTERN.match(size):
            out[size] = inv_map[cd]
    return out


# ★ 2026-06-28 — 롯데아이몰 2축(색상×사이즈) 실재고 3상태.
#   색상모음전 페이지의 itemInvQtyInfo 객체는 opt_val_cd_0(색 코드)·opt_val_cd_1(사이즈 코드)
#   ·inv_qty 를 함께 담는다(라이브 검증: 9색×13사이즈=97조합 정확 수량). 단축 경로는 색이
#   하나라 size 만으로 매핑 가능했지만, 2축은 (색,사이즈) 조합으로 매핑해야 정확.
_ITEM_INV_OBJ_PATTERN = re.compile(r"\{[^{}]*?inv_qty[^{}]*?\}")
_OVC0_PATTERN = re.compile(r"opt_val_cd_0\s*:\s*'?(\d+)'?")
_OVC1_PATTERN = re.compile(r"opt_val_cd_1\s*:\s*'?(\d+)'?")
_INVQ_PATTERN = re.compile(r"inv_qty\s*:\s*(\d+)")


def _extract_item_inv_qty2(html: str) -> dict[tuple[str, str], int]:
    """``itemInvQtyInfo`` → {(opt_val_cd_0, opt_val_cd_1): inv_qty}. 2축용. 없으면 {}."""
    out: dict[tuple[str, str], int] = {}
    for obj in _ITEM_INV_OBJ_PATTERN.findall(html or ""):
        c0 = _OVC0_PATTERN.search(obj)
        c1 = _OVC1_PATTERN.search(obj)
        q = _INVQ_PATTERN.search(obj)
        if c0 and c1 and q:
            out[(c0.group(1), c1.group(1))] = int(q.group(1))
    return out


def _opt_code_label_map(ul) -> dict[str, str]:
    """하나의 옵션 리스트(ul) → {opt_val_cd(li id 의 N): label}. 헤더('색상 선택')는 제외."""
    out: dict[str, str] = {}
    if ul is None:
        return out
    for li in ul.select("li[id]"):
        m = _OPT_LI_ID_PATTERN.match(li.get("id", "") or "")
        if not m:
            continue
        p = li.select_one("p.txt_option")
        raw = (p.get_text(strip=True) if p else li.get_text(strip=True)) or ""
        label = _SIZE_PAREN_PATTERN.sub("", raw).strip()
        if label and not OPT_HEADER_PATTERN.match(label):
            out[m.group(1)] = label
    return out


def _build_inv_qty_by_color_size(soup: BeautifulSoup, html: str) -> dict[tuple[str, str], int]:
    """2축: (색상 label, 사이즈 label) → inv_qty. 리스트[0]=색상·[1]=사이즈 가정."""
    inv = _extract_item_inv_qty2(html)
    if not inv:
        return {}
    lists = soup.select(".inp_option.inpOptList")
    if len(lists) < 2:
        return {}
    color_map = _opt_code_label_map(lists[0])   # opt_val_cd_0 → 색 label
    size_map = _opt_code_label_map(lists[1])     # opt_val_cd_1 → 사이즈 label
    out: dict[tuple[str, str], int] = {}
    for (c0, c1), q in inv.items():
        cl = color_map.get(c0)
        sl = size_map.get(c1)
        if cl and sl:
            out[(cl, sl)] = q
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

# ★ 2026-05-15 — 자동 적용 vs 미적용 판정 키
#   ``dcTnnoCd`` 가 sale_price (immdDcAplyTotAmt) 에 이미 반영됐는지 판단의 단일 진실 원천.
#     · 1ST = 스토어 즉시할인        → 자동 (sale_price 에 반영됨)
#     · 2ND = CM할인 (롯데ON 즉시할인) → 자동 (sale_price 에 반영됨)
#     · 3RD = 무료배송 할인          → 자동 (sale_price 에 반영됨)
#     · 4TH = 쿠폰 (스토어/상품)     → 다운로드 필요 (sale_price 에 미반영)
#     · 5TH = 카드즉시할인           → 결제수단 한정 (sale_price 에 미반영)
#   사용자 명세 검증 (2026-05-15):
#     URL #1 (르무통): sale_price=126,060 = 149,000 - 8,940 (1ST) - 14,000 (2ND) ✓
#     URL #2 (코르테즈 LE1216549546): sale_price=64,980 = 83,300 - 18,320 (1ST) ✓
LOTTEON_AUTO_APPLIED_TIERS = {"1ST", "2ND", "3RD"}

# 미적용 사유 추출용 dispDtls 텍스트 패턴
#   예: "사용조건 : 70,000원 이상 구매시, 최대 30,000원"
LOTTEON_MIN_AMT_PATTERN = re.compile(r"([\d,]+)\s*원\s*이상\s*구매")
# 예: "할인율 : 5%" / "할인액 : 5,000원" / "발급기간 : ~05.31"


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
        import os as _os
        browser = p.chromium.launch(headless=_os.environ.get('WATCH_CRAWL') != '1')  # WATCH_CRAWL=1 → 보이는 창
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1440, "height": 900},
        )
        page = ctx.new_page()
        from .base import block_heavy_resources
        block_heavy_resources(page)  # [PERF] 이미지/영상/폰트 차단 — JSON API 데이터는 그대로

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
    # 단일색 상품(단품): 옵션축이 1개뿐이고 값이 사이즈 형태면 → 색상축이 아니라 사이즈축.
    # (이대로 두면 '230' 이 색상으로 잡혀 매칭/필터가 전부 실패)
    if not sizes and colors and _looks_like_sizes(colors):
        return [], colors
    return colors, sizes


def _looks_like_sizes(items: list[dict]) -> bool:
    """축 값들이 신발 사이즈 형태(숫자/ mm, 150~400)인지 다수결 판정."""
    if not items:
        return False
    n = 0
    for it in items:
        raw = (it.get("name") or "").lower().replace("mm", "").strip()
        d = "".join(ch for ch in raw if ch.isdigit())
        if d and 150 <= int(d) <= 400:
            n += 1
    return n >= max(1, len(items) * 0.6)


def _extract_unmet_reason(promo: dict, sale_price: int) -> tuple[str, str]:
    """미적용 사유 + 자세히 텍스트 추출.

    ★ 2026-05-15 — 사용자 명세 (5/15):
      "코르테즈(두번째 상품의 경우) **'주문금액부족'이라서 반영 못함**을 알려줘야하고,
       **자세히 눌러서 얼마인지도 표현**해줘야지."

    Returns:
        (unmet_reason, condition_detail)
        - unmet_reason: 한 줄 사유 (예: "주문금액 부족 (70,000원 이상)", "첫구매 한정")
        - condition_detail: dispDtls[] 를 " / " 로 join 한 "자세히" 텍스트
          (예: "할인율 : 7% / 사용조건 : 70,000원 이상 구매시, 최대 30,000원 / 사용기간 : ~05.17")

    판정 우선순위:
      1) mainFlag.isFirstBuy=True  → "첫구매 한정"
      2) mainFlag.isStrJJim=True   → "스토어찜 한정"
      3) mainFlag.isClub=True      → "롯데클럽 회원 한정"
      4) mainFlag.isLpntMb=True    → "L포인트 회원 한정"
      5) dispDtls 에서 "X원 이상 구매" 추출 → sale_price < X → "주문금액 부족 (X원 이상)"
      6) prAplyYn == "N" 인데 위 사유 없음 → "조건 미충족"
    """
    flag = promo.get("mainFlag") or {}
    # dispDtls — "자세히" 정보 (이미 임베드되어 있음 → 클릭 불필요)
    disp_dtls = promo.get("dispDtls") or []
    condition_detail = " / ".join(str(x).strip() for x in disp_dtls if x)

    reasons: list[str] = []
    # 회원 조건은 미적용 사유의 직접 원인이지만, 카드즉시할인은 항상 카드 보유 필요라서
    # mainFlag 가 비어 있는 경우도 있다. 따라서 mainFlag 는 부가 조건으로만 다룸.
    if isinstance(flag, dict):
        if flag.get("isFirstBuy"):
            reasons.append("첫구매 한정")
        if flag.get("isStrJJim"):
            reasons.append("스토어찜 한정")
        if flag.get("isClub"):
            reasons.append("롯데클럽 회원 한정")
        if flag.get("isLpntMb"):
            reasons.append("L포인트 회원 한정")

    # 주문금액 조건 매칭 — dispDtls 의 "X원 이상 구매" 패턴
    min_amt_required = 0
    for dtl in disp_dtls:
        m = LOTTEON_MIN_AMT_PATTERN.search(str(dtl))
        if m:
            try:
                v = int(m.group(1).replace(",", ""))
                if v > 0:
                    min_amt_required = v
                    break
            except (ValueError, TypeError):
                pass

    # minPdAmt JSON 필드 폴백
    if min_amt_required == 0:
        try:
            v = int(promo.get("minPdAmt") or 0)
            if v > 0:
                min_amt_required = v
        except (ValueError, TypeError):
            pass

    if min_amt_required > 0 and sale_price > 0 and sale_price < min_amt_required:
        reasons.insert(0, f"주문금액 부족 ({min_amt_required:,}원 이상)")

    # 결제수단 한정 (카드즉시할인) — pyMnsDtl 있으면 카드 필요 사실 표기
    py_mns = promo.get("pyMnsDtl")
    disp_title = (promo.get("dispTitle") or "").strip()
    if isinstance(py_mns, dict) and disp_title:
        # 이미 카드명 (예: "삼성카드", "토스페이 롯데카드") 이 dispTitle 에 들어있음
        # → 별도 사유 추가 없이 dispTitle 만으로 사용자가 인지 가능
        pass

    return " / ".join(reasons), condition_detail


def _parse_lotteon_benefits(favor_data: dict, sale_price: int = 0) -> tuple[list[dict], str]:
    """롯데ON ``favorBox/benefits.discountGroups`` → 쿠폰별 분리 추출.

    ★ 2026-05-15 변경 (사용자 명세):
      - 각 쿠폰에 ``applied`` (bool) 필드 추가 — sale_price 에 자동 반영 여부.
        판정 키: ``dcTnnoCd in {"1ST","2ND","3RD"}``.
        (1ST=스토어즉시할인, 2ND=CM할인, 3RD=무료배송 → 모두 immdDcAplyTotAmt 에 포함)
      - 미적용 항목: ``unmet_reason`` (예: "주문금액 부족 (70,000원 이상)", "첫구매 한정")
      - ``condition_detail``: dispDtls[] 의 "자세히" 정보 (할인율/사용조건/사용기간)
      - ``discount_info`` 텍스트: 자동 적용 항목 ✓ / 미적용 항목 (사유) 으로 분리 표시

    Args:
        favor_data: pbf API ``favorBox/benefits.data``
        sale_price: 이미 추출된 sale_price (immdDcAplyTotAmt). 주문금액 부족 판정에 사용.

    Returns:
        (coupons, discount_info_text)
        coupons: 쿠폰별 dict 리스트 (UI/breakdown 용)
            {
              group: str,                # groupId (IMMD / IMMD_AND_PRODUCT_COUPON / STORE_COUPON / ORDER 등)
              group_title: str,          # discountGroup.title (사용자 노출용)
              name: str,                 # dispTitle 또는 dispName 또는 prNm
              kind: str,                 # prKndCd
              type: str,                 # prTypCd
              dc_type: str,              # dcTypCd (FX/FL — 정액 vs 정률)
              dc_tier: str,              # dcTnnoCd (1ST/2ND/3RD/4TH/5TH)
              dc_rate: float,            # % (없으면 0)
              dc_amount: int,            # 원 (없으면 0)
              text: str,                 # "X% (XXX원)" 사용자 표시
              condition: str,            # mainFlag/금액 조건 (한 줄)
              condition_detail: str,     # dispDtls[] join — "자세히" 텍스트
              applied: bool,             # ★ sale_price 에 이미 반영 (1ST/2ND/3RD 인 자동 할인)
              apply_yn: bool,            # prAplyYn==Y (사이트가 현재 사용자에게 적용 가능 판정)
              best_apply_yn: bool,       # bestPrAplyYn==Y (최저가 계산 포함 여부)
              check_state: str,          # check ("none" / "enabled" / "disabled")
              unmet_reason: str,         # ★ 미적용 사유 (적용된 쿠폰은 빈 문자열)
              is_card_coupon: bool,
              coupon_no: str,
            }
        discount_info_text: 모음전 UI 표시 텍스트
            예: "자동 적용: 스토어 즉시할인 6% (8,940원) / 롯데ON 즉시할인 10% (14,000원)
                 ｜추가 가능: [ON] 첫구매 5천원 할인 [미적용: 첫구매 한정]"
    """
    coupons: list[dict] = []
    applied_parts: list[str] = []
    unapplied_parts: list[str] = []

    for dg in favor_data.get("discountGroups") or []:
        group_title = (dg.get("title") or "").strip()
        is_card_coupon_group = (group_title == LOTTEON_CARD_COUPON_TITLE)

        for promo in dg.get("discountApplyPromotionList") or []:
            group_id = promo.get("groupId") or ""
            pr_knd = promo.get("prKndCd") or ""
            pr_typ = promo.get("prTypCd") or ""
            dc_typ = promo.get("dcTypCd") or ""
            dc_tier = (promo.get("dcTnnoCd") or "").strip()
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

            apply_yn = (promo.get("prAplyYn") or "").upper() == "Y"
            best_apply_yn = (promo.get("bestPrAplyYn") or "").upper() == "Y"
            check_state = (promo.get("check") or "").strip().lower()

            # ★ 자동 적용 판정 — dcTnnoCd 단일 진실 원천 (qty.immdDcAplyTotAmt 매칭)
            applied = (
                dc_tier in LOTTEON_AUTO_APPLIED_TIERS
                and apply_yn
                and best_apply_yn
            )

            # 미적용 사유 + "자세히" 텍스트
            unmet_reason, condition_detail = _extract_unmet_reason(promo, sale_price)
            # 자동 적용된 쿠폰은 미적용 사유 비움
            if applied:
                unmet_reason = ""

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
                "dc_tier": dc_tier,
                "dc_rate": dc_rate,
                "dc_amount": dc_amount,
                "text": value_text,
                "condition": condition,
                "condition_detail": condition_detail,
                "applied": applied,
                "apply_yn": apply_yn,
                "best_apply_yn": best_apply_yn,
                "check_state": check_state,
                "unmet_reason": unmet_reason,
                "is_card_coupon": is_card_coupon,
                "coupon_no": coupon_no,
            })

            # discount_info 텍스트 빌드 — 자동 vs 미적용 분리
            #   name 에 이미 % 표기가 포함된 경우 (예: "스토어 즉시할인 6%") value_text 중복 회피.
            if name and value_text:
                name_norm = name.rstrip()
                rate_int_token = f"{int(dc_rate)}%" if dc_rate == int(dc_rate) and dc_rate > 0 else None
                if rate_int_token and name_norm.endswith(rate_int_token):
                    prefix = name_norm[: -len(rate_int_token)].rstrip()
                    seg = f"{prefix} {value_text}".strip() if prefix else value_text
                else:
                    seg = f"{name} {value_text}"
            elif name:
                seg = name
            else:
                continue

            if applied:
                applied_parts.append(seg)
            else:
                # 미적용 — 사유 + 자세히
                tail_bits: list[str] = []
                if unmet_reason:
                    tail_bits.append(f"미적용: {unmet_reason}")
                elif not apply_yn:
                    tail_bits.append("미적용")
                if condition_detail:
                    tail_bits.append(f"자세히: {condition_detail}")
                if tail_bits:
                    seg += " [" + " / ".join(tail_bits) + "]"
                elif condition:
                    seg += f" [{condition}]"
                unapplied_parts.append(seg)

    # 최종 텍스트 조립 — 자동 적용 / 추가 가능 (미적용) 두 섹션
    final_parts: list[str] = []
    if applied_parts:
        final_parts.append("자동 적용: " + " / ".join(applied_parts))
    if unapplied_parts:
        final_parts.append("추가 가능: " + " / ".join(unapplied_parts))
    discount_info_text = " ｜ ".join(final_parts)

    return coupons, discount_info_text


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


def _extract_lotteon_owners_member_discount(addition_data: dict) -> tuple[float, str]:
    """롯데ON 회원할인 (롯데오너스 X% 추가 할인) 추출.

    ★ 2026-05-15 — 사용자 명세 (스크린샷):
      "회원할인 > 롯데오너스 할인 1% : -1,260원" — 사용자 회원가입 상태라 자동 활성 ✅.

    출처: ``addition`` API 응답 의 ``additionFavorInfo.ownersFavor``
        - ``ownersDcCnts``     : "추가 1% 할인"     (라벨)
        - ``ownersHighLight``  : ["1%"]             (rate 정수형)
        - ``purchaseFavorCnts``: "추가 0.5% 적립"   (적립 — 별도)

    Returns:
        (rate, label)
          rate: 0.0~1.0 (예: 0.01 = 1%). 없으면 0.0.
          label: 사용자 노출 라벨 (예: "롯데오너스 할인 1%"). 없으면 빈 문자열.
    """
    if not isinstance(addition_data, dict):
        return 0.0, ""
    # additionFavorInfo wrapper 또는 root 둘 다 대비
    info = addition_data.get("additionFavorInfo") or addition_data
    if not isinstance(info, dict):
        return 0.0, ""
    of = info.get("ownersFavor") or {}
    if not isinstance(of, dict):
        return 0.0, ""

    rate = 0.0
    # 1) ownersHighLight: ["1%"] (가장 정확)
    hl = of.get("ownersHighLight") or []
    if isinstance(hl, list):
        for tok in hl:
            m = re.search(r"(\d+(?:\.\d+)?)\s*%", str(tok))
            if m:
                try:
                    rate = float(m.group(1)) / 100.0
                    break
                except (ValueError, TypeError):
                    pass
    # 2) ownersDcCnts: "추가 1% 할인" (폴백)
    if rate <= 0:
        cnts = (of.get("ownersDcCnts") or "").strip()
        m = re.search(r"(\d+(?:\.\d+)?)\s*%", cnts)
        if m:
            try:
                rate = float(m.group(1)) / 100.0
            except (ValueError, TypeError):
                pass

    if rate <= 0:
        return 0.0, ""
    # 라벨 — 사용자 스크린샷 명세 ("롯데오너스 할인 X%")
    rate_text = f"{int(rate * 100)}%" if rate * 100 == int(rate * 100) else f"{rate * 100:g}%"
    label = f"롯데오너스 할인 {rate_text}"
    return rate, label


def _extract_lotteon_store_jjim_coupon(coupons: list[dict]) -> tuple[int, str]:
    """스토어찜 쿠폰 (정액 차감) 추출.

    ★ 2026-05-15 — 사용자 명세 (스크린샷):
      "스토어쿠폰 > 스토어찜 감사 쿠폰 -6,000원" (받기 + 1회 사용 조건. 비활성 기본).

    coupons 리스트 (이미 _parse_lotteon_benefits 가 만든 dict 들) 안에서:
      - kind == "CPN_SLR_CPN"  (스토어쿠폰)
      - 또는 group == "STORE_COUPON"
      - 또는 name/condition 에 '스토어찜' 포함

    Returns:
        (amount, label)
          amount: 정액 (원). 없으면 0.
          label: "스토어찜 감사 쿠폰 -X,XXX원". 없으면 빈 문자열.
    """
    for c in coupons or []:
        kind = (c.get("kind") or "").upper()
        group = (c.get("group") or "").upper()
        name = c.get("name") or ""
        is_store_jjim = (
            kind == "CPN_SLR_CPN"
            or group == "STORE_COUPON"
            or "스토어찜" in name
        )
        if not is_store_jjim:
            continue
        try:
            amt = int(c.get("dc_amount") or 0)
        except (ValueError, TypeError):
            amt = 0
        if amt <= 0:
            continue
        # 라벨 — 사용자 스크린샷 명세
        label = f"{name or '스토어찜 감사 쿠폰'} -{amt:,}원"
        return amt, label
    return 0, ""


def _fetch_lotteon(product_url: str, timeout_sec: int) -> CrawlResult:
    """롯데ON (lotteon.com) 단품 크롤링 — Playwright + pbf API 캡처."""
    bundle = _fetch_lotteon_via_playwright(product_url, timeout_sec)
    base_data = bundle["base"]
    option_data = bundle["option"]
    favor_data = bundle["favor"]
    qty_data = bundle["qty"]
    addition_data = bundle["addition"]

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
    #   ★ 2026-05-15 — sale_price 를 함께 넘겨 "주문금액 부족" 미적용 사유 판정에 사용.
    coupons, discount_info_text = _parse_lotteon_benefits(favor_data, sale_price=max_price)
    auto_card_discount = None
    # 사용자 명세상 카드즉시할인은 자동 적용 X — auto_card_discount 는 None 유지
    # (UI 가 coupons 안의 is_card_coupon=True 항목을 별도 표시)

    # ★ 2026-05-15 — 사용자 스크린샷 명세 동적 혜택 2종 추출:
    #   1) 롯데오너스 1% 회원할인 (addition API ownersFavor → 자동 활성)
    #   2) 스토어찜 감사 쿠폰 -6,000원 (favor STORE_COUPON → 비활성 기본, 토글)
    lotte_member_rate, lotte_member_label = _extract_lotteon_owners_member_discount(addition_data)
    store_jjim_amount, store_jjim_label = _extract_lotteon_store_jjim_coupon(coupons)

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
            opt = {
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
            }
            # ★ 2026-05-15 — 동적 혜택 키 (compute_breakdown 이 자동 차감)
            if lotte_member_rate > 0:
                opt["lotte_member_discount_rate"] = lotte_member_rate
                opt["lotte_member_discount_label"] = lotte_member_label
            if store_jjim_amount > 0:
                opt["store_jjim_coupon_amount"] = store_jjim_amount
                opt["store_jjim_coupon_label"] = store_jjim_label
            options.append(opt)

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
        # 서버 fetch(curl_cffi). ⚠️ lotteimall WAF 가 서버 IP 를 403 으로 막을 수 있어
        #   라이브는 확장 navGrab → /api/sources/parse → parse_html(실브라우저 HTML) 경로 우선.
        html = self._fetch_html(product_url)
        return self.parse_html(html, product_url)

    def parse_html(self, html: str, product_url: str) -> CrawlResult:
        """롯데홈쇼핑/롯데아이몰 SSR HTML 파싱 (네트워크 없음 — 확장 navGrab 진입점).

        ⚠️ lotteon.com(SPA)은 이 경로가 아니라 fetch→_fetch_lotteon(API)로 처리.
        실브라우저(확장)가 받은 HTML 을 그대로 파싱 → lotteimall WAF 우회.
        """
        product_id = _extract_product_id(product_url)
        # V7 는 빈 productId 도 허용 — 동일 동작 유지
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
        # ★ 2026-07-23 (사장님 질문에서 출발) — PDP 「쿠폰받기」 다운로드 쿠폰.
        #   주문서 실측 결과 이 쿠폰은 **「플러스 할인쿠폰」 칸**이다 → 표면가에
        #   이미 들어간 「할인쿠폰」과 **동시 적용**, 대신 경유 네이버 플러스쿠폰과
        #   택1. 선반영액(`preapplied_coupon`)은 차감 계산엔 안 쓰고 **검산·진단용**
        #   으로 계속 실어 보낸다(정가 = 표면가 + 선반영액 대조).
        download_coupons = _parse_download_coupons(soup)
        preapplied_coupon = _parse_preapplied_coupon_amount(html)

        # ★ 2026-07-18 (사용자 확정) — crawled_price = **표면노출가(카드 미적용 할인가)**.
        #   구 정책은 최대할인가(카드 청구할인 포함)를 담아 H몰(bbprc=카드 미포함)과
        #   의미가 달랐다 → 매트릭스 비교 불성립. H몰 규약에 맞춘다.
        #   카드 청구할인은 버리지 않고 lotteimall_card_discount/_label 로 분리 보관.
        base_for_policy, _price_source = _resolve_surface_price(soup, html, auto_card_discount)
        if base_for_policy <= 0:
            # 폴백 금지 — 정가·최대할인가로 조용히 대체하지 않는다(추정가 = 금전 손실).
            raise RuntimeError(
                f"[lotteimall] 표면노출가(카드 미적용 할인가) 확정 실패 — {_price_source}"
            )

        # ★ 카드 청구할인 분리 보관 (H몰 hmall_card_discount/_label 패턴 그대로).
        #   M1-6 에서 이 값을 조건부 혜택(사용자 토글)으로 붙인다.
        card_benefits: dict = {}
        # 다운로드 쿠폰 — 있을 때만 실어 보낸다(빈 값은 서버가 기존값 보존).
        if download_coupons:
            card_benefits["lotteimall_download_coupons"] = download_coupons
        if preapplied_coupon > 0:
            card_benefits["lotteimall_preapplied_coupon"] = preapplied_coupon
        if auto_card_discount:
            _cd_amt = _to_int(str(auto_card_discount.get("amount") or 0))
            if _cd_amt > 0:
                card_benefits["lotteimall_card_discount"] = _cd_amt
                card_benefits["lotteimall_card_label"] = (
                    auto_card_discount.get("label") or "카드"
                )

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

        # ★ 2026-06-25 — 실재고 3상태: 단일축(색 또는 사이즈 한 축)이면 itemInvQtyInfo
        #   (inv_qty)로 실수량 매핑. 단일색 상품은 inpOptList 1개라 사이즈가 color_text 에
        #   담기므로(기존 크롤러 특성), 옵션 라벨로 매핑한다.
        #   ★ 2026-06-28 — 2축(색×사이즈)도 itemInvQtyInfo(opt_val_cd_0·opt_val_cd_1)로
        #     조합별 실수량 매핑(라이브 검증: 롯데아이몰 색상모음전 97조합). 단축은 기존 size 매핑.
        _single_axis = not (color_names and size_names)
        size_qty_map = _build_inv_qty_by_size(soup, html) if _single_axis else {}
        cs_qty_map = {} if _single_axis else _build_inv_qty_by_color_size(soup, html)

        options: list[dict] = []
        for color in colors:
            for size in sizes:
                is_sold_out = bool(color["soldOut"] or size["soldOut"])
                # V7: option1 = color.name || productName
                color_text = color["name"] if color["name"] else product_name
                size_text = size["name"]
                # 사용자 정책 (2026-05-06): 품절=0 / 충분 재고=999 (표시 없음)
                #   ★ inv_qty 매핑 있으면 실수량(3상태). 2축=(색,사이즈) 조합 우선, 단축=size 라벨.
                _label = size_text if size_text else (color["name"] or "")
                _lbl_key = _SIZE_PAREN_PATTERN.sub("", _label).strip()
                _csk = (_SIZE_PAREN_PATTERN.sub("", (color["name"] or "")).strip(),
                        _SIZE_PAREN_PATTERN.sub("", (size_text or "")).strip())
                if cs_qty_map and _csk in cs_qty_map:
                    # 2축 조합별 실재고(0=품절·<5=실수량N·>=5=충분999). _lotteimall_disp_qty(사이트 JS 기준).
                    stock_int = _lotteimall_disp_qty(cs_qty_map[_csk])
                elif _lbl_key in size_qty_map:
                    # 단축 실재고(0=품절·<5=실수량N·>=5=충분999). _lotteimall_disp_qty(사이트 JS 기준).
                    stock_int = _lotteimall_disp_qty(size_qty_map[_lbl_key])
                else:
                    stock_int = 0 if is_sold_out else 999
                # ★ 2026-07-14 — 저장용 라벨에서 상태 꼬리표('(품절)'·'(N개 남음)') 제거.
                #   버그: 단품(단일색)은 사이즈가 color_text 에 담기는데(위 특성), 한정 사이즈는
                #   li 텍스트가 "250mm (2개 남음)" 이라 그대로 저장됐다. 매트릭스 매칭
                #   (_stk_digits = 모든 숫자 이어붙임)이 "250"+"2"="2502" 를 만들어 우리 사이즈
                #   "250" 과 불일치 → 그 사이즈만 '미크롤' 둔갑(품절은 괄호에 숫자없어 우연히 정상).
                #   재고 값(stock_int)은 이미 위에서 괄호 제거한 _lbl_key/_csk 로 정확히 뽑았으므로
                #   여기선 '저장 키'만 정리한다(값·품절판정에 영향 없음).
                _store_color = _SIZE_PAREN_PATTERN.sub("", color_text or "").strip()
                _store_size = _SIZE_PAREN_PATTERN.sub("", size_text or "").strip()
                # CrawlResult.price: V7 는 maxPrice 사용 (옵션 표시 가격)
                # 단, maxPrice 가 0 일 수 있으므로 V7 의 ``maxPrice || '-'`` 분기는
                # 본 모듈에서는 0 그대로 유지 (CrawlResult 스키마는 int).
                options.append({
                    "option_id": f"{product_id}|{_store_color}|{_store_size}",
                    "color_text": _store_color,
                    "size_text": _store_size,
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
                    # ★ 2026-07-18: 카드 청구할인 분리 보관(H몰 패턴). 표면가에 미반영.
                    **card_benefits,
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
            # ★ 2026-05-15 — 리뷰작성 적립금 (정액)
            r_label = point_rewards.get("review_label") or "리뷰작성 적립금"
            r_n = point_rewards.get("review_default") or 0
            r_l = point_rewards.get("review_club") or 0
            if r_l > 0 and r_n > 0:
                info_parts.append(f"{r_label} 일반 +{r_n:,}원 / L.CLUB +{r_l:,}원")
            elif r_l > 0:
                info_parts.append(f"{r_label} +{r_l:,}원")
            elif r_n > 0:
                info_parts.append(f"{r_label} +{r_n:,}원")

        return CrawlResult(
            source=self.source_name,
            product_url=product_url,
            product_name_raw=product_name,
            options=options,
            discount_info=" / ".join(info_parts),
            # [2026-07-23 M3] 소싱처 카테고리 경로 — 못 뽑으면 빈 문자열(추측 금지)
            category_path=_parse_category_path(soup),
            # [2026-07-23 M4-4] 이미지 URL·상세 HTML — 못 뽑으면 빈 값(추측 금지)
            image_urls=_parse_image_urls(soup, product_url),
            detail_html=_parse_detail_html(soup, product_url),
        )
