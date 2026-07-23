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

카테고리(빵부스러기) 부재 — 2026-07-23 M3 실측 결론:
  · PDP(``/md/pda/itemPtc?slitmCd=``)에는 빵부스러기가 **없다**. SSR ``__NEXT_DATA__``
    (13KB)에도, 실브라우저로 끝까지 렌더한 DOM(108KB)에도 카테고리 '이름'이 한 곳도
    없다 — breadcrumb 마크업·JSON-LD BreadcrumbList·og/section 메타·카테고리 링크
    전부 0건(셀렉터 탐색으로 확인).
  · 있는 건 ``itemPtc.itemDScfCd``(예: ``"39040802"``) 숫자 분류코드뿐이고, 코드→이름
    사전을 주는 공개 경로를 못 찾았다(``item-ctg`` 류 404, ``item-ptc`` API 는 401).
  · 따라서 ``CrawlResult.category_path`` 는 **빈 문자열 = 카테고리 확인불가**로 둔다.
    코드를 이름인 척 넣거나 상품명에서 추측하지 않는다(무결성 원칙).
    회귀 핀: ``tests/sources/test_crawler_category_path.py``
    ``test_현대H몰은_빵부스러기가_없어_빈문자열이다``.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

import requests
from bs4 import BeautifulSoup

from .base import (
    AbstractCrawler, CrawlResult, build_image_urls, sanitize_detail_html,
)

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
DEFAULT_TIMEOUT = 20

# 현대H몰 사이즈별 실재고 API(공개 — 로그인 불필요, www 호스트). 모음전(2축) 전용.
HMALL_STOCKCOUNT_URL = "https://www.hmall.com/api/hf/dp/v1/item-ptc/item-stockcount"
# [2026-07-23 M4-4] 상세설명(셀러 HTML) API — 공개(로그인 불필요). 사유는 fetch_detail_html.
HMALL_ITEM_DTL_URL = "https://www.hmall.com/api/hf/dp/v1/item-ptc/item-dtl"


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


# ─────────────────────────────────────────────────────────────
# [2026-07-23 M4-4] 이미지 (현대H몰)
# ─────────────────────────────────────────────────────────────
HMALL_IMG_HOST = "https://image.hmall.com"


def _hmall_static_bucket(slitm_cd: str) -> str:
    """상품코드 → 이미지 CDN 의 4단 버킷 경로. 규칙을 못 세우면 빈 문자열.

    현대H몰 대표사진 주소는 이렇게 생겼다(실측)::

        https://image.hmall.com/static/4/4/89/25/2225894478_0.jpg
                                └ 버킷 ┘  └ orglImgNm ┘

    버킷은 상품코드(10자리)에서 **자리로 잘라 만든다**::

        seg1 = cd[-3]     seg2 = cd[-4]     seg3 = cd[-6:-4]     seg4 = cd[-8:-6]
        2225894478 → 4 / 4 / 89 / 25          ✔ 위 실주소와 일치

    ★ 추측이 아니라 실측이다 — 2026-07-23 라이브 검색결과 페이지에서 **상품 31건**의
      (상품코드, 실제 버킷경로) 쌍을 뽑아 전수 대조했고 **31/31 일치, 불일치 0**.
      조립한 주소 3건을 HEAD 로 찍어 전부 ``200 image/jpeg`` 확인
      (존재하지 않는 번호 `_9.jpg` 는 404 를 준다 = 아무 주소나 200 이 아니다).

    상품코드가 10자리 숫자가 아니면 빈 문자열(조립 금지).
    """
    cd = str(slitm_cd or "").strip()
    if not (cd.isdigit() and len(cd) >= 8):
        return ""
    return f"{cd[-3]}/{cd[-4]}/{cd[-6:-4]}/{cd[-8:-6]}"


