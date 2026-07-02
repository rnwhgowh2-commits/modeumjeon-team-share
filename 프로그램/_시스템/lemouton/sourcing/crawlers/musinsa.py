"""무신사 (musinsa.com) 단품 크롤러.

V7 (Chrome extension) 의 musinsa 크롤링 로직을 Python 으로 1:1 포팅.

V7 원본 위치: ``크롤러_V7_쿠팡 반영/background/background.js``
  - ``crawlProduct(productId)`` — 신/구 페이지 fallback 라우터
  - ``crawlNewPage(productId)`` — www.musinsa.com/products/{id} 흐름
       1. ``musinsaGetMaxBenefitPrice`` — 최대혜택가 체크박스 클릭 (본 task 미사용)
       2. ``getDropdownCount`` — 드롭다운 개수 (1=사이즈만, 2=색상×사이즈)
       3. ``parseDropdownItems`` — ``__NEXT_DATA__`` 에서 productName/brand/normalPrice/salePrice
          + DOM ``[data-mds="StaticDropdownMenuItem"]`` innerText 에서 옵션·품절·재고
       4. ``crawlColorSize`` — 색상 클릭 → 사이즈 드롭다운 갱신 → 컬러별 사이즈 행 생성
  - ``crawlLegacyPage(productId)`` — store.musinsa.com/app/goods/{id} 폴백 (jaego_yn / stock 속성)

V7 흐름 한국어 요약 (변경 금지):
  1. URL 매칭: ``/musinsa\\.com\\/products\\/(\\d+)/`` 캡처 → productId
  2. ``__NEXT_DATA__`` JSON 에서 메타 추출:
       - ``goodsNm`` → productName
       - ``brandName`` → brand
       - ``normalPrice`` → originPrice
       - ``salePrice`` → price
       - 둘 중 하나만 있으면 다른 쪽도 같은 값 (V7 ``if (!originPrice && salePrice)`` 분기)
  3. 드롭다운 1개 → 사이즈만, option1=사이즈명, option2='' (색상 없음 케이스)
  4. 드롭다운 2개 → 색상 × 사이즈 데카르트 곱, option1=색상, option2=사이즈
  5. 품절 마커: 옵션 텍스트에 ``(품절)`` 포함 또는 ``재입고 알림`` 라인 → stockQuantity=0
  6. 재고 수량: 텍스트에서 ``잔여 N개`` / ``N개 남음`` / ``재고 N개`` 매칭
       - ≤10 이면 그 값, 아니면 10 으로 캡 (V7 default)
  7. 최대혜택가 옵션 (``musinsaCoupon``/``musinsaPoint``/``musinsaPrediscount``):
       - 본 task 는 default ``salePrice`` 만 사용. V7 의 체크박스 클릭 / DOM 가격 재읽기 로직은
         별도 task 로 분리 (Concerns 참고).

Python 환경 한계 보강 (V7 의미 보존, 절차 변경):
  - V7 는 Chrome 탭에서 JS 로 렌더된 DOM 드롭다운을 "클릭" 해야 옵션이 보임. requests/curl 로는 DOM 클릭 불가.
    → 동등한 데이터 출처를 musinsa 내부 API 에서 사용 (V7 의 ``__NEXT_DATA__`` 추출과 동일 의미):

    (a) 메타: ``GET https://goods-detail.musinsa.com/api2/goods/{goodsNo}``
        ↳ V7 ``"goodsNm"``/``"brandName"``/``"normalPrice"``/``"salePrice"`` 정규식과 정확히 동일한 필드.
    (b) 옵션 정의: ``GET https://goods-detail.musinsa.com/api2/goods/{goodsNo}/options``
        ↳ V7 가 DOM 드롭다운에서 읽던 색상명·사이즈명·optionItem(=SKU) 매핑.
        - ``data.basic[]`` = V7 의 드롭다운 그룹 (name='색상' / '사이즈').
        - ``data.optionItems[]`` = SKU 단위. ``managedCode`` 가 ``"{색상}^{사이즈}"`` 형태로
          V7 의 ``option1^option2`` 규약과 동일.
    (c) 재고/품절: ``POST https://goods-detail.musinsa.com/api2/goods/{goodsNo}/options/v2/prioritized-inventories``
        body ``{"optionValueNos": [...]}`` (전체 색상·사이즈 ID 평탄화).
        ↳ V7 가 DOM 드롭다운 텍스트의 ``(품절)`` 마커로 판정하던 것과 동등한 신호:
            - ``outOfStock=true`` → V7 stockStatus='품절'
            - ``remainQuantity`` (정수) → V7 ``잔여 N개`` 정규식 결과
        - ``productVariantId`` = ``optionItems[].no`` 와 매핑.

  - HTTP 클라이언트: Cloudflare bot detection 회피를 위해 ``curl_cffi.requests`` 사용
    (TLS fingerprint 가 실제 Chrome 과 동일). 일반 ``requests`` 는 403 (Cloudflare).
"""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlparse

