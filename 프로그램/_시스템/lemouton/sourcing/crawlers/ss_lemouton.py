"""스마트스토어 (네이버) 르무통 셀러 페이지 크롤러 — NEW.

V7 (Chrome extension) 에는 없는 신규 크롤러. 본 모듈은 V7 포팅이 아닌
실 페이지 R&D 결과로 채택한 패턴이다.

R&D 요약 (2026-04 시점):
  1. ``https://smartstore.naver.com/{seller}/products/{id}`` 직접 GET 은 비로그인
     상태에서 Naver SSO 로그인 페이지로 강제 리디렉트된다 (응답 ``nidlogin.login``).
  2. 동일 상품을 가리키는 브랜드 셀러 도메인 ``https://brand.naver.com/{seller}/products/{id}``
     은 비로그인 200 OK + 상품 HTML 을 반환한다.
  3. 그 HTML 에는 ``<script>window.__PRELOADED_STATE__ = {...}</script>`` 형태로
     상품 메타가 inline 되어 있다 (Next.js 류의 SSR state hydration).
  4. SKU 단위 (색상 × 사이즈) 재고는 별도 XHR 로 로드되며 (``/i/v1/...``) ,
     비로그인 + non-browser 환경에서는 429 / WAF 페이지를 받는다.
     → 실 브라우저 자동화 없이는 SKU 단위 재고를 받기 어렵다.
  5. 따라서 본 크롤러는 inline state 의 ``simpleProductForDetailPage.A`` 만 사용한다.
     - 상품명: ``name``
     - 가격:   ``salePrice`` (할인 적용 후 노출가)
     - 옵션:   ``optionStandards`` — ``optionGroupName`` ('색상' / '사이즈') 별
              ``optionName`` 목록 (group definitions)
     - 재고:   상품 전체 ``stockQuantity`` 와 ``productStatusType`` /
              ``channelProductDisplayStatusType`` / ``soldout`` 신호.

구현 결정 (a/b/c 중 'a'):
  (a) inline ``window.__PRELOADED_STATE__`` JSON 파싱.
  (b) HTML 표준 셀렉터 — 옵션 패널이 클라이언트 렌더되어 raw HTML 에 노출되지 않음 → 부적합.
  (c) Naver Commerce API 직접 호출 — 비로그인 + 비브라우저 차단 (WAF) → 부적합.

URL 정규화:
  - ``smartstore.naver.com/{seller}/products/{id}`` → 동일 ``brand.naver.com``
    호스트로 swap 후 GET (브랜드 스토어가 아닐 경우 fail-fast 는 호출자 책임).
  - 그 외 (이미 brand.naver.com) 은 그대로 사용.

SKU stock 한계 (Concerns):
  - inline state 는 상품 합계 stockQuantity 만 제공.
  - 본 크롤러는 다음 매핑을 사용 (다른 크롤러의 '재고있음/품절' binary 와 일관):
      * 상품 전체 soldout (productStatusType != 'SALE' or stockQuantity == 0)
        → 모든 옵션 행 stock=0
      * 그 외 → 모든 옵션 행 stock=1 (단품 케이스에서는 stockQuantity)
  - SKU 별 미세 재고/품절 정보가 필요해질 경우, 향후 별도 task 에서
    Selenium / Playwright 기반 옵션 클릭 자동화 또는 인증된 commerce API 사용을
    검토. (T13 musinsa 의 inventories API 와 동등한 신호 출처 필요.)
"""
from __future__ import annotations

import json
import re
from typing import Optional
from urllib.parse import urlparse, urlunparse

from curl_cffi import requests as cffi_requests

from .base import AbstractCrawler, CrawlResult


# ─────────────────────────────────────────────────────────────
# 상수
# ─────────────────────────────────────────────────────────────
DEFAULT_TIMEOUT = 30
IMPERSONATE = "chrome120"  # 다른 크롤러와 동일 (T11/T12/T13)

# R&D: 비로그인 GET 시 brand.naver.com 만 200, smartstore.naver.com 은 로그인 리다이렉트.
SMARTSTORE_HOST = "smartstore.naver.com"
BRAND_HOST = "brand.naver.com"

# /products/{ID} 패턴 (호스트 무관)
PRODUCT_ID_PATTERN = re.compile(r"/products/(\d+)")

# window.__PRELOADED_STATE__ = { ... };</script>
PRELOADED_STATE_PATTERN = re.compile(
    r"window\.__PRELOADED_STATE__\s*=\s*(.+?)</script>",
    re.DOTALL,
)

# inline state 에는 JSON 외 JS 리터럴 ``undefined`` 가 섞여 들어옴 → null 로 치환.
# 식별자/문자열 내부 'undefined' (예: ``"isUndefined"``, ``"undefined_field"``) 는
# 영숫자/언더스코어/따옴표 경계로 보호한다.
JS_UNDEFINED_PATTERN = re.compile(r"(?<![\w\"])undefined(?![\w\"])")