def _parse_image_urls(it: dict, slitm_cd: str, product_url: str) -> list[str]:
    """[2026-07-23 M4-4] 현대H몰 상품 이미지 URL 목록. 못 만들면 빈 리스트.

    ★ **HTML 에는 상품 사진이 한 장도 없다.** PDP 원문(13KB 스켈레톤)에는 `<img>` 가
      0개, `og:image` 도 없다(2026-07-23 실측 — `og:` 는 type/title/description/url 뿐).
      실화면 사진은 JS 가 `__NEXT_DATA__` 의 파일명으로 **주소를 조립**해 넣는다.
      우리도 같은 조립을 한다: `HMALL_IMG_HOST/static/{버킷}/{orglImgNm}`.

    ★ 안전장치 — 파일명이 상품코드로 시작할 때만 만든다. 실측된 표준 이름은
      `{slitmCd}_0.jpg` 이고(=`itemBaseImgNm` 과 동일), 그 밖의 이름은 버킷 규칙이
      성립하는지 확인된 바 없으므로 **조립하지 않는다**(엉뚱한 사진 = 오등록).

    ★ 추가 사진 — 이 상품은 `_0` 한 장뿐이다(화면 갤러리도 같은 사진의 크기 변형만
      돌린다). `enlg1ImgNm`·`enlg2ImgNm`(확대컷)이 채워진 상품은 그것도 담는다.
      `_1`·`_2` … 로 **번호를 훑지 않는다** — 없는 번호는 404 라 확인은 되지만,
      그건 네트워크 호출이고 순수 파서가 할 일이 아니다(추측 금지).

    ★ 지재권 — URL 문자열만 만든다. 파일은 내려받지 않는다.
    """
    bucket = _hmall_static_bucket(slitm_cd)
    if not bucket:
        return []
    cands: list[str] = []
    for key in ("orglImgNm", "itemBaseImgNm", "enlg1ImgNm", "enlg2ImgNm"):
        name = str(it.get(key) or "").strip()
        if not name or "/" in name:
            continue
        if not name.startswith(str(slitm_cd)):
            continue          # 표준 이름이 아니면 버킷 규칙을 확신할 수 없다 → 조립 금지
        cands.append(f"{HMALL_IMG_HOST}/static/{bucket}/{name}")
    return build_image_urls(cands, product_url)


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
        res = self.parse_html(resp.text, product_url)
        # [2026-07-23 M4-4] 상세설명은 HTML 이 아니라 별도 API 에만 있다(사유는
        #   fetch_detail_html). 크롤 경로이므로 여기서 한 번 더 받는다 —
        #   실패해도 수집 전체를 죽이지 않는다(빈 문자열 = 상세 확인불가).
        if not res.detail_html:
            res.detail_html = fetch_detail_html(product_url)
        return res

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
            # [2026-06-29 S21] 품절판정 = sellGbcd("00"=판매중/그 외 품절). 품절 사이즈도
            #   stockCount=1 센티넬을 주므로 stockCount 만 보면 '1개 있음' 둔갑(거짓 재고
            #   =금전손실). 단품(1축 SSR stockList)도 모음전과 동일하게 sellGbcd 우선.
            stock = _size_stock_from_row(row)
            uitm_cd = str(row.get("uitmCd") or "")
            options.append({
                "option_id": f"{slitm_cd}|{color_text}|{size_text}|{uitm_cd}",
                "color_text": color_text,
                "size_text": size_text,
                "price": price,
                "sale_price": price,
                "stock": stock,             # sellGbcd 3상태(품절=0). 999 둔갑 없음.
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
            # [2026-07-23 M3] 카테고리 경로 = **확인불가**(빈 문자열). 사유는 모듈 docstring
            #   「카테고리(빵부스러기) 부재」 참조. 지어내지 않는다.
            category_path="",
            # [2026-07-23 M4-4] 이미지 = __NEXT_DATA__ 파일명 + CDN 버킷 조립(실측 규칙).
            #   상세 = 이 HTML 에 없다(별도 API). 크롤 경로가 fetch_detail_html 로 채운다.
            image_urls=_parse_image_urls(it, slitm_cd, product_url),
            detail_html="",
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


# ── 현대H몰 상세설명(셀러 HTML) — item-dtl API ──────────────────────────────────
#   배경(2026-07-23 라이브 역공학):
#     · PDP 원문(13KB)에도 렌더 DOM 의 __NEXT_DATA__ 에도 상세설명이 **없다**.
#       화면의 상세 영역(`#smItemDetailInfoWrap`)은 XHR 응답을 JS 가 꽂아 넣는다.
#     · 원천 = `item-dtl` 응답의 `respData.itemPtc.htmlItstCntnList[].htmlItstCntn`
#       (실측: 셀러 상세 이미지 18장짜리 `<img src='https://ai.esmplus.com/…'>` 나열).
#     · 화면 DOM 을 긁으면 안 된다 — 롯데/현대 지연로딩이 실주소를 `no_image_600x600.jpg`
#       로 바꿔 놓아 46장 중 45장이 회색 판이 된다(실측). API 원문에는 실주소가 그대로다.
#     · API 는 공개(로그인 불필요·쿠키 없이 200) → 확장 없이 크롤 경로에서 호출 가능.


def _item_dtl_params(slitm_cd: str) -> dict:
    """item-dtl 쿼리 파라미터(브라우저 실요청에서 확인한 보일러플레이트).

    ``itstHtmlYn='Y'`` 가 상세 HTML 을 달라는 스위치다. 나머지는 화면 분기용 플래그라
    상세 본문에 영향이 없어 고정값으로 둔다(``slitmNm`` 은 로깅용이라 비워도 200).
    """
    return {
        "slitmCd": slitm_cd, "itstPhotoExpsYn": "N", "dtvItemYn": "N",
        "slitmNm": "", "itstHtmlYn": "Y", "optItemYn": "N",
        "custGrdSectYn": "N", "setItemYn": "N", "mLiveYn": "N", "brodChannel": "",
    }


def fetch_detail_html(product_url: str, timeout: int = DEFAULT_TIMEOUT) -> str:
    """현대H몰 상세설명 HTML 을 서버사이드로 수집. 실패하면 **빈 문자열**.

    ★ 크롤 경로(`HmallCrawler.fetch`)에서만 부른다 — 순수 파서(`parse_html`)는
      네트워크를 쓰지 않는다. 같은 파일의 `fetch_combo_persize_options` 와 같은 성격
      (공개 API 보강)이다.
    ★ 실패해도 예외를 올리지 않는다 — 상세 하나 때문에 가격·재고 수집이 죽으면 안 된다.
      '상세 확인불가'는 정직한 결과이고, 무스톰프 저장이라 기존값도 안 지운다.
    """
    slitm_cd = _extract_slitm_cd(product_url)
    if not slitm_cd:
        return ""
    try:
        r = requests.get(
            HMALL_ITEM_DTL_URL, params=_item_dtl_params(slitm_cd), timeout=timeout,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json",
                     "Accept-Language": "ko-KR,ko;q=0.9", "Referer": product_url},
        )
        r.raise_for_status()
        data = r.json() or {}
    except Exception as e:
        logger.warning("[m4img] 현대H몰 상세 API 실패 — 상세 확인불가. slitmCd=%s err=%s",
                       slitm_cd, str(e)[:120])
        return ""
    return detail_html_from_item_dtl(data, product_url)


def detail_html_from_item_dtl(data, product_url: str) -> str:
    """item-dtl 응답(JSON) → 정리된 상세 HTML. 순수 변환(네트워크 없음 — 테스트 대상).

    원천은 ``respData.itemPtc.htmlItstCntnList[].htmlItstCntn`` (셀러가 넣은 상세 HTML).
    여러 조각이면 순서대로 이어 붙여 공통 관문 한 번으로 정리한다. 없으면 빈 문자열.
    """
    if not isinstance(data, dict):
        return ""
    resp = data.get("respData") or {}
    if not isinstance(resp, dict):
        return ""
    lst = (resp.get("itemPtc") or {}).get("htmlItstCntnList") or resp.get("htmlItstCntnList")
    if not isinstance(lst, list):
        return ""
    fragments = [str((row or {}).get("htmlItstCntn") or "").strip()
                 for row in lst if isinstance(row, dict)]
    body = "".join(f for f in fragments if f)
    if not body:
        return ""
    # 조각을 하나로 묶어 공통 관문(스크립트·링크·추적픽셀 제거, 상대주소 절대화)에 태운다.
    return sanitize_detail_html(f"<div>{body}</div>", product_url)


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