from curl_cffi import requests as cffi_requests

from .base import AbstractCrawler, CrawlResult


# ─────────────────────────────────────────────────────────────
# V7 동등 상수 — host_permissions 와 동일한 도메인만 호출
# ─────────────────────────────────────────────────────────────
GOODS_DETAIL_BASE = "https://goods-detail.musinsa.com"
PDP_REFERER_BASE = "https://www.musinsa.com"
DEFAULT_TIMEOUT = 30
IMPERSONATE = "chrome120"  # curl_cffi 가 V7 Chrome UA 에 가장 가까운 프로필


# V7: ``/musinsa\.com\/products\/(\d+)/`` (background.js crawlByUrl)
PRODUCT_ID_PATTERN = re.compile(r"/products/(\d+)")


def _extract_product_id(product_url: str) -> str:
    """V7: ``url.match(/\\/products\\/(\\d+)/)[1]``."""
    m = PRODUCT_ID_PATTERN.search(product_url)
    return m.group(1) if m else ""


def _build_headers(product_url: str) -> dict:
    """V7 의 Chrome 탭 동등 — Origin/Referer 가 www.musinsa.com 이어야 CORS 통과."""
    return {
        "Origin": PDP_REFERER_BASE,
        "Referer": product_url,
        "Accept": "application/json",
    }


def _split_managed_code(managed_code: str) -> tuple[str, str]:
    """V7 ``option1^option2`` 규약: ``"블랙^225mm"`` → ('블랙', '225mm').

    옵션 1개 (사이즈만 또는 색상만) 인 경우 ``"^"`` 가 없을 수 있음 → 단일 토큰으로 처리.
    """
    if "^" in managed_code:
        a, b = managed_code.split("^", 1)
        return a.strip(), b.strip()
    return managed_code.strip(), ""


