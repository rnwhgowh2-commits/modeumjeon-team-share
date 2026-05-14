"""무신사 (musinsa.com) 회원가 크롤러 — Playwright 기반.

모음전 자동화 ``modules/sourcing/musinsa.py`` 의 sync 포팅 + ``CrawlResult`` 인터페이스.

가격 3계층 (모음전 자동화 정책):
  · 정가             original_price      raw 원본
  · 계층1 확정매입가 sale_price          무신사 salePrice - 쿠폰
  · 계층2 예상매입가 benefit_price       계층1 - 등급할인 - 결제혜택 - 선할인 - (옵션)카드 - (옵션)보유적립

본 프로젝트 ``CrawlResult.options[i]`` 는 단일 ``price`` 필드를 갖기 때문에:
  · ``options[i]['price']`` = ``benefit_price`` (계층2, 회원가)
  · ``options[i]['original_price']``, ``options[i]['sale_price']``, ``options[i]['breakdown']``
    을 옵셔널로 함께 노출 (필요 시 합계 비교 / 보고서)

세션 파일 (``data/auth/무신사_default.json``) 이 없으면 ``RuntimeError`` 전파 →
디스패처가 비로그인 API 폴백.
"""
from __future__ import annotations

import logging
import re
from typing import Optional
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

from config import SOURCING_AUTH
from .base import AbstractCrawler, CrawlResult, LoginExpiredError
from ..auth import has_state, new_context_with_state


logger = logging.getLogger(__name__)


PRODUCT_ID_PATTERN = re.compile(r"/products/(\d+)")


