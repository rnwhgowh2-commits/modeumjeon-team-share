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

# 현대H몰 사이즈별 실재고 API(공개 — 로그인 불필요, www 호스트). 모음전(2축) 전용.
HMALL_STOCKCOUNT_URL = "https://www.hmall.com/api/hf/dp/v1/item-ptc/item-stockcount"


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


# ── 현대H몰 모음전(2축 색×사이즈) 사이즈별 실재고 — item-stockcount API ──────────────
#   배경(2026-06-29 라이브 역공학, [[reference_hmall_stockcount_api]]):
#     · 모음전(uitmCombYn="Y")은 페이지 __NEXT_DATA__ 에 1축(색)만 옴 → 색별 합계뿐.
#       사이즈별 실재고는 색을 고를 때 item-stockcount(uitmAttrTypeSeq=2) 로만 온다.
#     · ⚠️ uitmSeq 는 '색 위치'가 아니라 비순차 내부 ID(예: 블랙1·…·올리브6·크림핑크18·
#       아이보리21·스카이블루22). 페이지·색목록 어디에도 진짜 uitmSeq 가 안 나온다(전부 0)
#       → 1..N 순회는 7번째+ 색을 놓치고, 중간 seq 는 MIX(여러색×한사이즈) 쓰레기를 준다.
#       해법 = 프로브: uitmSeq 를 훑되 '단일 색 + 전부 사이즈' 응답만 채택(색으로 dedup).
#     · ⚠️ 품절판정 = sellGbcd("00"=판매중 / 그 외 "11"=품절). 품절 사이즈도 stockCount=1
#       센티넬을 주므로 stockCount 만 보면 '1개 있음' 둔갑(거짓 재고=금전손실). sellGbcd 우선.
#     · API 는 공개(로그인 불필요·credentials 없이 200) → 서버사이드 호출 가능(확장 불요).


def _stockcount_params(slitm_cd: str, attr_type: int, uitm_seq: int) -> dict:
    """item-stockcount 쿼리 파라미터(검증된 보일러플레이트)."""
    return {
        "slitmCd": slitm_cd, "setItemYn": "N", "uitmCombYn": "Y",
        "uitmAttrTypeSeq": str(attr_type), "selectBoxIdx": "1",
        "uitmSeq": str(uitm_seq), "rishpNotfExpsYn": "Y",
        "befUitmSeq1": "0", "befUitmSeq2": "0", "befUitmSeq3": "0",
        "setSlitmCd": slitm_cd, "setSlitmYn": "N",
    }


def _size_stock_from_row(row: dict) -> int:
    """stockList 한 행 → 사이즈 실재고(3상태). sellGbcd!='00' 이면 품절(0).

    sellGbcd 없을 때만 stockCount 폴백(거짓 품절 방지). 품절(=00 아님)일 때 stockCount(=1
    센티넬)는 무시하고 0.
    """
    gb = str(row.get("sellGbcd") or "").strip()
    if gb and gb != "00":
        return 0
    return _to_int(row.get("stockCount"))