def _get_default_musinsa_account(strict: bool = False) -> Optional[tuple]:
    """대표 크롤 계정 (sourcing_accounts.is_default_for_crawl=1) 의 (source, account_key) 반환.

    auth 파일 (data/auth/{source}_{account_key}.json) 도 존재해야 함.

    Args:
        strict: True 면 DB 조회 실패(연결 끊김·풀 고갈 등) 시 예외를 그대로 전파한다.
                False(기본) 면 기존 호환 — 모든 예외를 삼키고 None 반환.

    ⚠️ 2026-06-05: 회원가 크롤 차단 로직(`_fetch_single`)은 strict=True 로 호출한다.
       DB 오류를 삼켜 None 으로 만들면 "로그인 세션 만료"로 오인되어, 단순 DB 끊김에도
       잘못된 차단/자동 재로그인이 발생하기 때문. strict 모드에서 DB 오류는 그대로 올라가
       호출자가 "로그인 문제"가 아닌 "인프라 문제"로 구분 처리한다.
    """
    from pathlib import Path
    from shared.db import SessionLocal
    from sqlalchemy import text
    try:
        s = SessionLocal()
        try:
            # ⚠️ is_default_for_crawl/is_active 는 PostgreSQL(Supabase)에서 BOOLEAN,
            #    SQLite 에선 INTEGER(0/1). "= 1" 로 비교하면 Postgres 에서
            #    'operator does not exist: boolean = integer' 에러가 난다.
            #    bare 컬럼(truthy 평가)은 두 DB 모두 호환 → = 1 제거. (2026-06-05 fix)
            r = s.execute(text(
                "SELECT source, account_key FROM sourcing_accounts "
                "WHERE source IN ('musinsa', '무신사') AND is_default_for_crawl "
                "AND is_active LIMIT 1"
            )).first()
        finally:
            s.close()
    except Exception:
        if strict:
            raise  # DB 오류 → 로그인 만료로 위장하지 않고 호출자에게 전파
        return None
    if not r:
        return None
    db_source, acc_key = r[0], r[1]
    # auth 파일 — 한글/영문 source 둘 다 시도
    auth_dir = Path("data/auth")
    for src in (db_source, "musinsa", "무신사"):
        if (auth_dir / f"{src}_{acc_key}.json").exists():
            return (src, acc_key)
    return None


# 모듈 레벨 캐시 — process 수명 동안 styleNo→variant_urls 재사용
_VARIANT_CACHE: dict = {}