# ─ JS 추출 스크립트 (모음전 자동화 _EXTRACT_JS 의 핵심부 1:1 포팅) ─────────
_EXTRACT_JS = """
async (cfg) => {
    const DROPDOWN_WAIT = cfg.dropdownWait || 200;
    const STOCK_CAP = cfg.stockCap || 10;

    function parsePrice(text) {
        const m = (text || '').replace(/\\s/g, '').match(/([0-9,]+)원/);
        return m ? parseInt(m[1].replace(/,/g, '')) : 0;
    }

    // ── 상품명 / 가격 ──────────────────────────────────
    const title = document.title || '';
    const name = title.split(' - ')[0].trim();

    const origEl = document.querySelector('[class*="DiscountWrap"]');
    let originalPrice = origEl ? parsePrice(origEl.innerText) : 0;

    const saleEl = document.querySelector('[class*="CalculatedPrice"]');
    let salePrice = saleEl ? parsePrice(saleEl.innerText) : 0;
    if (!salePrice) {
        const curEl = document.querySelector('[class*="CurrentPrice"]');
        salePrice = curEl ? parsePrice(curEl.innerText) : 0;
    }
    if (!salePrice && !originalPrice) {
        const totalEl = document.querySelector('[class*="PriceTotal"], [class*="price"]');
        if (totalEl) {
            const nums = (totalEl.innerText.match(/([0-9,]+)원/g) || [])
                .map(n => parseInt(n.replace(/[^0-9]/g, '')))
                .filter(v => v > 1000);
            if (nums.length >= 2) { originalPrice = Math.max(...nums); salePrice = Math.min(...nums); }
            else if (nums.length === 1) { originalPrice = nums[0]; salePrice = nums[0]; }
        }
    }
    if (!salePrice) salePrice = originalPrice;
    if (!originalPrice) originalPrice = salePrice;

    // ── 브랜드 ──────────────────────────────────
    let brand = '';
    const metaBrand = document.querySelector('meta[property="product:brand"], meta[name="brand"]');
    if (metaBrand) brand = (metaBrand.getAttribute('content') || '').trim();
    if (!brand) {
        const nameEl = document.querySelector('[class*="Brand__BrandName"]');
        if (nameEl) brand = (nameEl.innerText || '').trim();
    }
    if (!brand) {
        for (const a of document.querySelectorAll('a[href*="/brand/"]')) {
            const t = (a.innerText || '').trim();
            if (t && !/바로가기|더보기/.test(t) && t.length < 40) { brand = t; break; }
        }
    }

    // ── 항목별 할인 파싱 (계층2 산정용) ─────────────────────
    const breakdown = {
        grade_discount:        0,
        money_reward:          0,
        money_reward_rate:     0,
        pre_discount:          0,
        card_discount:         0,
        point_use_ignored:     0,
        coupon:                0,
        purchase_extra_reward: 0,  // ★ 신규 (2026-05-05): 구매 추가 적립 (활성 시 차감)
    };
    let couponName = '';
    let benefitPriceFromUI = 0;

    // ★ 2026-05-05 사용자 확정 정책 (누적식 매입가 산정):
    //   1. 결제수단 즉시할인 = 무시 (토스페이/카드 등)
    //   2. 결제수단 적립 (무신사 삼성카드 등) = 무시 (무신사머니만)
    //   3. 적립금 사용 = 0 강제 (이중차감 방지)
    //   4. 후기적립 항목 있으면 500원 고정 (일반 후기만)
    //   5. 활성 여부 매 크롤마다 화면에서 감지 (등급할인/등급적립/구매적립/선할인)
    //   6. 누적식: 표면가→쿠폰→후기→등급적립→무신사머니 (각 단계가 직전 결과 베이스)
    breakdown.grade_discount_active = false;   // 등급 할인 활성 여부
    breakdown.grade_discount_rate = 0;          // % (LV.X · X% 추출)
    breakdown.grade_reward_active = false;      // 등급 적립 (= 구매 적립) 활성 여부
    breakdown.grade_reward_rate = 0;            // % (LV.X · X% 추출)
    breakdown.purchase_reward_radio_on = false; // "구매 적립" 라디오 ✓ (활성 시 등급적립 적용)
    breakdown.pre_discount_radio_on = false;    // "적립금 선할인" 라디오 ✓
    breakdown.has_review_reward_item = false;   // 후기적립 +X원 항목 존재 → 500원 고정 차감

    // ★ 2026-05-06 무신사 신UI 검증 완료 (debug_fetch2.py):
    //   · MaxBenefitPrice__Wrap = 할인 영역 (요약). 클릭 안 해도 textContent 에 정보 있음
    //   · MaxBenefitPrice__PointSummaryWrap (드롭다운) → 클릭 시 PointDetailWrap 등장
    //     PointDetailWrap = 적립 상세 (등급적립, 후기적립, 무신사머니 적립)
    //   → 1) PointSummaryWrap 클릭 (적립 상세 펼침)
    //     2) Dimmed 제거 (오버레이 차단 방지)
    //     3) 가장 큰 textContent 가진 MaxBenefitPrice 요소에서 정규식 매칭
    document.querySelectorAll('[class*="Dimmed"], [class*="Modal"]').forEach(el => {
        try { el.remove(); } catch(_) {}
    });
    document.querySelectorAll('[class*="MaxBenefitPrice__PointSummaryWrap"]').forEach(el => {
        try { el.click(); } catch(_) {}
    });
    await new Promise(r => setTimeout(r, 800));

    // 가장 큰 MaxBenefitPrice 요소 찾기 (모든 정보 포함된 컨테이너)
    let wrap = null;
    let largestLen = 0;
    document.querySelectorAll('[class*="MaxBenefitPrice"]').forEach(el => {
        const len = (el.textContent || '').length;
        if (len > largestLen) { largestLen = len; wrap = el; }
    });
    if (!wrap) wrap = document.querySelector('[class*="MaxBenefitPrice"]');

    if (wrap) {
        // textContent = 모든 정보 (CSS 숨김 포함). 줄바꿈 없이 합쳐짐 → 정규식 직접 매칭
        const text = wrap.textContent || '';

        // 최대혜택가 (페이지 표시값 — 정보용)
        const bm = text.match(/([\\d,]+)\\s*원\\s*최대혜택가/);
        if (bm) benefitPriceFromUI = parseInt(bm[1].replace(/,/g, ''));

        // ── 즉시 차감 항목 ───────────────────────────────
        // 등급할인: "등급 할인 -X원" (불가면 매칭 안됨)
        let m = text.match(/등급\\s*할인\\s*-([\\d,]+)\\s*원/);
        if (m) {
            breakdown.grade_discount = parseInt(m[1].replace(/,/g, ''));
            breakdown.grade_discount_active = true;
            if (salePrice > 0) {
                breakdown.grade_discount_rate = breakdown.grade_discount / salePrice;
            }
        }

        // 적립금 사용: "보유 적립금 사용 (현재 X원 보유)-Y원"
        m = text.match(/(?:보유\\s*)?적립금\\s*사용[^-]*-([\\d,]+)\\s*원/);
        if (m) breakdown.point_use_ignored = parseInt(m[1].replace(/,/g, ''));

        // 적립금 선할인: "적립금 선할인 -X원" (불가면 매칭 안됨)
        m = text.match(/적립금\\s*선할인\\s*-([\\d,]+)\\s*원/);
        if (m) {
            breakdown.pre_discount = parseInt(m[1].replace(/,/g, ''));
            breakdown.pre_discount_radio_on = true;
        }

        // 상품 쿠폰: "상품 쿠폰 -X원" 또는 쿠폰명 다음 -X원
        m = text.match(/상품\\s*쿠폰[^-가-힣]*-([\\d,]+)\\s*원/);
        if (m) breakdown.coupon = parseInt(m[1].replace(/,/g, ''));

        // ── 적립 항목 (양수, 누적 베이스 적용) ──────────────
        // 구매 적립 라디오 ✓ 여부: "구매 적립 (+X원)" — + 가 있으면 활성
        m = text.match(/구매\\s*적립\\s*\\(\\+([\\d,]+)\\s*원\\)/);
        if (m) {
            breakdown.purchase_reward_radio_on = true;
            breakdown.grade_reward_active = true;
        }

        // 등급 적립률 + 금액: "등급 적립 (LV.X 블랙다이아몬드 · 4%)4,540원"
        m = text.match(/등급\\s*적립\\s*\\(LV\\.\\d+[^·)]*·\\s*(\\d+(?:\\.\\d+)?)\\s*%\\)\\s*([\\d,]+)\\s*원/);
        if (m) {
            breakdown.grade_reward_rate = parseFloat(m[1]) / 100;
            const ui_amt = parseInt(m[2].replace(/,/g, ''));
            if (ui_amt > 0) breakdown.grade_reward_active = true;
        }

        // 후기 적립: "후기 적립X원" — 양수면 활성 (정책상 500원 고정 차감)
        m = text.match(/후기\\s*적립\\s*([\\d,]+)\\s*원/);
        if (m) {
            const amt = parseInt(m[1].replace(/,/g, ''));
            if (amt > 0) breakdown.has_review_reward_item = true;
        }

        // 구매 추가 적립: "구매 추가 적립X원"
        m = text.match(/구매\\s*추가\\s*적립\\s*([\\d,]+)\\s*원/);
        if (m) breakdown.purchase_extra_reward = parseInt(m[1].replace(/,/g, ''));

        // 무신사머니 적립률 + 금액: "무신사머니 결제 시 4% 적립4,170원"
        m = text.match(/무신사\\s*머니\\s*결제\\s*시\\s*(\\d+(?:\\.\\d+)?)\\s*%\\s*적립\\s*([\\d,]+)\\s*원/);
        if (m) {
            breakdown.money_reward_rate = parseFloat(m[1]) / 100;
            breakdown.money_reward = parseInt(m[2].replace(/,/g, ''));
        }

        // ── Fail-safe 검증용 메타데이터 (3중 강화) ─────────
        breakdown.wrap_found = true;
        breakdown.text_length = text.length;
        breakdown.has_grade_section = /등급\\s*적립|등급\\s*할인/.test(text);
        breakdown.has_review_section = /후기\\s*적립/.test(text);
        breakdown.has_money_section = /무신사\\s*머니/.test(text);
        breakdown.has_my_discount_section = /나의\\s*할인가|사용\\s*혜택/.test(text);
        // ★ 펼침 직접 증거 — PointDetailWrap 은 PointSummaryWrap 클릭 시만 등장
        breakdown.point_detail_wrap_found = !!document.querySelector('[class*="MaxBenefitPrice__PointDetailWrap"]');
    } else {
        breakdown.wrap_found = false;
    }

    // ※ 라디오 활성 감지는 텍스트 정규식으로 위에서 처리 ("구매 적립 (+X원)" 패턴)
    //   기존 input[type=radio] 스캔은 불필요 — 무신사 새 UI 는 React 커스텀 컴포넌트라 input 없을 수 있음

    // ── 옵션 (드롭다운 색상×사이즈) ─────────────────────────
    const options = [];
    const triggers = document.querySelectorAll('[data-mds="DropdownTriggerBox"]');

    function parseSizeItem(item) {
        const text = item.innerText.trim();
        const soldout = text.includes('품절') || text.includes('재입고');
        const name = text.split('\\n')[0]
            .replace(/\\s*\\(?\\s*(품절|재입고\\s*알림|잔여\\s*\\d+\\s*개)\\s*\\)?.*$/g, '')
            .trim();
        let qty = STOCK_CAP;
        const m = text.match(/잔여\\s*(\\d+)\\s*개/);
        if (m) qty = parseInt(m[1]);
        return { name, soldout, qty: soldout ? 0 : Math.min(qty, STOCK_CAP) };
    }

    if (triggers.length === 0) {
        options.push({ color: '', size: '', soldout: false, qty: STOCK_CAP });
    } else if (triggers.length === 1) {
        triggers[0].click();
        await new Promise(r => setTimeout(r, DROPDOWN_WAIT));
        for (const item of document.querySelectorAll('[data-mds="StaticDropdownMenuItem"]')) {
            const s = parseSizeItem(item);
            options.push({ color: '', size: s.name, soldout: s.soldout, qty: s.qty });
        }
        document.body.click();
    } else {
        triggers[0].click();
        await new Promise(r => setTimeout(r, DROPDOWN_WAIT));
        const colors = [];
        for (const item of document.querySelectorAll('[data-mds="StaticDropdownMenuItem"]')) {
            const text = item.innerText.trim();
            colors.push({
                name: text.replace(/\\s*(품절|재입고 알림).*/g, '').trim(),
                soldout: text.includes('품절'),
            });
        }
        for (let ci = 0; ci < colors.length; ci++) {
            if (colors[ci].soldout) {
                options.push({ color: colors[ci].name, size: '', soldout: true, qty: 0 });
                continue;
            }
            const cMenus = document.querySelectorAll('[data-mds="StaticDropdownMenuItem"]');
            if (ci < cMenus.length) {
                cMenus[ci].click();
                await new Promise(r => setTimeout(r, DROPDOWN_WAIT));
            }
            triggers[1].click();
            await new Promise(r => setTimeout(r, DROPDOWN_WAIT));
            for (const item of document.querySelectorAll('[data-mds="StaticDropdownMenuItem"]')) {
                const s = parseSizeItem(item);
                options.push({ color: colors[ci].name, size: s.name, soldout: s.soldout, qty: s.qty });
            }
            document.body.click();
            await new Promise(r => setTimeout(r, 50));
            if (ci < colors.length - 1) {
                triggers[0].click();
                await new Promise(r => setTimeout(r, DROPDOWN_WAIT));
            }
        }
    }

    return { name, brand, originalPrice, salePrice, benefitPriceFromUI,
             breakdown, couponName, options };
}
"""


