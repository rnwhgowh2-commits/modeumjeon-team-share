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
  - SSG MONEY — 사용자 명세 (2026-05-15): "**매입가에 반영해야 함**.
      단, 이미 sale_price 에 반영된 경우는 중복매입 방지를 위해 추가 차감 X."

SSG MONEY 패턴 (3 URL 실측 결과, 2026-05-15):
  - **패턴 A — 즉시할인 형태 (이미 sale_price 에 반영, 추가 차감 X)**:
      할인내역 layer ``div.cdtl_ly_cont`` 안에
      ``<dl class="cdtl_ly_dc"><dt>SSG MONEY 즉시할인</dt><dd>4,410원</dd>``.
      페이지 안내 텍스트: "현재 최적가의 금액 기준은 …, SSG MONEY 즉시할인이
      적용된 금액". → ``ssg_money_already_applied = True``.
      예: URL3 (1000807328520) 판매가 49,000 → 최적가 39,690
      (상품 즉시할인 4,900 + SSG MONEY 즉시할인 4,410).
  - **패턴 B — 적립 형태 (별도 적립, 매입가에서 차감 가능)**:
      구매혜택 영역 ``<span class="cdtl_benefit">SSG MONEY</span>`` +
      ``<div class="cdtl_benefit_info"><div class="txt">5% 적립</div>``.
      sale_price 에는 미반영 → 매입가 계산 시 sale_price 의 5% 만큼 차감 OK.
      ``ssg_money_already_applied = False``.
      예: URL1 (1000739593935 르무통) bestAmt=sellprc=109,900 + SSG MONEY 5% 적립.
  - **패턴 C — "X% 적립 또는 X% 즉시할인" 듀얼 옵션**:
      구매혜택 텍스트가 "10% 적립 또는 10% 즉시할인". 즉시할인 dl.cdtl_ly_dc 가
      함께 존재하면 사용자가 즉시할인 쪽을 선택한 가격(bestAmt)이므로 이미 반영.
      → ``ssg_money_already_applied = True`` (즉시할인 dl 우선).
      예: URL3 — 구매혜택은 "10% 적립 또는 10% 즉시할인"이지만 할인내역에
      "SSG MONEY 즉시할인 4,410원" 노출 → 즉시할인 모드 확정.
  - **패턴 D — SSG MONEY 노출 없음**:
      구매혜택 영역에 SSG MONEY 항목 없고 할인내역에도 SSG MONEY 즉시할인 dt 없음.
      → ``ssg_money_rate = 0``, ``ssg_money_amount = 0``, ``already_applied = False``.
      예: URL2 (1000631699134 닥스 벨트) — 상품 즉시할인 18,945원만 노출.

옵션 dict 표준 키 (base.CrawlResult.options):
  - option_id, color_text, size_text, price, sale_price, stock
  - card_benefit_price / card_benefit_condition (옵션이 모두 동일하므로 옵션마다 박음)
  - ssg_money_rate (float %) / ssg_money_amount (int 원) — 적립 또는 즉시할인 금액
  - ssg_money_already_applied (bool) — True 면 sale_price 에 이미 반영됨 → 중복매입 금지
  - ssg_money_text (str) — 원문 디버그용 ("5% 적립" / "10% 적립 또는 10% 즉시할인" 등)