def _discover_color_variants(product_url: str) -> list:
    """무신사 product 의 모델명 → 같은 모델의 모든 색상 product URL 자동 발견.

    1. product 페이지 fetch → goodsNm + brand 추출
    2. goodsNm 의 색상 단어 제거 → base 모델명
    3. Playwright 로 검색 페이지 렌더 → 같은 brand 의 product_id list 반환
    """
    import re as _re, json as _json
    try:
        r = cffi_requests.get(product_url, impersonate=IMPERSONATE,
                              headers=_build_headers(product_url), timeout=10)
        if r.status_code != 200:
            return [product_url]
        m = _re.search(r'__NEXT_DATA__\"\s*type=\"application/json\">(.+?)</script>',
                       r.text, _re.DOTALL)
        if not m:
            return [product_url]
        data = _json.loads(m.group(1))
        txt = _json.dumps(data, ensure_ascii=False)
        # goodsNm + brand 추출
        gm = _re.search(r'"goodsNm"\s*:\s*"([^"]+)"', txt)
        bm = _re.search(r'"brandName"\s*:\s*"([^"]+)"', txt)
        if not gm:
            return [product_url]
        goods_nm = gm.group(1)
        brand_name = bm.group(1) if bm else ""
        # 색상 단어 제거 (한글 색상 패턴)
        color_pats = ['다크네이비', '네이비', '블랙블랙', '블랙화이트',
                      '블랙', '화이트', '그레이', '브라운', '아이보리',
                      '오렌지', '라이트블루', '스카이블루', '크림핑크',
                      '올리브그린', '핑크', '레드', '블루', '카키']
        base = goods_nm
        for c in color_pats:
            base = _re.sub(rf'\s*{c}\s*', ' ', base).strip()
        # cache key
        cache_key = (brand_name + ":" + base).strip()
    except Exception:
        return [product_url]

    import logging as _lg
    _logger = _lg.getLogger("lemouton.sourcing.crawlers.musinsa")
    _logger.info("[musinsa] discover_variants base=%s brand=%s", base, brand_name)
    if cache_key in _VARIANT_CACHE:
        _logger.info("[musinsa] cache hit: %d urls", len(_VARIANT_CACHE[cache_key]))
        return _VARIANT_CACHE[cache_key]

    # Playwright 로 검색 페이지 렌더 — headless=False 가 musinsa 자동화 차단 우회 확인됨
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=False, channel="chrome",
                args=["--disable-blink-features=AutomationControlled",
                      "--window-position=2000,2000",  # 화면 밖 위치
                      "--window-size=400,300"],
            )
            try:
                ctx = browser.new_context(locale="ko-KR",
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36")
                page = ctx.new_page()
                from .base import block_heavy_resources
                block_heavy_resources(page)  # [PERF] 이미지/영상/폰트 차단 — 검색결과 텍스트는 그대로
                # base 모델명 + brand 로 검색 (URL 인코딩)
                from urllib.parse import quote as _q
                search_kw = f"{brand_name} {base}".strip() if brand_name else base
                page.goto(f"https://www.musinsa.com/search/goods?keyword={_q(search_kw)}",
                          wait_until="networkidle", timeout=30000)
                page.wait_for_timeout(4000)
                ids = page.evaluate("""() => {
                    const out = new Set();
                    document.querySelectorAll('a[href*="/products/"]').forEach(a => {
                        const m = a.href.match(/\\/products\\/(\\d+)/);
                        if (m) out.add(m[1]);
                    });
                    return Array.from(out);
                }""")
            finally:
                browser.close()
        urls = [f"https://www.musinsa.com/products/{i}" for i in ids if i]
        if not urls:
            urls = [product_url]
        _logger.info("[musinsa] discover_variants result: %d urls", len(urls))
        _VARIANT_CACHE[cache_key] = urls
        return urls
    except Exception as _e:
        _logger.warning("[musinsa] discover_variants Playwright 실패: %s", _e)
        return [product_url]


def _has_musinsa_session() -> bool:
    """대표 크롤 계정의 storage_state 파일 존재 여부."""
    return _get_default_musinsa_account() is not None


class MusinsaCrawler(AbstractCrawler):
    """무신사 디스패처 — 로그인 세션 있으면 회원가 (Playwright), 없으면 비로그인 API.

    동작:
      1. ``prefer_member_price=True`` (기본) → 반드시 로그인(회원가) 상태로만 크롤.
         대표 계정 + 세션 있으면 ``MusinsaPlaywrightCrawler`` (무신사머니/적립금/선할인 차감).
         로그인 불가(대표계정 없음·세션 만료·Playwright 실패) 시 → ``LoginExpiredError`` 로
         **막는다** (2026-06-05 정책: 비로그인 가격 = 잘못된 매입가 = 금전 손실).
      2. ``prefer_member_price=False`` (다중 색상 variant 사이즈 추출 전용) → 비로그인 API
         (V7 ``crawlNewPage``) 로 ``salePrice`` 만 추출 (회원가 ❌, 의도된 동작).

    세션 등록:
      ``python -m scripts.musinsa_login`` 으로 1회 수동 로그인.
    """

    source_name = "musinsa"

    def __init__(self, timeout: int = DEFAULT_TIMEOUT, prefer_member_price: bool = True):
        self.timeout = timeout
        self.prefer_member_price = prefer_member_price

    def fetch(self, product_url: str) -> CrawlResult:
        # 1. 같은 styleNo 의 다른 색상 variant URL 자동 발견
        variant_urls = _discover_color_variants(product_url) or [product_url]

        # 2. 단일 모드 vs 다중 모드
        if len(variant_urls) <= 1:
            return self._fetch_single(product_url)

        # 3. 다중 색상 — 비회원가 API 모드 강제 (사이즈별 옵션 추출 → 매칭 가능)
        # variant 별 goodsNm 의 공통 prefix 를 계산해 색상 정확히 추출
        #  예: '클래식 2 블랙(블랙 아웃솔)', '클래식 2 그레이' → prefix='클래식 2 ', 색상='블랙(블랙 아웃솔)'/'그레이'
        url_to_color: dict = {}
        try:
            import os as _os
            names_per_url = []
            for vurl in variant_urls:
                pid = _extract_product_id(vurl)
                if not pid:
                    continue
                try:
                    meta = self._fetch_meta(pid, vurl)
                    nm = ((meta or {}).get("data") or {}).get("goodsNm") or ""
                    names_per_url.append((vurl, nm))
                except Exception:
                    pass
            if names_per_url:
                common_prefix = _os.path.commonprefix([n for _, n in names_per_url])
                for vurl, nm in names_per_url:
                    color_part = nm[len(common_prefix):].strip()
                    if color_part:
                        url_to_color[vurl] = color_part
        except Exception as _e:
            import logging
            logging.getLogger(__name__).debug("[musinsa] 공통 prefix 계산 실패: %s", _e)

        merged_options = []
        product_name_first = None
        brand_first = ""
        discount_info_first = ""
        saved_pref = self.prefer_member_price
        self.prefer_member_price = False  # 사이즈별 9 옵션 추출용
        try:
            for vurl in variant_urls:
                try:
                    sub = self._fetch_single(vurl)
                    if not product_name_first:
                        product_name_first = sub.product_name_raw
                        brand_first = sub.brand
                        discount_info_first = sub.discount_info
                    # 다중 모드: variant 페이지의 색상으로 옵션의 color_text 덮어쓰기
                    forced_color = url_to_color.get(vurl)
                    if forced_color:
                        for opt in sub.options:
                            opt["color_text"] = forced_color
                    merged_options.extend(sub.options)
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).warning("[musinsa] variant %s fetch 실패: %s", vurl, e)
        finally:
            self.prefer_member_price = saved_pref
        return CrawlResult(
            source=self.source_name,
            product_url=product_url,
            product_name_raw=product_name_first or "",
            options=merged_options,
            brand=brand_first,
            discount_info=discount_info_first,
        )

    def _fetch_single(self, product_url: str) -> CrawlResult:
        # 비회원가 모드 (다중 색상 variant 사이즈 추출 전용) — 의도적으로 비로그인 API 사용
        if not self.prefer_member_price:
            return self._fetch_via_api(product_url)

        # ── 회원가 모드: 반드시 로그인 상태로만 크롤. 로그인 불가 시 비로그인 폴백 금지 (막는다) ──
        #    사용자 정책 (2026-06-05): 비로그인 가격은 회원가가 아님 → 잘못된 매입가 = 금전 손실.
        #    기존엔 Playwright 실패 시 _fetch_via_api 로 조용히 폴백했으나, 이제 예외를 위로 전파한다.
        from .base import LoginExpiredError
        # strict=True → DB 조회 실패는 그대로 전파(로그인 만료로 위장 ❌). 계정이 진짜
        # 없을 때만 None → 아래서 LoginExpiredError 로 차단.
        default_acc = _get_default_musinsa_account(strict=True)
        if not default_acc:
            raise LoginExpiredError(
                "musinsa",
                "대표 크롤 계정 미지정 또는 세션 파일 없음 — 회원가 크롤 불가 (비로그인 폴백 차단)",
            )
        db_source, acc_key = default_acc
        # [2026-06-05] 송장자동화 프로필(%LOCALAPPDATA%/invoice_profiles/무신사_{login_id})을
        #   그대로 사용 → 사용자가 송장자동화로 로그인해둔 세션 재사용(재로그인 불필요).
        #   account_key(영빈) 가 아니라 실제 login_id 로 프로필을 찾아야 매칭됨.
        from lemouton.auth.sourcing_credentials import default_store as _creds_store
        from lemouton.auth.profile_store import resolve_profile_dir
        _c = _creds_store().load_all().get(db_source, {}).get(acc_key, {})
        _login_id = _c.get("id", acc_key)
        _login_method = _c.get("login_method", "direct")
        _prof_dir = str(resolve_profile_dir(db_source, _login_id, _login_method))
        from .musinsa_playwright import MusinsaPlaywrightCrawler
        # Playwright 예외(LoginExpiredError 등)는 잡지 않고 위로 전파 → 호출자가 차단/재로그인 처리
        result = MusinsaPlaywrightCrawler(
            account_name=acc_key, profile_dir=_prof_dir).fetch(product_url)
        # account_name(storage_state) 모드는 비로그인 페이지를 자동 감지하지 못하므로,
        # 결과에 로그인 마커가 전무하면(세션 만료로 비로그인 크롤됨) 여기서 막는다.
        if result.options and not any(
            o.get("login_marker_present") or o.get("is_member_price")
            for o in result.options
        ):
            raise LoginExpiredError(
                "musinsa",
                f"로그인 마커 없음 — 세션 만료 추정 (account={acc_key}, 비로그인 폴백 차단)",
            )
        return result

    # ── 메타: V7 __NEXT_DATA__ goodsNm/brandName/normalPrice/salePrice 와 동일 의미 ──
    def _fetch_meta(self, product_id: str, product_url: str) -> dict:
        url = f"{GOODS_DETAIL_BASE}/api2/goods/{product_id}"
        resp = cffi_requests.get(
            url,
            impersonate=IMPERSONATE,
            headers=_build_headers(product_url),
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    # ── 옵션 정의: V7 DOM 드롭다운 색상·사이즈 목록과 동일 의미 ──
    def _fetch_options(self, product_id: str, product_url: str) -> dict:
        url = f"{GOODS_DETAIL_BASE}/api2/goods/{product_id}/options"
        resp = cffi_requests.get(
            url,
            impersonate=IMPERSONATE,
            headers=_build_headers(product_url),
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    # ── 재고/품절: V7 DOM (품절) 마커 / 잔여 N개 정규식과 동일 의미 ──
    def _fetch_inventories(
        self, product_id: str, product_url: str, option_value_nos: list[int]
    ) -> dict:
        if not option_value_nos:
            return {"data": []}
        url = f"{GOODS_DETAIL_BASE}/api2/goods/{product_id}/options/v2/prioritized-inventories"
        headers = _build_headers(product_url)
        headers["Content-Type"] = "application/json"
        resp = cffi_requests.post(
            url,
            json={"optionValueNos": option_value_nos},
            impersonate=IMPERSONATE,
            headers=headers,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def _fetch_via_api(self, product_url: str) -> CrawlResult:
        """비로그인 공개 API (V7 ``crawlNewPage``) 폴백 — ``salePrice`` 만 사용."""
        product_id = _extract_product_id(product_url)
        if not product_id:
            raise ValueError(f"musinsa product URL 에서 ID 추출 실패: {product_url}")

        # 1) 메타 — V7 parseDropdownItems 의 __NEXT_DATA__ 정규식과 동등
        meta = self._fetch_meta(product_id, product_url)
        meta_data = (meta or {}).get("data") or {}
        product_name = meta_data.get("goodsNm") or ""
        goods_price = meta_data.get("goodsPrice") or {}
        # V7: parseInt(salePrice) / parseInt(normalPrice)
        sale_price = int(goods_price.get("salePrice") or 0)
        origin_price = int(goods_price.get("normalPrice") or 0)
        # V7: ``if (!originPrice && salePrice) originPrice = salePrice;``
        if not origin_price and sale_price:
            origin_price = sale_price
        if not sale_price and origin_price:
            sale_price = origin_price
        # [2026-07-02 A6 fix] §4 폴백가 금지 — salePrice·normalPrice 둘 다 없어 sale_price<=0 이면
        #   0원 옵션을 생성하지 않고 크롤 실패로 표면화(raise). 0원이 매트릭스에 흘러 최저가로
        #   오인되면 손실. (SSG 는 옵션단위 continue, 여기는 상품 전체 가격 부재라 전체 실패로 처리.)
        if sale_price <= 0:
            raise ValueError(
                f"musinsa 비회원 API 가격 파싱 실패(salePrice/normalPrice 부재): {product_url}")

        # 2) 옵션 정의 — V7 색상·사이즈 드롭다운 목록과 동등
        opts = self._fetch_options(product_id, product_url)
        opts_data = (opts or {}).get("data") or {}
        basic_groups = opts_data.get("basic") or []
        option_items = opts_data.get("optionItems") or []

        # 3) 재고/품절 — V7 (품절) / 잔여 N개 와 동등
        all_value_nos: list[int] = []
        for grp in basic_groups:
            for v in grp.get("optionValues") or []:
                if v.get("no") is not None:
                    all_value_nos.append(int(v["no"]))
        inv_resp = self._fetch_inventories(product_id, product_url, all_value_nos)
        inv_list = (inv_resp or {}).get("data") or []
        # productVariantId == optionItem.no
        inv_by_variant: dict[int, dict] = {
            int(it["productVariantId"]): it for it in inv_list if "productVariantId" in it
        }

        # 4) optionItems → CrawlResult.options 행 생성
        # V7: dropdownCount=1 → option1=사이즈, option2=''
        #     dropdownCount=2 → option1=색상, option2=사이즈
        # API 의 ``basic`` 그룹 개수가 V7 의 dropdownCount 와 동등.
        is_color_size = len(basic_groups) >= 2
        options: list[dict] = []

        for it in option_items:
            variant_no = int(it.get("no") or 0)
            managed_code = it.get("managedCode") or ""
            # V7 규약: managedCode = "{option1}^{option2}"
            #   2 그룹: option1=색상, option2=사이즈
            #   1 그룹: option1=값(사이즈 or 단품), option2=''
            tok_a, tok_b = _split_managed_code(managed_code)
            if is_color_size:
                color_text = tok_a
                size_text = tok_b
            else:
                # V7 dropdownCount=1: option1 만 있음
                # 다중 색상 variant 모드에서는 각 페이지가 단일 색상이므로 goodsNm 마지막 토큰을
                # 색상으로 추정 (예: "르무통 클래식 블랙(화이트아웃솔)" → "블랙(화이트아웃솔)")
                _name_parts = (product_name or "").rsplit(" ", 1)
                color_text = _name_parts[-1] if len(_name_parts) > 1 else ""
                size_text = tok_a

            inv = inv_by_variant.get(variant_no, {})
            # 사용자 정책 (2026-05-06):
            #   품절(outOfStock): 0
            #   잔여 N (remainQuantity): N
            #   표시 없음: 충분 재고 → 999
            out_of_stock = bool(inv.get("outOfStock"))
            remain = inv.get("remainQuantity")
            # [2026-07-02 A6 fix] remain 이 문자열("5") 로 와도 int 비교 TypeError 안 나게 안전 변환.
            #   변환 실패(비정상값)는 수량미상(999) 으로 — 크래시로 옵션 통째 유실 방지.
            try:
                remain_i = int(remain) if remain is not None else None
            except (TypeError, ValueError):
                remain_i = None
            if out_of_stock:
                stock = 0
            elif remain_i is None:
                stock = 999
            else:
                stock = remain_i if remain_i >= 0 else 0

            # V7 option_id: `{productId}|{option1}|{option2}` 패턴 (T10 lemouton 과 동일 규약)
            options.append({
                "option_id": f"{product_id}|{color_text}|{size_text}",
                "color_text": color_text,
                "size_text": size_text,
                "price": sale_price,
                "stock": stock,
            })

        # V7 fallback: optionItems 가 0개면 단일 행 (단품)
        if not options:
            options.append({
                "option_id": f"{product_id}||",
                "color_text": "",
                "size_text": "",
                "price": sale_price,
                "stock": 999,
            })

        return CrawlResult(
            source=self.source_name,
            product_url=product_url,
            product_name_raw=product_name,
            options=options,
        )