# ─────────────────────────────────────────────────────────────
# URL 정규화
# ─────────────────────────────────────────────────────────────
def _normalize_url(product_url: str) -> str:
    """smartstore.naver.com → brand.naver.com 으로 swap.

    R&D: smartstore.naver.com 은 비로그인 GET 시 nidlogin 으로 리다이렉트되어
    상품 HTML 을 받지 못한다. 동일 (seller, id) 가 brand.naver.com 에서
    200 OK 로 응답하므로 호스트만 교체.
    """
    parsed = urlparse(product_url)
    if parsed.netloc == SMARTSTORE_HOST:
        # netloc 만 변경, path/query 는 그대로
        return urlunparse(parsed._replace(netloc=BRAND_HOST))
    return product_url


def _extract_product_id(product_url: str) -> str:
    m = PRODUCT_ID_PATTERN.search(product_url)
    return m.group(1) if m else ""


# ─────────────────────────────────────────────────────────────
# __PRELOADED_STATE__ 파싱
# ─────────────────────────────────────────────────────────────
def _extract_preloaded_state(html: str) -> Optional[dict]:
    """``window.__PRELOADED_STATE__ = {...};`` JSON 추출.

    - 끝의 ``;`` 제거
    - JS ``undefined`` 리터럴 → ``null``
    - 추출 실패 / 파싱 실패 시 None.
    """
    m = PRELOADED_STATE_PATTERN.search(html)
    if not m:
        return None
    raw = m.group(1).strip()
    if raw.endswith(";"):
        raw = raw[:-1]
    fixed = JS_UNDEFINED_PATTERN.sub("null", raw)
    try:
        return json.loads(fixed)
    except (json.JSONDecodeError, ValueError):
        return None


def _is_soldout(simple_a: dict) -> bool:
    """상품 전체 soldout 판정.

    R&D 신호:
      - productStatusType: 'SALE' 외 (예: 'OUTOFSTOCK') → 품절
      - channelProductDisplayStatusType: 'ON' 외 (예: 'SUSPEND') → 품절
      - stockQuantity == 0 → 품절
      - soldout: True (있으면 우선)
    """
    if simple_a.get("soldout") is True:
        return True
    status = simple_a.get("productStatusType")
    if status and status != "SALE":
        return True
    disp = simple_a.get("channelProductDisplayStatusType")
    if disp and disp != "ON":
        return True
    qty = simple_a.get("stockQuantity")
    if isinstance(qty, int) and qty <= 0:
        return True
    return False


def _split_option_groups(option_standards: list[dict]) -> tuple[list[str], list[str]]:
    """optionStandards → (colors, sizes).

    optionStandards 항목 형태:
      {"optionGroupName": "색상", "optionName": "블랙", ...}
      {"optionGroupName": "사이즈", "optionName": "230", ...}

    그룹 이름이 '색상' / '사이즈' 이외 (예: '단일사이즈') 인 경우 본 모듈은
    첫 번째 그룹을 colors, 두 번째 그룹을 sizes 로 위치 기반 매핑 (다른 크롤러
    포팅 결과와 일관: option1=색상, option2=사이즈).
    """
    by_group: dict[str, list[str]] = {}
    group_order: list[str] = []
    for opt in option_standards:
        gname = opt.get("optionGroupName") or ""
        oname = opt.get("optionName") or ""
        if not oname:
            continue
        if gname not in by_group:
            by_group[gname] = []
            group_order.append(gname)
        by_group[gname].append(oname)

    # 한국어 그룹명 우선 (색상 / 사이즈), 없으면 위치 기반
    colors: list[str] = []
    sizes: list[str] = []
    if "색상" in by_group:
        colors = by_group["색상"]
    if "사이즈" in by_group:
        sizes = by_group["사이즈"]

    if not colors and not sizes:
        # 위치 기반: 첫 그룹 = colors, 두 번째 그룹 = sizes
        if len(group_order) >= 1:
            colors = by_group[group_order[0]]
        if len(group_order) >= 2:
            sizes = by_group[group_order[1]]
    elif not sizes and len(group_order) >= 2:
        # 색상은 매칭됐는데 사이즈 그룹명이 다른 경우 (예: '치수')
        for g in group_order:
            if g != "색상":
                sizes = by_group[g]
                break
    elif not colors and len(group_order) >= 2:
        for g in group_order:
            if g != "사이즈":
                colors = by_group[g]
                break

    return colors, sizes