class MusinsaPlaywrightCrawler(AbstractCrawler):
    """무신사 회원가 크롤러 (Playwright + storage_state).

    필수 조건:
      ``has_state('무신사', 'default')`` 가 True 여야 함.
      세션이 없으면 ``RuntimeError`` 발생 → 디스패처가 비로그인 API 폴백.
    """

    source_name = "musinsa"

    def __init__(self, account_name: str = "default", headless: bool = True,
                 profile_dir: Optional[str] = None):
        """
        Args:
            account_name: storage_state 파일 이름 (legacy)
            headless: 브라우저 GUI 표시 여부
            profile_dir: ★ Playwright user_data_dir (대표 크롤 계정 ProfileStore 경로).
                         지정 시 launch_persistent_context 로 영구 프로필 사용 (로그인 상태 유지).
                         미지정 시 storage_state 기반 (legacy).
        """
        self.account_name = account_name
        self.headless = headless
        self.profile_dir = profile_dir

    def fetch(self, product_url: str) -> CrawlResult:
        # ★ profile_dir 모드 — launch_persistent_context (영구 프로필 = 로그인 유지)
        if self.profile_dir:
            from pathlib import Path
            prof_path = Path(self.profile_dir)
            if not prof_path.exists():
                raise RuntimeError(
                    f"프로필 디렉터리 없음: {self.profile_dir}\n"
                    f"소싱처 계정 페이지에서 [🔑 자동 로그인] 1회 실행 필요"
                )
            with sync_playwright() as pw:
                # ★ Chrome 우선 — scrapers/base.py 의 로그인 마법사가 channel="chrome" 으로
                #    쿠키를 저장하므로 동일 채널로 띄워야 prefs/Local State 100% 호환
                # → Edge 폴백 (Chrome 미설치)
                # → bundled chromium 최후 폴백
                context = None
                last_err = None
                args = ["--disable-blink-features=AutomationControlled"]
                for ch in ("chrome", "msedge", None):
                    try:
                        kwargs = dict(
                            user_data_dir=str(prof_path),
                            headless=self.headless,
                            args=args,
                        )
                        if ch:
                            kwargs["channel"] = ch
                        context = pw.chromium.launch_persistent_context(**kwargs)
                        logger.info("[무신사] 채널: %s", ch or "bundled chromium")
                        break
                    except Exception as e:
                        last_err = e
                        logger.warning("[무신사] 채널 %s 실패: %s", ch or "bundled", e)
                if context is None:
                    raise RuntimeError(f"모든 채널 실패: {last_err}")
                try:
                    page = context.new_page()
                    try:
                        return self._crawl(page, product_url)
                    finally:
                        page.close()
                finally:
                    context.close()
            return  # unreachable

        # ── Legacy: storage_state 기반 (account_name)
        # 한글/영문 source 둘 다 시도
        _src_used = None
        for _src in ("무신사", "musinsa"):
            if has_state(_src, self.account_name):
                _src_used = _src
                break
        if not _src_used:
            raise RuntimeError(
                f"무신사 로그인 세션 없음 (account={self.account_name}) — `python -m scripts.musinsa_login` 으로 1회 로그인 필요"
            )

        with sync_playwright() as pw:
            browser, context = new_context_with_state(pw, _src_used, self.account_name, browser=None)
            try:
                page = context.new_page()
                try:
                    return self._crawl(page, product_url)
                finally:
                    page.close()
            finally:
                context.close()
                browser.close()

    def _crawl(self, page, product_url: str) -> CrawlResult:
        timeout = SOURCING_AUTH.get("crawl_timeout_ms", 25000)
        csr_wait = SOURCING_AUTH.get("csr_wait_ms", 5000)

        page.goto(product_url, timeout=timeout, wait_until="domcontentloaded")
        try:
            page.wait_for_selector(
                '[data-mds="DropdownTriggerBox"], [class*="CalculatedPrice"]',
                timeout=csr_wait,
            )
        except PWTimeout:
            pass

        # ★ 송장전송기 무제한 로그인 패턴 — 비로그인 페이지 감지 (profile_dir 모드만)
        #   profile_dir 가 지정됐다는 건 회원가 크롤 의도 → 비로그인이면 LoginExpiredError 신호
        #   호출자 (api_pricing 등) 가 잡아서 자동 재로그인 + 재시도
        if self.profile_dir:
            try:
                login_check = page.evaluate("""
                    () => {
                        // 우상단 로그인/회원가입 버튼 = 비로그인
                        const navText = (document.querySelector('header, nav, [class*="Gnb"], [class*="header"]')?.textContent || '');
                        const isNotLoggedIn = /로그인 ?\\/ ?회원가입|로그인 \\| 회원가입/.test(navText);
                        // 회원 전용 버튼이 disabled = 비로그인
                        const memberBtn = document.querySelector('button[class*="회원"], [aria-label*="회원 전용"]');
                        return {
                            not_logged_in: isNotLoggedIn,
                            url: location.href,
                            redirect_to_login: /\\/login|\\/auth\\/login|member\\.one/.test(location.href),
                        };
                    }
                """)
                if login_check.get("not_logged_in") or login_check.get("redirect_to_login"):
                    raise LoginExpiredError(
                        "musinsa",
                        f"비로그인 페이지 감지 (url={login_check.get('url','')[:60]})"
                    )
            except LoginExpiredError:
                raise
            except Exception as e:
                logger.debug("[무신사] 로그인 검사 예외 (무시): %s", e)

        raw = page.evaluate(
            _EXTRACT_JS,
            {
                "dropdownWait": SOURCING_AUTH.get("dropdown_interval_ms", 200),
                "stockCap":     SOURCING_AUTH.get("stock_cap", 10),
            },
        )

        product_id = self._extract_product_id(product_url)
        product_name = raw.get("name") or ""
        brand = raw.get("brand") or ""
        orig_price = int(raw.get("originalPrice") or 0)
        sale_price = int(raw.get("salePrice") or 0)

        if orig_price == 0 and sale_price == 0:
            raise RuntimeError(f"무신사 가격 파싱 실패 (0원) — {product_url}")

        # ════════════════════════════════════════════════
        # 계층 산정 — 2026-05-05 사용자 확정 정책 (누적식 5단계)
        # ════════════════════════════════════════════════
        # 정책 요약:
        #   - 적립금 사용 = 0 강제 (이중차감 방지)
        #   - 결제수단 즉시할인 (토스페이/카드) = 무시
        #   - 결제수단 적립 (무신사 삼성카드 등) = 무시 (무신사머니만)
        #   - 후기적립 항목 있으면 500원 고정 (일반 후기 기준)
        #   - 라디오 = 항상 "구매 적립" 가정 (선할인 무시)
        #   - 누적식: 직전 단계 결과를 다음 단계 베이스로
        bd = raw.get("breakdown") or {}

        # ★ Fail-safe 검증 — 사용자 확정 정책 (2026-05-05):
        #   "상세 펼쳐서 정보 추출 못하면 차라리 크롤링 실패하는게 나음. 가격 잘못되면 엄청난 금전적 손실"
        #   ★ 2026-05-06 강화: 3중 검증 + Sanity check (LV별 한계율 + 매입가 비율)
        wrap_found             = bool(bd.get("wrap_found"))
        text_length            = int(bd.get("text_length") or 0)
        point_detail_wrap_found = bool(bd.get("point_detail_wrap_found"))
        has_grade              = bool(bd.get("has_grade_section"))
        has_review             = bool(bd.get("has_review_section"))
        has_money              = bool(bd.get("has_money_section"))
        has_my_discount        = bool(bd.get("has_my_discount_section"))

        # 검증 1: wrap 발견
        if not wrap_found:
            raise RuntimeError(
                "[무신사] 가격 상세 영역(MaxBenefitPrice) 미발견 — "
                "페이지 구조 변경 가능성. 가격 산출 불가 (Fail-safe)"
            )
        # 검증 2: 펼침 직접 증거 (PointDetailWrap 존재)
        if not point_detail_wrap_found:
            raise RuntimeError(
                "[무신사] PointDetailWrap 미발견 — 적립 상세 펼침 실패 (PointSummaryWrap 클릭 무효). "
                "가격 산출 불가 (Fail-safe)"
            )
        # 검증 3: textContent 충분히 길이 (펼친 후 ≥ 300자)
        if text_length < 300:
            raise RuntimeError(
                f"[무신사] 가격 상세 textContent 너무 짧음 ({text_length}자, 정상=500+자) — "
                f"펼침 불완전. 가격 산출 불가 (Fail-safe)"
            )
        # 검증 4: 핵심 섹션 3개 모두 노출 (이전 2개 → 3개로 강화)
        if not (has_grade and has_review and has_money):
            raise RuntimeError(
                f"[무신사] 핵심 섹션 미노출 — "
                f"등급={has_grade} 후기={has_review} 무신사머니={has_money}. "
                f"가격 산출 불가 (Fail-safe)"
            )
        # 검증 5: "나의 할인가" 또는 "사용 혜택" 노출 = 로그인 + 가격 영역 정상
        if not has_my_discount:
            raise RuntimeError(
                "[무신사] '나의 할인가' 영역 미노출 — 비로그인 또는 페이지 변경. "
                "가격 산출 불가 (Fail-safe)"
            )

        # ── Sanity check: LV별 한계율 ──────────────────────
        _grade_disc_rate = float(bd.get("grade_discount_rate") or 0)
        _grade_rwd_rate  = float(bd.get("grade_reward_rate") or 0)
        _money_rwd_rate  = float(bd.get("money_reward_rate") or 0)
        if _grade_disc_rate > 0.05:  # 등급할인 LV별 한계: 최대 4% (5% 초과 비정상)
            raise RuntimeError(
                f"[무신사] 등급할인율 비정상 ({_grade_disc_rate*100:.2f}% > 5%). 추출 오류 가능성 (Fail-safe)"
            )
        if _grade_rwd_rate > 0.05:
            raise RuntimeError(
                f"[무신사] 등급적립률 비정상 ({_grade_rwd_rate*100:.2f}% > 5%). 추출 오류 가능성 (Fail-safe)"
            )
        if _money_rwd_rate > 0.05:  # 무신사머니: LV.9 = 3%(기본) + 1%(프로모션) = 4% 한계 (5% 초과 비정상)
            raise RuntimeError(
                f"[무신사] 무신사머니 적립률 비정상 ({_money_rwd_rate*100:.2f}% > 5% — LV별 한계 4%). "
                f"추출 오류 가능성 (Fail-safe)"
            )
        grade_discount        = int(bd.get("grade_discount") or 0)         # 즉시 차감 (활성 시)
        coupon                = int(bd.get("coupon") or 0)                 # 즉시 차감
        # pre_disc/card/point_use = 정책상 우리 매입가에 안 씀 (정보용으로만 보존)
        pre_disc              = int(bd.get("pre_discount") or 0)
        card                  = int(bd.get("card_discount") or 0)
        point_use             = int(bd.get("point_use_ignored") or 0)
        # 적립률
        grade_reward_active   = bool(bd.get("grade_reward_active"))
        grade_reward_rate     = float(bd.get("grade_reward_rate") or 0)    # LV별 (예: LV.9 = 0.04)
        money_reward_rate     = float(bd.get("money_reward_rate") or 0)    # LV별 (기본+프로모션 합)
        money_reward_ui       = int(bd.get("money_reward") or 0)
        # 신규 추출
        has_review_reward     = bool(bd.get("has_review_reward_item"))
        purchase_extra_reward = int(bd.get("purchase_extra_reward") or 0)

        # ── 단계 1: 표면가 - 등급할인(활성시) - 쿠폰 - 선할인(정책0) - 적립금사용(정책0)
        base1 = max(sale_price - grade_discount - coupon, 0)

        # ── 단계 2: 후기적립 (항목 있을때만, 500원 고정 — 일반 후기)
        review_reward_fixed = 500 if has_review_reward else 0
        base2 = max(base1 - review_reward_fixed, 0)

        # ── 단계 3: 등급 적립 (= 구매 적립, 활성 시) + 구매 추가 적립 (활성 시)
        grade_reward_amt = int(base2 * grade_reward_rate) if (grade_reward_active and grade_reward_rate > 0) else 0
        base3 = max(base2 - grade_reward_amt - purchase_extra_reward, 0)

        # ── 단계 4: 무신사머니 적립 (LV별 % 누적 베이스 적용)
        if money_reward_rate > 0:
            money_reward_amt = int(base3 * money_reward_rate)
            payment_source = f"musinsa_money({money_reward_rate*100:.2f}%)"
        else:
            money_reward_amt = money_reward_ui  # rate 추출 실패 시 화면값 폴백
            payment_source = "musinsa_money_ui_fallback"

        tier1_confirmed = base1  # 호환성 (기존 코드가 참조)
        payment_benefit = money_reward_amt
        tier2_expected = max(base3 - money_reward_amt, 0)

        # ── Sanity check (매입가 비율) ─────────────────────
        #   매입가가 sale_price 의 50%~100% 범위 벗어나면 비정상 (잘못된 추출 가능성)
        if sale_price > 0:
            ratio = tier2_expected / sale_price
            if ratio < 0.50:
                raise RuntimeError(
                    f"[무신사] 매입가 비율 비정상 ({ratio*100:.1f}% < 50%) — "
                    f"tier2={tier2_expected:,}원 / sale={sale_price:,}원. 과차감 가능성 (Fail-safe)"
                )
            if ratio > 1.0:
                raise RuntimeError(
                    f"[무신사] 매입가가 sale_price 보다 큼 ({ratio*100:.1f}%) — 산식 오류 (Fail-safe)"
                )
            # 차감 합계 (sale - tier2) 가 sale 의 30% 초과면 의심 (과차감)
            total_deduction = sale_price - tier2_expected
            if total_deduction > sale_price * 0.30:
                raise RuntimeError(
                    f"[무신사] 차감 합계 과다 ({total_deduction:,}원, {total_deduction/sale_price*100:.1f}% of sale) "
                    f"— 30% 초과 비정상 (Fail-safe)"
                )

        # 옵션 → CrawlResult.options
        options: list[dict] = []
        for opt in raw.get("options") or []:
            color = opt.get("color") or ""
            size = opt.get("size") or ""
            soldout = bool(opt.get("soldout"))
            qty = int(opt.get("qty") or 0)
            options.append({
                "option_id": f"{product_id}|{color}|{size}",
                "color_text": color,
                "size_text": size,
                # ★ price = 계층2 (회원가) — 마켓 가격 산정의 기준
                "price": tier2_expected,
                "stock": 0 if soldout else qty,
                # 추가 진단 필드 (옵셔널 — 호출자가 사용할 수 있음)
                "original_price": orig_price,
                "sale_price": tier1_confirmed,
                "benefit_price": tier2_expected,
                "breakdown": {
                    # 즉시 차감 항목 (활성 시)
                    "grade_discount":        grade_discount,
                    "coupon":                coupon,
                    "pre_discount":          pre_disc,         # 정책 미사용 (구매적립 선택)
                    "card_discount":         card,             # 정책 미사용
                    "point_use_ignored":     point_use,        # 정책 미사용 (이중차감 방지)
                    # 적립 차감 항목 (누적식)
                    "review_reward_fixed":   review_reward_fixed,
                    "grade_reward_active":   grade_reward_active,
                    "grade_reward_rate":     grade_reward_rate,
                    "grade_reward_amount":   grade_reward_amt,
                    "purchase_extra_reward": purchase_extra_reward,
                    "money_reward":          money_reward_ui,
                    "money_reward_rate":     money_reward_rate,
                    "money_reward_amount":   money_reward_amt,
                    "payment_benefit":       payment_benefit,
                    "payment_source":        payment_source,
                    # 누적식 단계별 베이스 (디버깅)
                    "base1_after_grade":     base1,
                    "base2_after_review":    base2,
                    "base3_after_grade_rwd": base3,
                    "ui_max_benefit_price":  int(raw.get("benefitPriceFromUI") or 0),
                },
            })

        if not options:
            options.append({
                "option_id": f"{product_id}||",
                "color_text": "", "size_text": "",
                "price": tier2_expected, "stock": SOURCING_AUTH.get("stock_cap", 10),
                "original_price": orig_price,
                "sale_price": tier1_confirmed,
                "benefit_price": tier2_expected,
            })

        coupon_name = raw.get("couponName") or ""
        # 누적식 정책 요약 텍스트
        parts = []
        if grade_discount > 0:
            parts.append(f"등급할인 -{grade_discount:,}원")
        if grade_reward_active and grade_reward_rate > 0:
            parts.append(f"등급적립 {grade_reward_rate*100:.1f}%")
        if purchase_extra_reward > 0:
            parts.append(f"구매추가 +{purchase_extra_reward:,}원")
        if review_reward_fixed > 0:
            parts.append(f"후기 +{review_reward_fixed}원")
        if money_reward_rate > 0:
            parts.append(f"무신사머니 {money_reward_rate*100:.1f}%")
        if coupon > 0:
            parts.append(f"쿠폰 -{coupon:,}원")
        discount_info = " / ".join(parts) if parts else ""

        return CrawlResult(
            source=self.source_name,
            product_url=product_url,
            product_name_raw=product_name,
            options=options,
            brand=brand or "무신사",
            discount_info=discount_info,
        )

    @staticmethod
    def _extract_product_id(url: str) -> str:
        m = PRODUCT_ID_PATTERN.search(url)
        return m.group(1) if m else ""
