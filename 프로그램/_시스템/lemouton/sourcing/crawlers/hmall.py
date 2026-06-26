"""현대H몰 (hmall.com) 단품 크롤러 — SSR ``__NEXT_DATA__`` JSON 파서.

특징 (2026-06-25 라이브 실측):
  · 페이지는 Next.js SSR — 상품/옵션/재고/가격이 ``<script id="__NEXT_DATA__">`` 의
    ``props.pageProps.respData.itemPtc`` 에 통째로 박혀 옴(별도 XHR 없음).
  · 표면 노출가 = ``itemPtc.bbprc`` (깜짝할인 선반영가). 정가 = ``itemPtc.sellPrc``.
  · 옵션·재고 = ``itemPtc.stockList[]`` — 각 항목에 ``stockCount`` 로 **사이즈별 실재고
    수량**이 그대로 노출됨(0=품절). → 3단계 재고(품절/실수량/충분) 정확 포착.
  · 회원 전용 혜택(적립·카드 즉시할인 등)은 로그인 세션에서만 노출 → 확장 navGrab 이
    ``credentials:include`` 로 받은 로그인 HTML 의 __NEXT_DATA__ 를 파싱해야 정확.

수집 경로:
  · 라이브 = 크롬 확장 navGrab(로그인 브라우저) → POST /api/sources/parse → 이 parse_html.
  · 서버 단독 fetch = 비로그인 표면가/재고용(검증·폴백).

⚠️ 무결성: 크롤 실패·필드 부재 시 옛값/추정 금지. 못 읽으면 빈 옵션(정직한 '데이터 없음').
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

import requests
from bs4 import BeautifulSoup

from .base import AbstractCrawler, CrawlResult

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
DEFAULT_TIMEOUT = 20


def _to_int(v: Any) -> int:
    """문자열/숫자 → 정수(콤마 제거). 실패 시 0."""
    if v is None:
        return 0
    if isinstance(v, (int, float)):
        return int(v)
    m = re.search(r"-?\d[\d,]*", str(v))
    if not m:
        return 0
    try:
        return int(m.group(0).replace(",", ""))
    except ValueError:
        return 0


def _extract_next_data(html: str) -> Optional[dict]:
    """``<script id="__NEXT_DATA__">`` JSON 추출. 없으면 None."""
    soup = BeautifulSoup(html, "lxml")
    tag = soup.find("script", id="__NEXT_DATA__")
    if tag is None or not tag.string:
        # lxml 이 큰 JSON 을 .string 으로 안 줄 때 대비 — 정규식 폴백
        m = re.search(
            r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>',
            html, re.DOTALL,
        )
        if not m:
            return None
        raw = m.group(1)
    else:
        raw = tag.string
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


def _extract_slitm_cd(product_url: str) -> str:
    """URL 의 ``slitmCd`` 파라미터."""
    m = re.search(r"slitmCd=(\d+)", product_url or "")
    return m.group(1) if m else ""


def _color_from_name(name: str) -> str:
    """색상 축이 없을 때(단일색 단품) 상품명 마지막 토큰을 색상으로.

    예: '르무통 메이트 ... 운동화 다크네이비' → '다크네이비'.
    """
    parts = (name or "").strip().split(" ")
    return parts[-1] if parts else ""


def _opt_axes(row: dict) -> tuple[str, str]:
    """stockList 한 행 → (color_text, size_text).

    hmall 옵션 축:
      · 단일축(사이즈만, optFormItemYn='N') → uitm1AttrNm/uitmAttrNm = 사이즈, 색상 없음.
      · 2축(색×사이즈) → uitm1AttrNm = 1축, uitm2AttrNm = 2축.
    사이즈로 보이는 축(숫자+mm/숫자)을 size_text 로, 나머지를 color_text 로 분리.
    """
    a1 = (row.get("uitm1AttrNm") or row.get("uitmAttrNm") or "").strip()
    a2 = (row.get("uitm2AttrNm") or "").strip()

    def _is_size(t: str) -> bool:
        return bool(re.fullmatch(r"\d{2,3}\s*(mm|MM|호|cm|CM)?", t.strip()))

    if a2:
        # 2축 — 사이즈처럼 보이는 쪽을 size 로
        if _is_size(a2) and not _is_size(a1):
            return (a1, a2)
        if _is_size(a1) and not _is_size(a2):
            return (a2, a1)
        # 둘 다 모호 — 관례상 1축=색, 2축=사이즈
        return (a1, a2)
    # 단일축
    if _is_size(a1):
        return ("", a1)            # 색상은 호출부에서 상품명 폴백
    return (a1, "")


def _parse_hmall_benefits(soup: BeautifulSoup, surface_price: int) -> dict:
    """렌더된 혜택 DOM에서 적립(H.Point)·카드 즉시할인 추출.

    ⚠️ 혜택은 hmall 의 **클라이언트 렌더**라 서버 fetch(pre-JS) HTML 엔 없다(15KB 셸엔
       __NEXT_DATA__ 가격·재고만). **확장 navGrab(post-JS DOM, 105KB)** 일 때만 채워진다.
       못 읽으면 {} (옛값·추정 금지 — 무결성 원칙).

    반환 키(동적 혜택):
      hmall_point_amount   : 적립 H.Point 정액(원) — accrue(상시)
      hmall_card_label     : 카드 즉시할인 라벨(예: 'NH카드 5%')
      hmall_card_discount  : 카드 즉시할인액(표면가 − 카드적용가) — payment(조건부, 토글)
    """
    out: dict = {}
    try:
        text = soup.get_text(' ', strip=True)
    except Exception:
        return out
    if surface_price <= 0:
        return out
    # 적립 H.Point: "적립 기본 140P"
    m_p = re.search(r'기본\s*([\d,]+)\s*P', text)
    if m_p:
        amt = _to_int(m_p.group(1))
        if 0 < amt < surface_price * 0.4:          # 가드: 표면가 40% 미만만 채택
            out['hmall_point_amount'] = amt
    # 카드 즉시할인: "NH카드5% 120,555원" (즉시 할인 영역)
    m_c = re.search(r'([가-힣A-Z]{1,8}카드)\s*(\d+)\s*%[\s\S]{0,20}?([\d,]{4,})\s*원', text)
    if m_c:
        card_price = _to_int(m_c.group(3))
        if 0 < card_price < surface_price:         # 가드: 카드가 < 표면가
            out['hmall_card_label'] = f"{m_c.group(1)} {m_c.group(2)}%"
            out['hmall_card_discount'] = surface_price - card_price  # 즉시할인액
    return out


class HmallCrawler(AbstractCrawler):
    """현대H몰 단품 크롤러 (SSR __NEXT_DATA__ 파서)."""

    source_name = "hmall"

    def fetch(self, product_url: str) -> CrawlResult:
        """서버 단독 fetch(비로그인). 라이브 정확 수집은 확장 navGrab → parse_html 경로."""
        resp = requests.get(
            product_url,
            headers={"User-Agent": USER_AGENT, "Accept-Language": "ko-KR,ko;q=0.9"},
            timeout=DEFAULT_TIMEOUT,
        )
        resp.raise_for_status()
        return self.parse_html(resp.text, product_url)

    def parse_html(self, html: str, product_url: str) -> CrawlResult:
        """확장/서버가 받은 HTML 의 __NEXT_DATA__ → CrawlResult (네트워크 없음)."""
        data = _extract_next_data(html)
        if not data:
            raise RuntimeError("[hmall] __NEXT_DATA__ 없음 — 파싱 실패")

        try:
            it = data["props"]["pageProps"]["respData"]["itemPtc"]
        except (KeyError, TypeError):
            it = None

        if not isinstance(it, dict):
            # 판매중단/비정상 페이지 — 정직한 '데이터 없음'(옛값 금지)
            logger.warning("[hmall] itemPtc 없음(판매중단 등). url=%s", product_url)
            return CrawlResult(
                source=self.source_name,
                product_url=product_url,
                product_name_raw="",
                options=[],
                brand="",
                discount_info="크롤 실패: 상품 데이터 없음",
            )

        slitm_cd = _extract_slitm_cd(product_url) or str(it.get("slitmCd") or "")
        product_name = (it.get("slitmNm") or "").strip()
        brand = (it.get("brndNm") or "").strip()
        sell_prc = _to_int(it.get("sellPrc"))      # 정가
        bbprc = _to_int(it.get("bbprc"))           # 표면 노출가(깜짝할인 선반영)
        surface_price = bbprc or sell_prc          # bbprc 우선, 없으면 정가
        discount_rate = 0
        if sell_prc > 0 and 0 < surface_price < sell_prc:
            discount_rate = round((sell_prc - surface_price) / sell_prc * 100)

        # 혜택(적립·카드) — 렌더된 DOM 에 있을 때만(확장 navGrab post-JS). 서버 fetch 엔 부재.
        benefits = _parse_hmall_benefits(BeautifulSoup(html, "lxml"), surface_price)

        fallback_color = _color_from_name(product_name)
        stock_list = it.get("stockList") or []
        options: list[dict] = []
        for row in stock_list:
            if not isinstance(row, dict):
                continue
            color_text, size_text = _opt_axes(row)
            if not color_text:
                color_text = fallback_color
            opt_prc = _to_int(row.get("sellPrc"))
            price = opt_prc if opt_prc > 0 else surface_price
            stock = _to_int(row.get("stockCount"))
            uitm_cd = str(row.get("uitmCd") or "")
            options.append({
                "option_id": f"{slitm_cd}|{color_text}|{size_text}|{uitm_cd}",
                "color_text": color_text,
                "size_text": size_text,
                "price": price,
                "sale_price": price,
                "stock": stock,             # stockCount 실수량(0=품절). 999 둔갑 없음.
                **benefits,                 # 동적 혜택(있을 때만) — 옵션마다 동일 값
            })

        # 옵션이 비었으나 상품은 살아있는 단일 SKU(stockList 부재) → 단일 행 폴백.
        #   soldout 플래그로 품절 여부만 반영(수량 미상이면 999=충분 센티넬은 쓰지 않고
        #   실패로 두지 않기 위해 품절 아닐 때만 단일행, 수량은 모름 → 0 아님).
        if not options and surface_price > 0:
            is_sold = bool(it.get("soldout"))
            options.append({
                "option_id": f"{slitm_cd}|{fallback_color}|",
                "color_text": fallback_color,
                "size_text": "",
                "price": surface_price,
                "sale_price": surface_price,
                "stock": 0 if is_sold else 999,
            })

        return CrawlResult(
            source=self.source_name,
            product_url=product_url,
            product_name_raw=product_name,
            options=options,
            brand=brand,
            discount_info=(f"깜짝할인 {discount_rate}%" if discount_rate else ""),
        )