2026-05-14 신규. 2026-05-15 SSG MONEY 매입가 반영 + 중복 방지 (패턴 A~D).
"""
from __future__ import annotations

import html as html_lib
import logging
import re
from typing import Optional
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

from curl_cffi import requests as cffi_requests
from bs4 import BeautifulSoup

from .base import AbstractCrawler, CrawlResult


logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# 상수
# ─────────────────────────────────────────────────────────────
DEFAULT_TIMEOUT = 30
IMPERSONATE = "chrome120"  # 다른 사이트 크롤러와 동일 (T10/T11/T12)

# 네이버 쇼핑 유입 위장 파라미터 — ckwhere=ssg_naver 가 채널 전용 제휴쿠폰
# (예: "[제휴할인] 백화점 8% 쿠폰")을 PDP 에 노출시킨다.
#   2026-06-02 익명 curl_cffi(본 크롤러 실환경) 실측 확정:
#     나이키 모자(itemId=1000552535854, siteNo=6009) — clean ❌ / s_naver ❌ /
#     ssg_naver ✅ 8% 제휴쿠폰. 네이버 토큰(NaPm)·로그인 모두 불필요.
#   ckwhere 값은 몰별로 다름(신세계몰 6004 → s_naver, 백화점 6009 → ssg_naver).
#   현재는 ssg_naver 단일 적용(실데이터 다수가 6009 + 6004 에서도 기존 쿠폰을
#   깨지 않음 확인). 신세계몰 전용 쿠폰 관측 시 siteNo 매핑 추가 검토.
NAVER_COUPON_PARAMS = {
    "ckwhere": "ssg_naver",
    "appPopYn": "n",
    "utm_medium": "PCS",
    "utm_source": "naver",
    "utm_campaign": "naver_pcs",
}

# ─────────────────────────────────────────────────────────────
# 세션(쿠키) 워밍업 — 익명 단발 요청은 SSG anti-bot 이 429 로 막는다.
# 실제 브라우징처럼 홈(ssg.com) 방문으로 쿠키 확보 후 재사용하면 통과율이 크게 오른다.
# ─────────────────────────────────────────────────────────────
import time as _time

_SSG_SESSION = None
_SSG_WARMED = False

_SSG_HEADERS = {
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.ssg.com/",
}


def _get_ssg_session(timeout: int = DEFAULT_TIMEOUT):
    """쿠키 유지 세션 반환 (최초 1회 홈 방문으로 워밍업)."""
    global _SSG_SESSION, _SSG_WARMED
    if _SSG_SESSION is None:
        _SSG_SESSION = cffi_requests.Session(impersonate=IMPERSONATE)
    if not _SSG_WARMED:
        try:
            _SSG_SESSION.get("https://www.ssg.com/", timeout=timeout,
                             headers={"Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8"})
            _SSG_WARMED = True
            _time.sleep(1.2)
        except Exception:
            pass
    return _SSG_SESSION


def _reset_ssg_session():
    global _SSG_SESSION, _SSG_WARMED
    _SSG_SESSION = None
    _SSG_WARMED = False


def _apply_naver_coupon_params(url: str) -> str:
    """SSG 상품 URL 에 네이버 유입 파라미터(ckwhere=ssg_naver 등)를 set/override.

    기존 query(itemId·siteNo·salestrNo·검색어 등)는 보존하고 ckwhere 등 5개만
    강제 세팅한다(기존 ``ckwhere=s_naver`` 가 있으면 덮어씀). itemId 없는 URL은
    그대로 둔다(안전).
    """
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    if "itemId" not in query:
        return url
    query.update(NAVER_COUPON_PARAMS)
    return urlunsplit(parts._replace(query=urlencode(query)))

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

# 옵션 값이 '사이즈'인지 판별 (220mm / 250 등). 단일 옵션축(단일색 상품)이 사이즈일 때
#   그 값을 size_text 로 보내기 위함. 색상명(블랙 등)·자유텍스트는 매칭 안 됨.
_SIZE_VALUE_RE = re.compile(r"^\s*\d{2,3}\s*(mm|cm)?\s*$", re.I)

# resultItemObj.itemNm / brandNm / brandId — 페이지 헤더 메타.
RESULT_ITEM_NM_RE = re.compile(r"itemNm\s*:\s*'((?:\\'|[^'])*)'")
RESULT_BRAND_NM_RE = re.compile(r"brandNm\s*:\s*'((?:\\'|[^'])*)'")

# itemId 추출 (URL fallback)
ITEM_ID_FROM_URL_RE = re.compile(r"[?&]itemId=([0-9]+)")

# [2026-06-05] 딜 페이지(dealItemView) 내부 itemView 링크의 itemId.
#   dealItemView 는 여러 단품을 묶은 "딜/기획전" 페이지로 uitemObj 인라인 JS 가 없어
#   본 크롤러로 직접 파싱 불가 → HTML 안 첫 itemView(대표 상품) 로 재크롤한다.
#   예: SSG_모음전 딜(1000616111568) → 첫 itemView=르무통 메이트(1000607152603).
DEAL_ITEMVIEW_LINK_RE = re.compile(r"itemView\.ssg\?itemId=(\d{10,})")


def _resolve_deal_representative_url(product_url: str, html: str) -> Optional[str]:
    """dealItemView(딜 묶음 페이지) → 대표 상품 itemView URL.

    딜 페이지엔 uitemObj 가 없어 직접 옵션 파싱 불가. HTML 안 첫 ``itemView.ssg``
    링크(=대표 상품)의 itemId 로 교체한 itemView URL 을 돌려준다. siteNo/salestrNo
    등 원본 쿼리는 보존한다. 링크가 없으면 None.
    """
    m = DEAL_ITEMVIEW_LINK_RE.search(html)
    if not m:
        return None
    return _item_view_url(product_url, m.group(1))


def _item_view_url(product_url: str, item_id: str) -> str:
    """dealItemView/itemView URL 의 itemId 를 바꿔 단일 itemView URL 생성(쿼리 보존)."""
    parts = urlsplit(product_url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["itemId"] = item_id
    new_path = parts.path.replace("dealItemView.ssg", "itemView.ssg")
    if "itemView.ssg" not in new_path:
        new_path = "/item/itemView.ssg"
    return urlunsplit(parts._replace(path=new_path, query=urlencode(query)))


def _model_core(name: str) -> str:
    """모델 핵심명 — 브랜드/프로모/공통 수식어 제거(메이트·업·메이트 메리제인 등만 남김)."""
    s = re.sub(r"\[[^\]]*\]", " ", name or "")
    for w in ("르무통", "발 편한", "발편한", "메리노울", "운동화", "컬러", ",", "·"):
        s = s.replace(w, " ")
    return re.sub(r"\s+", " ", s).strip()


def resolve_deal_models(product_url: str, html: str, fetch_html=None, parse_html=None) -> list[dict]:
    """[2026-06-19 모델매핑] 딜(dealItemView) 묶음 → 묶인 '모델' 전체 목록.

    Returns: [{item_id, name, url}] — fetch_html·parse_html 주면 각 itemView 의 정확한
      product_name 으로 name 을 채운다(모달 표시·모델명 매칭용). 없으면 itemId.
    """
    ids: list[str] = []
    for m in DEAL_ITEMVIEW_LINK_RE.finditer(html):
        if m.group(1) not in ids:
            ids.append(m.group(1))
    urls = {iid: _item_view_url(product_url, iid) for iid in ids}
    names: dict[str, Optional[str]] = {}
    # [2026-06-21] 각 itemView 상품명 fetch 를 '병렬'로 (기존 순차 9건 ~9초 → ~1-2초).
    #   드롭다운이 너무 느려 '안 되는 것처럼' 보이던 문제 해결. fetch_html·parse_html 은
    #   호출마다 독립(스레드 안전)이라 ThreadPool 로 동시 실행한다.
    if fetch_html and parse_html and ids:
        from concurrent.futures import ThreadPoolExecutor

        def _name(iid):
            try:
                res = parse_html(fetch_html(urls[iid]), urls[iid])
                return iid, (getattr(res, "product_name_raw", None)
                             or getattr(res, "product_name", None))
            except Exception:
                return iid, None
        try:
            with ThreadPoolExecutor(max_workers=min(9, len(ids))) as ex:
                for iid, name in ex.map(_name, ids):
                    names[iid] = name
        except Exception:
            names = {}
    out = [{"item_id": iid, "name": (names.get(iid) or iid), "url": urls[iid]}
           for iid in ids]
    return out


def match_deal_model(models: list[dict], target_name: str):
    """묶인 모델들 중 우리 모음전 모델명(target)에 맞는 1개 선정.

    Returns: (matched_dict | None, ambiguous: bool)
      - 핵심명 토큰셋 동일 = 확정. 첫 토큰만 같고 여러 개 = ambiguous(사용자 확인).
      - '메이트' vs '메이트 메리제인' 처럼 헷갈리면 ambiguous=True 로 표시.
    """
    t = _model_core(target_name).split()
    if not t:
        return None, False
    t0, tset = t[0], set(t)
    scored = []
    for m in models:
        toks = _model_core(m.get("name", "")).split()
        score = 0
        if set(toks) == tset:
            score += 5                       # 정확히 같은 모델
        if toks and toks[0] == t0:
            score += 2                       # 첫 토큰(핵심) 일치
        if t0 in "".join(toks):
            score += 1
        scored.append((score, m))
    scored.sort(key=lambda x: -x[0])
    best = scored[0]
    if best[0] <= 0:
        return None, False
    ambiguous = len(scored) > 1 and scored[1][0] == best[0]
    return best[1], ambiguous

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


# ─────────────────────────────────────────────────────────────
# SSG MONEY 파서 — 사용자 명세 (2026-05-15): 매입가 반영 + 중복 방지
# ─────────────────────────────────────────────────────────────
# 즉시할인 형태 텍스트 (이미 sale_price 에 반영됨 — 추가 차감 금지)
_RE_SSG_MONEY_INSTANT_DT = re.compile(r"SSG\s*MONEY\s*즉시할인")
# 안내 문구 — "최적가의 금액 기준은 ... SSG MONEY 즉시할인이 적용된 금액"
_RE_SSG_MONEY_APPLIED_NOTE = re.compile(
    r"최적가의\s*금액\s*기준은[^<]{0,80}?SSG\s*MONEY\s*즉시할인이\s*적용된\s*금액"
)
# 적립 형태 텍스트: "5% 적립" / "10% 적립 또는 10% 즉시할인"
_RE_BENEFIT_PCT_ACCUM = re.compile(
    r"(\d+(?:\.\d+)?)\s*%\s*적립(?:\s*또는\s*(\d+(?:\.\d+)?)\s*%\s*즉시할인)?"
)
# 적립 형태 텍스트: "5,000원 적립" (% 가 아닌 정액 적립도 대응)
_RE_BENEFIT_KRW_ACCUM = re.compile(r"([0-9][0-9,]{2,})\s*원\s*적립")
# SSG MONEY 충전결제 적립 텍스트: "충전결제 시 1.5% 적립" (별도 적립 — 매입가에서 차감 가능)
# 구매혜택 > 쇼핑혜택 탭에 위치. <div class="txt color1">충전결제 시 1.5% 적립</div>
_RE_SSG_MONEY_CHARGE_PCT = re.compile(
    r"충전\s*결제\s*시\s*(\d+(?:\.\d+)?)\s*%\s*적립"
)


def _parse_ssg_money(soup: BeautifulSoup, html: str) -> dict:
    """SSG MONEY 적립/즉시할인 추출.

    Returns:
        dict with keys:
            ssg_money_rate: float (% 적립률, 없으면 0.0)
            ssg_money_amount: int (정액 적립 원, 없으면 0)
            ssg_money_already_applied: bool
                — True 면 sale_price(bestAmt) 에 이미 반영됨 → 중복매입 방지
            ssg_money_text: str (원문 디버그용)
    """
    out = {
        "ssg_money_rate": 0.0,
        "ssg_money_amount": 0,
        "ssg_money_already_applied": False,
        "ssg_money_text": "",
    }

    # 1) 할인내역 layer 의 "SSG MONEY 즉시할인" dt 존재 여부 → 이미 반영 신호
    # 페이지에는 div.cdtl_ly_cont 가 여러 개 (공유하기·할인내역·기타 툴팁) — 모두 순회.
    # 할인내역 layer 만 dl.cdtl_ly_dc (dc = discount) 노드를 보유함.
    instant_in_layer = False
    instant_amount = 0
    for layer in soup.select("div.cdtl_ly_cont"):
        for dl in layer.select("dl.cdtl_ly_dc"):
            dts = dl.select("dt")
            dds = dl.select("dd")
            for dt, dd in zip(dts, dds):
                dt_text = re.sub(r"\s+", " ", dt.get_text(" ", strip=True))
                if _RE_SSG_MONEY_INSTANT_DT.search(dt_text):
                    instant_in_layer = True
                    em = dd.select_one("em.ssg_price")
                    if em:
                        instant_amount = _to_int(em.get_text())
                    break
            if instant_in_layer:
                break
        if instant_in_layer:
            break
    # 안내 문구로도 confirm
    note_says_applied = bool(_RE_SSG_MONEY_APPLIED_NOTE.search(html))

    # 2) 구매혜택 영역의 <span class="cdtl_benefit">SSG MONEY</span> 적립 텍스트
    accum_rate = 0.0
    accum_amount = 0
    benefit_text = ""
    for span in soup.select("span.cdtl_benefit"):
        label = (span.get_text(strip=True) or "")
        if "SSG MONEY" not in label.upper() and "SSGMONEY" not in label.upper().replace(" ", ""):
            continue
        li = span.parent
        if not li:
            continue
        info = li.select_one("div.cdtl_benefit_info > div.txt") or li.select_one("div.cdtl_benefit_info .txt")
        if not info:
            continue
        benefit_text = re.sub(r"\s+", " ", info.get_text(" ", strip=True))
        m_pct = _RE_BENEFIT_PCT_ACCUM.search(benefit_text)
        if m_pct:
            try:
                accum_rate = float(m_pct.group(1))
            except ValueError:
                accum_rate = 0.0
        else:
            m_krw = _RE_BENEFIT_KRW_ACCUM.search(benefit_text)
            if m_krw:
                accum_amount = _to_int(m_krw.group(1))
        break

    # 2-b) 구매혜택 > 쇼핑혜택 영역의 "충전결제 시 X% 적립" 텍스트 (별도 적립 — 패턴 B 변형).
    #     예: <div class="txt color1">충전결제 시 1.5% 적립</div>
    #          <span class="desc">횟수 무제한 SSG MONEY 적립</span>
    #     accum_rate 미발견 시 fallback 으로 채택 (사이트 노출 1.5% 충전결제 적립).
    if accum_rate <= 0 and accum_amount <= 0:
        m_charge = _RE_SSG_MONEY_CHARGE_PCT.search(html)
        if m_charge:
            try:
                accum_rate = float(m_charge.group(1))
                if not benefit_text:
                    benefit_text = f"충전결제 시 {m_charge.group(1)}% 적립 (SSG MONEY)"
            except ValueError:
                pass

    # 3) already_applied 판정 룰 (우선순위: 할인내역 dt > 안내문구 > 텍스트 "즉시할인" 존재)
    already_applied = bool(instant_in_layer or note_says_applied)
    # 패턴 C: 구매혜택은 "X% 적립 또는 X% 즉시할인" + 할인내역에 SSG MONEY 즉시할인 dt
    # → 이미 즉시할인 모드로 bestAmt 가 계산됨 (instant_in_layer=True 이면 자동 처리)

    # 출력 정리
    if already_applied:
        out["ssg_money_already_applied"] = True
        # 즉시할인 금액(원)을 ssg_money_amount 로 보고 — 매입가에 차감 금지의 근거
        if instant_amount > 0:
            out["ssg_money_amount"] = instant_amount
        # rate 는 적립 표시 텍스트에서 잡힌 % 그대로 노출 (디버그/표시용),
        # 단 already_applied=True 이면 매트릭스 산식에서 적용 안 함.
        if accum_rate > 0:
            out["ssg_money_rate"] = accum_rate
        out["ssg_money_text"] = benefit_text or "SSG MONEY 즉시할인 (sale_price 반영됨)"
    else:
        out["ssg_money_already_applied"] = False
        out["ssg_money_rate"] = accum_rate
        out["ssg_money_amount"] = accum_amount
        out["ssg_money_text"] = benefit_text

    return out


# ─────────────────────────────────────────────────────────────
# 상품쿠폰 파서 — 사용자 명세 (2026-05-15): X% 상품쿠폰 + 최소 구매금액 조건
# ─────────────────────────────────────────────────────────────
# DOM 구조 (URL 2번 닥스 벨트 예시):
#   <dl class="cdtl_dl cdtl_cpn_wrap">
#     <dt>상품쿠폰</dt>
#     <dd>
#       <a class="cdtl_benefit_coupon ...">
#         <strong class="tit">
#           <span class="cpn_txt">12%&nbsp;상품쿠폰</span>
#           <span class="ssg_price">최대 3만원</span>
#         </strong>
#         <p class="txt">
#           명품/잡화 쓱세일 백화점 12% 상품쿠폰<br>3만원 이상 구매 시 사용가능(~05/17)
#         </p>
#       </a>
#     </dd>
#   </dl>

# 쿠폰 X% 추출 (cpn_txt: "12% 상품쿠폰" / 정액 X원도 대응)
_RE_COUPON_PCT = re.compile(r"(\d+(?:\.\d+)?)\s*%\s*상품\s*쿠폰")
_RE_COUPON_KRW = re.compile(r"([0-9][0-9,]{2,})\s*원\s*상품\s*쿠폰")
# 최소 구매금액 추출 ("3만원 이상 구매 시 사용가능")
_RE_COUPON_MIN_ORDER = re.compile(r"(\d+(?:\.\d+)?)\s*만\s*원\s*이상\s*구매")
# 최대 할인액 ("최대 3만원" — UI 표시용, 산식에는 영향 X. % 가 적용되면 자동으로 한도 안)
_RE_COUPON_MAX = re.compile(r"최대\s*([0-9][0-9,]*)\s*만?\s*원")


def _parse_product_coupon(soup: BeautifulSoup) -> dict:
    """상품쿠폰 (X% / 최소 구매금액) 추출.

    Returns:
        dict with keys (모두 미노출이면 빈 dict):
            product_coupon_rate: float (% 비율, 0.12 = 12%)
            product_coupon_amount: int (정액 쿠폰 — % 미노출 시)
            product_coupon_min_order: int (최소 구매금액 원, 없으면 0)
            product_coupon_max_discount: int (최대 할인 원, UI 표시용)
            product_coupon_label: str (UI 표시 — "백화점 12% 상품쿠폰" 등)
    """
    out: dict = {}
    # dl.cdtl_cpn_wrap 안의 dt 가 "상품쿠폰" 인 dl
    wrap = None
    for dl in soup.select("dl.cdtl_cpn_wrap"):
        dt = dl.select_one("dt")
        if dt and "상품쿠폰" in dt.get_text(strip=True):
            wrap = dl
            break
    # fallback: dt 매칭 실패 시 cdtl_benefit_coupon 클래스로 직접 탐색
    if wrap is None:
        for dl in soup.select("dl"):
            if dl.select_one("a.cdtl_benefit_coupon, .cdtl_cpn_wrap"):
                dt = dl.select_one("dt")
                if dt and "상품쿠폰" in dt.get_text(strip=True):
                    wrap = dl
                    break
    if wrap is None:
        return out

    # X% 추출 (cpn_txt 우선)
    coupon_text = wrap.get_text(" ", strip=True)
    coupon_text = re.sub(r"\s+", " ", coupon_text)
    m_pct = _RE_COUPON_PCT.search(coupon_text)
    if m_pct:
        try:
            pct = float(m_pct.group(1))
            # rate 정규화 (12 → 0.12)
            out["product_coupon_rate"] = pct / 100 if pct > 1 else pct
        except ValueError:
            pass
    else:
        # 정액 fallback
        m_krw = _RE_COUPON_KRW.search(coupon_text)
        if m_krw:
            out["product_coupon_amount"] = _to_int(m_krw.group(1))

    # 최소 구매금액 ("3만원 이상")
    m_min = _RE_COUPON_MIN_ORDER.search(coupon_text)
    if m_min:
        try:
            man_units = float(m_min.group(1))
            out["product_coupon_min_order"] = int(man_units * 10000)
        except ValueError:
            pass

    # 최대 할인액 (UI 표시용 — "최대 3만원")
    m_max = _RE_COUPON_MAX.search(coupon_text)
    if m_max:
        # "만원" 단위 검출 — 숫자 자체가 작으면 만원 단위로 간주
        s = m_max.group(1).replace(",", "")
        try:
            n = int(s)
            # "최대 3만원" → 30000 / "최대 30,000원" → 30000
            if "만원" in m_max.group(0) or "만 원" in m_max.group(0):
                out["product_coupon_max_discount"] = n * 10000
            else:
                out["product_coupon_max_discount"] = n
        except ValueError:
            pass

    # 라벨 (p.txt 첫 줄 — "명품/잡화 쓱세일 백화점 12% 상품쿠폰")
    p_txt = wrap.select_one("p.txt")
    if p_txt:
        # <br> 분리 후 첫 줄 (조건 텍스트 제외)
        label_html = str(p_txt)
        label_first = re.split(r"<br\s*/?>", label_html, 1)[0]
        label_clean = BeautifulSoup(label_first, "lxml").get_text(" ", strip=True)
        label_clean = re.sub(r"\s+", " ", label_clean).strip()
        if label_clean:
            out["product_coupon_label"] = label_clean

    return out


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
        #
        # [2026-06-19 fix] 단일색 상품(블랙·다크네이비 등)은 옵션축이 '사이즈' 하나뿐이라
        #   type1='사이즈', optn1='220mm', optn2='' 로 온다. 기존 로직은 type1!='색상' 이라
        #   color_text=f"사이즈:220mm", size_text="" 로 만들어 → 저장단(_ingest)이 size_text 에
        #   숫자가 없어 '사이즈 미상'으로 전 옵션을 조용히 skip → 사이즈별 재고가 통째로 사라지고
        #   상품레벨 재고(합계)로 둔갑(전 사이즈 동일 수치)하던 버그. 단일축이 사이즈면 그 값을
        #   size_text 로 보내고 color 는 비운다(상품=단일색 → 매칭은 사이즈만으로 안전).
        if (not optn2) and (type1 == "사이즈" or _SIZE_VALUE_RE.match(optn1 or "")):
            color_text = ""
            size_text = optn1
        elif type1 == "색상" or not type1:
            color_text = optn1
            size_text = optn2 if (type2 == "사이즈" or not type2) else (f"{type2}:{optn2}" if optn2 else "")
        else:
            color_text = f"{type1}:{optn1}"
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
        # 네이버 유입 위장(ckwhere=ssg_naver)으로 채널 전용 제휴쿠폰까지 HTML 에 포함시킨다.
        fetch_url = _apply_naver_coupon_params(product_url)
        last_exc = None
        for attempt in range(4):
            sess = _get_ssg_session(self.timeout)
            try:
                resp = sess.get(fetch_url, timeout=self.timeout, headers=_SSG_HEADERS)
            except Exception as e:  # 네트워크/타임아웃
                last_exc = e
                _reset_ssg_session()
                _time.sleep(4 * (attempt + 1))
                continue
            if resp.status_code == 429:
                # 차단 — 세션 새로(쿠키 리셋) + 점증 대기 후 재시도
                last_exc = RuntimeError("HTTP Error 429: ")
                _reset_ssg_session()
                _time.sleep(8 * (attempt + 1))
                continue
            resp.raise_for_status()
            return resp.text
        raise last_exc or RuntimeError("[SSG] fetch 실패")

    def parse_html(self, html: str, product_url: str) -> CrawlResult:
        """받은 HTML 을 파싱해 CrawlResult 반환 (네트워크 없음 — A안 확장 진입점).

        fetch 의 세션 워밍업·딜 페이지 재크롤은 fetch 단계에서 처리.
        parse_html 은 받은 html 을 그대로 파싱한다.
        """
        soup = BeautifulSoup(html, "lxml")

        item_id = _extract_item_id(product_url, html)
        product_name = _extract_product_name(html, soup)
        brand = _extract_brand(html, soup)

        # 카드혜택가 (전 옵션 공통)
        card_price, card_condition = _parse_card_benefit(soup)

        # SSG MONEY (전 옵션 공통 — 적립률·적립금·이미 반영 여부)
        ssg_money = _parse_ssg_money(soup, html)

        # 상품쿠폰 (전 옵션 공통 — X% / 최소 구매금액)
        product_coupon = _parse_product_coupon(soup)

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

        # SSG MONEY 정보를 모든 옵션에 첨부 (옵션 단위로 동일).
        #   매트릭스 산식 — already_applied=False 일 때만 매입가 베이스에서 차감.
        #   already_applied=True → 표시만 / 중복매입 방지.
        for opt in options:
            opt["ssg_money_rate"] = ssg_money["ssg_money_rate"]
            opt["ssg_money_amount"] = ssg_money["ssg_money_amount"]
            opt["ssg_money_already_applied"] = ssg_money["ssg_money_already_applied"]
            if ssg_money["ssg_money_text"]:
                opt["ssg_money_text"] = ssg_money["ssg_money_text"]

        # 상품쿠폰 정보를 모든 옵션에 첨부 (옵션 단위로 동일).
        #   매트릭스 산식 — sale_price >= product_coupon_min_order 시 자동 활성.
        for opt in options:
            for k, v in product_coupon.items():
                opt[k] = v

        # discount_info — 카드혜택가 + SSG MONEY + 상품쿠폰 텍스트 요약
        discount_parts: list[str] = []
        if card_price is not None:
            seg = f"카드혜택가 {card_price:,}원"
            if card_condition:
                seg += f" ({card_condition})"
            discount_parts.append(seg)
        if ssg_money["ssg_money_text"]:
            if ssg_money["ssg_money_already_applied"]:
                discount_parts.append(
                    f"SSG MONEY {ssg_money['ssg_money_text']} [sale_price 반영됨 / 중복차감 X]"
                )
            else:
                discount_parts.append(f"SSG MONEY {ssg_money['ssg_money_text']}")
        if product_coupon.get("product_coupon_rate") or product_coupon.get("product_coupon_amount"):
            if product_coupon.get("product_coupon_rate"):
                seg = f"상품쿠폰 {product_coupon['product_coupon_rate']*100:g}%"
            else:
                seg = f"상품쿠폰 {product_coupon.get('product_coupon_amount', 0):,}원"
            min_o = product_coupon.get("product_coupon_min_order")
            if min_o:
                seg += f" ({min_o//10000}만원 이상)"
            discount_parts.append(seg)
        discount_info = " / ".join(discount_parts)

        return CrawlResult(
            source=self.source_name,
            product_url=product_url,
            product_name_raw=product_name,
            options=options,
            brand=brand,
            discount_info=discount_info,
        )

    def fetch(self, product_url: str) -> CrawlResult:
        html = self._fetch_html(product_url)

        # [2026-06-20 money-safe] 딜 페이지(dealItemView)는 자동 '대표상품' 크롤 금지.
        #   사유: 딜 페이지 itemView 링크에 SSG 광고 캐러셀(data-advert) 상품이 섞여 있어
        #   '첫 itemView'가 무관한 광고상품(예: 여성 와이드 바지)일 수 있음 → 엉뚱한 가격/재고
        #   크롤(금전 위험). 딜은 반드시 모델 선택(resolve_deal_models)으로 단일 itemView URL을
        #   지정해 크롤한다. 대표상품 자동선택(_resolve_deal_representative_url)은 폐기.
        if "uitemObjArr.push" not in html:
            logger.warning("[SSG] 딜 페이지(dealItemView) — 자동 대표상품 크롤 금지. "
                           "모델 선택으로 단일 itemView URL 지정 필요: %s", product_url)
            # 옵션 없는 빈 결과 반환(파서가 딜 HTML 에서 옵션을 못 찾음 = 정직한 '데이터 없음').
            return self.parse_html(html, product_url)

        return self.parse_html(html, product_url)