def build_combo_persize_options(
    slitm_cd: str,
    size_responses: dict[int, list],
    color_price: dict[str, int],
    fallback_price: int = 0,
) -> list[dict]:
    """순수 변환(네트워크 없음 — 단위테스트 대상).

    size_responses: {uitmSeq: stockList(uitmAttrTypeSeq=2 응답)}.
    '단일 색 + 모든 행에 사이즈(uitm2AttrNm)' 인 응답만 채택(MIX cross-color 버림),
    색 이름으로 dedup, 사이즈별 stock 은 sellGbcd 로 3상태. 색→가격은 color_price.
    """
    found: dict[str, list] = {}
    for seq in sorted(size_responses):
        rows = size_responses.get(seq) or []
        if not rows:
            continue
        colset = {(r.get("uitm1AttrNm") or "").strip() for r in rows if isinstance(r, dict)}
        if len(colset) != 1:
            continue                                   # MIX(여러 색) → 쓰레기, 버림
        if not all((r.get("uitm2AttrNm") or "").strip() for r in rows):
            continue                                   # 사이즈 축 아님(색목록 등) → 버림
        color = next(iter(colset))
        if not color or color in found:
            continue
        sizes = []
        for r in rows:
            size = (r.get("uitm2AttrNm") or "").strip()
            if size:
                sizes.append((size, _size_stock_from_row(r)))
        if sizes:
            found[color] = sizes
    options: list[dict] = []
    for color, sizes in found.items():
        price = color_price.get(color) or fallback_price
        for size, stock in sizes:
            options.append({
                "option_id": f"{slitm_cd}|{color}|{size}|",
                "color_text": color,
                "size_text": size,
                "price": price,
                "sale_price": price,
                "stock": stock,
            })
    return options


def fetch_combo_persize_options(
    product_url: str, timeout: int = DEFAULT_TIMEOUT, max_seq: int = 30,
) -> Optional[list[dict]]:
    """현대H몰 모음전(2축) 사이즈별 3상태 옵션을 서버사이드로 수집.

    단품/비콤보(uitmCombYn != "Y")거나 수집 실패면 None → 호출부는 기존 옵션 유지
    (데이터 파괴 금지). 성공 시 per-(색,사이즈,재고,가격) 옵션 리스트.
    """
    slitm_cd = _extract_slitm_cd(product_url)
    if not slitm_cd:
        return None
    sess = requests.Session()
    ua = {"User-Agent": USER_AGENT, "Accept-Language": "ko-KR,ko;q=0.9"}
    # 1) 페이지 → uitmCombYn·색별 가격·색 개수·표면가
    try:
        page = sess.get(product_url, headers=ua, timeout=timeout)
        page.raise_for_status()
        data = _extract_next_data(page.text)
        it = data["props"]["pageProps"]["respData"]["itemPtc"]
    except Exception:
        return None
    if not isinstance(it, dict) or str(it.get("uitmCombYn") or "") != "Y":
        return None                                    # 단품/비콤보 → 페이지 파싱 옵션 사용
    surface = _to_int(it.get("bbprc")) or _to_int(it.get("sellPrc"))
    color_rows = it.get("stockList") or []
    color_price: dict[str, int] = {}
    for cr in color_rows:
        if not isinstance(cr, dict):
            continue
        c = (cr.get("uitm1AttrNm") or cr.get("uitmAttrNm") or "").strip()
        if c:
            color_price[c] = _to_int(cr.get("bbprc")) or _to_int(cr.get("sellPrc")) or surface
    expected = len(color_price) or len(color_rows)
    # 2) 프로브: uitmSeq 1..max_seq, 단일색 응답이 expected 개 모이면 종료
    api_headers = dict(ua, **{"Accept": "application/json", "Referer": product_url})
    responses: dict[int, list] = {}
    found_colors: set[str] = set()
    empties = 0
    for seq in range(1, max_seq + 1):
        try:
            r = sess.get(HMALL_STOCKCOUNT_URL, params=_stockcount_params(slitm_cd, 2, seq),
                         headers=api_headers, timeout=timeout)
            sl = ((r.json() or {}).get("respData") or {}).get("stockList") or []
        except Exception:
            sl = []
        responses[seq] = sl
        if not sl:
            empties += 1
        else:
            empties = 0
            cset = {(x.get("uitm1AttrNm") or "").strip() for x in sl if isinstance(x, dict)}
            if len(cset) == 1 and all((x.get("uitm2AttrNm") or "").strip() for x in sl):
                found_colors.add(next(iter(cset)))
        if expected and len(found_colors) >= expected:
            break
        if empties >= 8:
            break
    opts = build_combo_persize_options(slitm_cd, responses, color_price, surface)
    return opts or None