# ─────────────────────────────────────────────────────────────
# Crawler
# ─────────────────────────────────────────────────────────────
class SsLemoutonCrawler(AbstractCrawler):
    """스마트스토어 르무통 셀러 페이지 크롤러 (NEW — V7 미지원).

    URL 패턴:
      - https://smartstore.naver.com/lemouton/products/{ID}  (자동 brand 호스트로 swap)
      - https://brand.naver.com/lemouton/products/{ID}
    """

    source_name = "ss_lemouton"

    def __init__(self, timeout: int = DEFAULT_TIMEOUT):
        self.timeout = timeout

    def _fetch_html(self, product_url: str) -> str:
        resp = cffi_requests.get(
            product_url,
            impersonate=IMPERSONATE,
            timeout=self.timeout,
            allow_redirects=True,
        )
        resp.raise_for_status()
        return resp.text

    def fetch(self, product_url: str) -> CrawlResult:
        normalized_url = _normalize_url(product_url)
        product_id = _extract_product_id(normalized_url)

        html = self._fetch_html(normalized_url)
        state = _extract_preloaded_state(html)
        if state is None:
            # 파싱 실패 — 빈 결과 반환 (호출자가 fail-fast 결정)
            return CrawlResult(
                source=self.source_name,
                product_url=product_url,
                product_name_raw="",
                options=[],
            )

        simple = (state.get("simpleProductForDetailPage") or {}).get("A") or {}

        product_name = simple.get("name") or simple.get("dispName") or ""

        # ★ 2026-05-13 수정 (사용자 확정 정책):
        #   "할인가 (크롤링 기준)" = 비회원 표시 할인가 (즉시할인 적용 후).
        #   __PRELOADED_STATE__ 의 benefitsView.discountedSalePrice 가 표시 할인가와
        #   1:1 일치 (예: 117,900). 이전 R&D 의 "discountedSalePrice 가 0 이라
        #   salePrice 우선" 결론은 다른 경로의 동명 필드 (channelProductMigration 등)
        #   를 본 것이며, simpleProductForDetailPage.A.benefitsView.discountedSalePrice
        #   는 항상 채워진다.
        benefits_view = simple.get("benefitsView") or {}
        sale_price = int(
            benefits_view.get("discountedSalePrice")
            or benefits_view.get("mobileDiscountedSalePrice")
            or benefits_view.get("dispDiscountedSalePrice")
            or 0
        )
        original_price = int(simple.get("salePrice") or 0)  # 정가 (149,000)

        # ★ 2026-05-15 재수정 (정정된 산식 — 사이트 실제 표시값 매칭):
        #   네이버 브랜드몰 상품 상세의 "최대 적립 포인트" 박스를 클릭하면 노출되는
        #   breakdown 의 "최대 리뷰적립" 행 (예: 5,000원) 과 1:1 일치하는 산식은
        #   다음과 같다 (Playwright 로 popup 렌더 + DOM dump 검증, 2026-05-15):
        #
        #     "최대 리뷰적립" = photoVideoReviewPoint
        #                    + afterUsePhotoVideoReviewPoint
        #                    + managerPhotoVideoReviewPoint
        #                    + managerAfterUsePhotoVideoReviewPoint
        #
        #     검증 예 (상품 9496367527, 르무통 워크):
        #       photoVideoReviewPoint           = 2,850
        #       afterUsePhotoVideoReviewPoint   = 2,000
        #       managerPhotoVideoReviewPoint    =   150
        #       managerAfterUsePhotoVideoReviewPoint = 0
        #       합계 = 5,000원 → 사이트 표시값 "최대 리뷰적립 5,000원" 과 일치 ✓
        #
        #   이전 산식 (photoVideo + afterPhoto 만) 은 4,850 으로 manager(스토어매니저)
        #   추가 적립분 150원을 빠뜨려 잘못된 값을 반환했다. 사용자 정정 반영.
        #
        #   필드 의미 (한국어):
        #     - textReviewPoint: 텍스트 리뷰 작성 시 셀러 적립 (1,950)
        #     - photoVideoReviewPoint: 포토/동영상 리뷰 작성 시 셀러 적립 (2,850)
        #     - afterUseTextReviewPoint: 한달 사용 후 텍스트 리뷰 셀러 적립 (1,000)
        #     - afterUsePhotoVideoReviewPoint: 한달 사용 후 포토/동영상 셀러 적립 (2,000)
        #     - managerTextReviewPoint: 텍스트 리뷰 시 스토어매니저(네이버) 추가 (50)
        #     - managerPhotoVideoReviewPoint: 포토/동영상 리뷰 시 매니저 추가 (150)
        #     - managerAfterUseTextReviewPoint: 한달 사용 텍스트 매니저 추가 (0)
        #     - managerAfterUsePhotoVideoReviewPoint: 한달 사용 포토/동영상 매니저 추가 (0)
        #
        #   사이트 표시 "최대 리뷰적립" 은 **포토/동영상 경로** + **매니저 추가분 포함**.
        #   포토/동영상 미운영(0/0) 상품은 텍스트 경로로 폴백.
        photo_video_rp = int(benefits_view.get("photoVideoReviewPoint") or 0)
        text_rp = int(benefits_view.get("textReviewPoint") or 0)
        after_pv_rp = int(benefits_view.get("afterUsePhotoVideoReviewPoint") or 0)
        after_text_rp = int(benefits_view.get("afterUseTextReviewPoint") or 0)
        mgr_pv_rp = int(benefits_view.get("managerPhotoVideoReviewPoint") or 0)
        mgr_text_rp = int(benefits_view.get("managerTextReviewPoint") or 0)
        mgr_after_pv_rp = int(benefits_view.get("managerAfterUsePhotoVideoReviewPoint") or 0)
        mgr_after_text_rp = int(benefits_view.get("managerAfterUseTextReviewPoint") or 0)
        # 사이트 "최대 리뷰적립" 산식: 포토/동영상 4-field 합산 (매니저 포함). 없으면 텍스트.
        if photo_video_rp > 0 or after_pv_rp > 0 or mgr_pv_rp > 0 or mgr_after_pv_rp > 0:
            review_point_max = (
                photo_video_rp + after_pv_rp + mgr_pv_rp + mgr_after_pv_rp
            )
        else:
            review_point_max = (
                text_rp + after_text_rp + mgr_text_rp + mgr_after_text_rp
            )

        # discount_info 텍스트 (혜택 명목, 사람이 읽을 용도; 자동 계산엔 미사용).
        discount_info_parts: list[str] = []
        if review_point_max > 0:
            discount_info_parts.append(f"리뷰 적립금 최대 {review_point_max:,}원")
        seller_immediate = int(benefits_view.get("sellerImmediateDiscountAmount") or 0)
        if seller_immediate > 0:
            discount_info_parts.append(f"즉시할인 {seller_immediate:,}원")
        discount_info_text = " / ".join(discount_info_parts)

        # Fail-safe — 둘 다 0 이면 크롤링 자체 실패 (가격 0 저장 절대 금지)
        if sale_price <= 0 and original_price <= 0:
            raise RuntimeError(
                f"[ss_lemouton] 가격 추출 실패 (benefitsView/salePrice 모두 0) — Fail-safe"
            )
        # benefitsView 비면 정가를 sale_price 로 폴백 (정상가만 노출되는 상품)
        if sale_price <= 0:
            sale_price = original_price

        soldout = _is_soldout(simple)
        total_stock = simple.get("stockQuantity") or 0
        if not isinstance(total_stock, int):
            try:
                total_stock = int(total_stock)
            except (TypeError, ValueError):
                total_stock = 0

        option_standards = simple.get("optionStandards") or []
        colors, sizes = _split_option_groups(option_standards)

        # 다른 크롤러와 동일 규약: 색상/사이즈 비면 단일 빈 항목으로 카르테시안 1행
        if not colors:
            colors = [""]
        if not sizes:
            sizes = [""]

        # 단품 케이스 (옵션 행 1개) 판정 — V7 SSF/lotte 와 동일 규약
        is_single_row = len(colors) == 1 and colors[0] == "" and len(sizes) == 1 and sizes[0] == ""

        options: list[dict] = []
        for color in colors:
            for size in sizes:
                if soldout:
                    stock_int = 0
                elif is_single_row:
                    # 단품: 상품 전체 stockQuantity 노출 (상한 없음)
                    stock_int = max(int(total_stock), 0)
                else:
                    # 옵션 다중: SKU 단위 정보가 없으므로 '재고있음' 센티넬 매핑.
                    # 999 = 재고있음(수량 미상) — 타 소싱처와 통일 (기존 1 → 오해 소지로 변경).
                    stock_int = 999
                options.append({
                    "option_id": f"{product_id}|{color}|{size}",
                    "color_text": color,
                    "size_text": size,
                    # 혜택 정책 미정 (사용자 추가 예정) — price = sale_price pass-through
                    "price": sale_price,
                    "sale_price": sale_price,        # 표시 할인가 (UI matrix 가 우선 사용)
                    "original_price": original_price,  # 정가 (149,000) — 정보용
                    "stock": stock_int,
                    # ★ 2026-05-14 추가: 변동 리뷰 적립금 (원, 사이트 "최대 적립 포인트").
                    # SKU 단위 차등 정보는 inline state 에 없으므로 모든 옵션 동일 값.
                    # option_benefit_overrides 시드 갱신 운영용 (DB 변경은 본 크롤러 범위 밖).
                    "review_point_max": review_point_max,
                })

        return CrawlResult(
            source=self.source_name,
            product_url=product_url,
            product_name_raw=product_name,
            options=options,
            discount_info=discount_info_text,
        )
