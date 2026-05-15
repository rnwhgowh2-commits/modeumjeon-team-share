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


class ExpandFailedError(RuntimeError):
    """무신사 PDP 의 적립 상세 펼침 실패 — 재시도 가치 있음.

    이 예외는 fetch 외부에서 catch 후 page.reload + 1회 재시도 권장.
    재시도 후에도 실패 시 그대로 raise → 디스패처가 SourceProduct.last_status
    = 'extract_failed' 저장 + 매트릭스 UI 에 ⚠ 표시.
    """
    pass


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
    // ★ 2026-05-15 — 펼침 신뢰성 강화 (사용자 정정 후):
    //   기존 800ms 단발 클릭 → 200ms × 6회 재시도 + PointDetailWrap 확인 후 break
    //   실측: 첫 클릭 후 React 렌더링까지 평균 400ms, 최악 1200ms
    document.querySelectorAll('[class*="Dimmed"], [class*="Modal"]').forEach(el => {
        try { el.remove(); } catch(_) {}
    });
    // ★ 2026-05-15 정정 #4 — "나의 할인가" 영역 lazy load 발동 (구매적립/선할인 라디오 노출).
    //   원인: PDP 의 "나의 할인가" 영역이 lazy render. scroll + CollapseButton 클릭 필요.
    window.scrollTo(0, 800);
    await new Promise(r => setTimeout(r, 1500));
    window.scrollTo(0, 0);
    await new Promise(r => setTimeout(r, 1500));
    document.querySelectorAll('[class*="MaxBenefitPriceTitle__CollapseButton"]').forEach(el => {
        try { el.click(); } catch(_) {}
    });
    await new Promise(r => setTimeout(r, 800));
    // ★ 2026-05-15 정정 #6 — 적립금사용 체크박스 자동 OFF (우리 정책 무시 + 베이스 일관)
    //   원인: 사이트 default 가 "적립금사용 ON" (보유 적립금 자동 차감)
    //   → 모든 적립 amount 가 (적립금사용 차감 후 베이스) × % 로 표시
    //   → 우리 정책 (적립금사용 무시) 와 일관 위해 체크박스 자동 해제
    document.querySelectorAll('input[type="checkbox"]').forEach(c => {
        const parent = c.closest('label, div, [class*="Wrapper"], [class*="Section"]');
        const lbl = (parent ? parent.textContent : (c.parentElement ? c.parentElement.textContent : '')) || '';
        if (/적립금\\s*사용/.test(lbl) && c.checked) {
            try { c.click(); } catch(_) {}
        }
    });
    await new Promise(r => setTimeout(r, 800));
    // ★ 2026-05-15 정정 #2 — 펼침 성공 검증 강화 + 다중 전략 + 실패 시 명확 알림
    //   기존 위약 검증 (PointDetailWrap 등장만 확인) → 진짜 성공 검증 (핵심 텍스트 존재)
    //   진짜 성공 = PointDetailWrap 안에 "후기 적립" / "등급 적립" / "결제수단 적립" 중 하나 이상
    //   재시도 전략:
    //     시도 1~10: PointSummaryWrap 클릭 (현재) + 500ms wait + 검증
    //     시도 11~15: aria-expanded=false 모든 버튼 클릭 (전략 B) + 800ms wait + 검증
    //     모두 실패 → expand_result.ok=false → Python 측 fetch 재시도 (page.reload 후)
    async function expandPointDetail(maxRetry) {
        const successMarkers = /후기\\s*적립|등급\\s*적립|결제수단\\s*적립/;
        let lastTextLen = 0;
        for (let i = 0; i < maxRetry; i++) {
            // 전략 A: PointSummaryWrap 직접 클릭 (시도 1~10)
            // 전략 B: 추가로 모든 aria-expanded=false 버튼 (시도 11+)
            document.querySelectorAll('[class*="MaxBenefitPrice__PointSummaryWrap"]').forEach(el => {
                try { el.click(); } catch(_) {}
            });
            if (i >= 10) {
                document.querySelectorAll('button[aria-expanded="false"]').forEach(el => {
                    try { el.click(); } catch(_) {}
                });
            }
            // wait — 시도 횟수 증가에 따라 점진 증가 (React 가 늦게 렌더 케이스)
            const waitMs = (i < 10) ? 500 : 800;
            await new Promise(r => setTimeout(r, waitMs));
            // ★ 진짜 성공 검증 — PointDetailWrap 안에 핵심 텍스트
            const detail = document.querySelector('[class*="MaxBenefitPrice__PointDetailWrap"]');
            if (detail) {
                const txt = detail.textContent || '';
                lastTextLen = txt.length;
                if (successMarkers.test(txt)) {
                    // 한 번 더 대기 — 모든 자식 렌더 완료
                    await new Promise(r => setTimeout(r, 300));
                    return { ok: true, attempt: i+1, txt_len: txt.length };
                }
            }
        }
        return { ok: false, attempts: maxRetry, last_text_len: lastTextLen };
    }
    var expandResult = await expandPointDetail(15);

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
        // 등급할인: "등급 할인 (LV.X ... · Y%)-Z원" (2026-05-15 사용자 정정)
        //   기존 패턴 "등급 할인 -X원" 은 안 잡힘 (UI 가 LV/% 정보 포함)
        //   "불가" 케이스는 매칭 안됨 (정상 — 비활성)
        let m = text.match(/등급\\s*할인\\s*\\(LV\\.\\d+[^·)]*·\\s*(\\d+(?:\\.\\d+)?)\\s*%\\)\\s*-([\\d,]+)\\s*원/);
        if (m) {
            breakdown.grade_discount = parseInt(m[2].replace(/,/g, ''));
            breakdown.grade_discount_active = true;
            breakdown.grade_discount_rate = parseFloat(m[1]) / 100;
        } else {
            // Legacy fallback (구버전 UI 호환)
            m = text.match(/등급\\s*할인\\s*-([\\d,]+)\\s*원/);
            if (m) {
                breakdown.grade_discount = parseInt(m[1].replace(/,/g, ''));
                breakdown.grade_discount_active = true;
                if (salePrice > 0) {
                    breakdown.grade_discount_rate = breakdown.grade_discount / salePrice;
                }
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

        // 상품 쿠폰: 2026-05-15 사용자 정정 — UI 패턴 분석:
        //   · "사용가능 쿠폰 없음" → 매칭 안됨 (정상)
        //   · "상품 쿠폰<쿠폰명>쿠폰변경-65,150원" → 추출
        //   · "정기쿠폰" 라벨 (월 1회 자동) → 정책상 제외
        //   · "특별 혜택 XX% 쿠폰" → 사용자 명시 정기/특별 쿠폰 → 제외
        //   · 30% 초과 할인 쿠폰 → 특별/타깃 쿠폰 가능성 → 휴리스틱 제외
        // 알고리즘: '상품 쿠폰' ~ 다음 섹션('적립금 사용'/'구매 적립'/'제휴카드') 사이를
        //          잘라서 -X원 추출 + 라벨 검사.
        const couponSectionMatch = text.match(/상품\\s*쿠폰([\\s\\S]*?)(?=적립금\\s*사용|구매\\s*적립|제휴카드)/);
        if (couponSectionMatch) {
            const section = couponSectionMatch[1] || '';
            // 2026-05-15 사용자 정정: "월 1회 정기쿠폰" 만 제외. 특별 혜택 / % 휴리스틱 제거.
            const isRegularCoupon = /월\\s*1\\s*회|정기\\s*쿠폰/.test(section);
            const amtMatch = section.match(/-([\\d,]+)\\s*원/);
            if (amtMatch) {
                const amt = parseInt(amtMatch[1].replace(/,/g, ''));
                if (!isRegularCoupon) {
                    breakdown.coupon = amt;
                    const nameMatch = section.match(/^\\s*([^\\d-]+?)쿠폰\\s*변경/);
                    if (nameMatch) couponName = (nameMatch[1] || '').trim();
                } else {
                    breakdown.coupon_skipped_regular = true;
                    breakdown.coupon_skip_reason = '월 1회 정기 쿠폰';
                    breakdown.coupon_skipped_amount = amt;
                }
            }
        }

        // ── 장바구니 쿠폰 (2026-05-15 사용자 정정 — PDP 에 노출됨) ──
        // 예: "무탠다드 슈퍼세일 1만원 장바구니 쿠폰 / 만료 1일 전 · 10만원 이상 구매 시 1만원 추가 할인"
        //   - 정책: 조건 미충족이어도 표시 ✓ / 적용 ✗ (사용자 명세)
        //   - 페이지 전체 textContent 검색 (PDP 상단 띠 영역에 노출)
        // ★ 2026-05-15 정정 #3 — 더 유연한 정규식.
        //   기존: "이상 구매" 와 "추가 할인" 사이 80자 제한 → 띠 영역 다른 텍스트 끼면 매칭 X
        //   정정: 200자 + [\s\S] (newline 포함) + "(추가)?할인" 옵션
        breakdown.cart_coupons = [];
        const pageText = document.body.textContent || '';
        const cartCouponRe = /([가-힣A-Za-z][^/\\n]{0,50}?장바구니\\s*쿠폰)[\\s\\S]{0,200}?([\\d,]+)\\s*(만|천)?\\s*원?\\s*이상\\s*(?:구매)?[\\s\\S]{0,80}?([\\d,]+)\\s*(만|천)?\\s*원\\s*(?:추가\\s*)?할인/g;
        let cmatch;
        const seen = new Set();
        while ((cmatch = cartCouponRe.exec(pageText)) !== null) {
            const name = (cmatch[1] || '').trim().replace(/\\s+/g, ' ');
            const minNum = parseInt((cmatch[2] || '').replace(/,/g, '')) || 0;
            const minMul = (cmatch[3] === '만') ? 10000 : (cmatch[3] === '천' ? 1000 : 1);
            const discNum = parseInt((cmatch[4] || '').replace(/,/g, '')) || 0;
            const discMul = (cmatch[5] === '만') ? 10000 : (cmatch[5] === '천' ? 1000 : 1);
            const minAmt = minNum * minMul;
            const discAmt = discNum * discMul;
            const key = `${name}|${minAmt}|${discAmt}`;
            if (seen.has(key)) continue;
            seen.add(key);
            if (name && minAmt > 0 && discAmt > 0) {
                breakdown.cart_coupons.push({
                    name: name,
                    min_order_amount: minAmt,
                    discount_amount: discAmt,
                    meets_condition: salePrice >= minAmt,
                });
            }
        }

        // ── 적립 항목 (양수, 누적 베이스 적용) ──────────────
        // ★ 2026-05-15 정정 #3 — 사용자 명세: "구매적립 OR 선할인 둘 중 하나라도 활성이면 4%"
        //   기존 정규식이 wrap.text 안에서만 검색 → 라벨이 다른 영역에 있는 상품에서 못 잡음
        //   해결: pageText (body 전체) 에서 둘 중 하나라도 "(+X원)" or "-X원" 표시되면 활성
        const purchaseRewardInPage = /구매\\s*적립\\s*\\(\\+\\s*([\\d,]+)\\s*원\\)/.exec(pageText);
        const preDiscountInPage = /적립금\\s*선할인\\s*-\\s*([\\d,]+)\\s*원/.exec(pageText);
        if (purchaseRewardInPage || preDiscountInPage) {
            breakdown.purchase_reward_or_pre_discount_active = true;
            breakdown.grade_reward_active = true;
            if (purchaseRewardInPage) {
                breakdown.purchase_reward_displayed = parseInt(purchaseRewardInPage[1].replace(/,/g, ''));
            }
            if (preDiscountInPage) {
                breakdown.pre_discount_displayed = parseInt(preDiscountInPage[1].replace(/,/g, ''));
            }
        }
        // Legacy: wrap.text 만 매칭하던 옛 코드 (호환 유지)
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
        // ★ 2026-05-15 — "혜택 거의 없음" 케이스 (4210142) 감지:
        //   등급할인=불가 + 구매적립=불가 + 무신사머니="적용 안함" 인 상품은
        //   textContent 가 짧고 (185~280자) money_section 매칭이 안됨.
        //   Fail-safe 가 정상적으로 통과되도록 "비혜택 상품" 플래그 노출.
        breakdown.has_grade_disabled  = /등급\\s*할인\\s*불가/.test(text);
        breakdown.has_purchase_reward_disabled = /구매\\s*적립\\s*불가/.test(text);
        breakdown.has_money_apply_off = /(무신사\\s*머니[^적]{0,40})?적용\\s*안함/.test(text);
        breakdown.is_no_benefit_product = (
            breakdown.has_grade_disabled &&
            breakdown.has_purchase_reward_disabled
        );
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
             breakdown, couponName, options, expandResult };
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
                        return self._crawl_with_retry(page, product_url)
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
                    return self._crawl_with_retry(page, product_url)
                finally:
                    page.close()
            finally:
                context.close()
                browser.close()

    def _crawl_with_retry(self, page, product_url: str) -> CrawlResult:
        """ExpandFailedError 발생 시 page.reload + 1회 재시도. 그 후에도 실패면 raise."""
        try:
            return self._crawl(page, product_url)
        except ExpandFailedError as e:
            logger.warning("[무신사] 펼침 실패 — page.reload 후 1회 재시도: %s", str(e)[:200])
            try:
                page.reload(wait_until="domcontentloaded", timeout=30000)
                import time as _t
                _t.sleep(2)  # React 재초기화 시간
                return self._crawl(page, product_url)
            except ExpandFailedError as e2:
                logger.error("[무신사] 펼침 재시도 실패 — 최종 포기. %s", str(e2)[:200])
                raise

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

        # ★ 2026-05-15 정정 #5 — Python 측 page.inner_text 보강 추출.
        #   _EXTRACT_JS escape 문제 / 정규식 실패 케이스 우회.
        #   page.locator('body').inner_text() = 가장 신뢰성 있는 raw text.
        try:
            _body_text = page.locator('body').inner_text()
        except Exception:
            _body_text = ''
        _py_purchase = re.search(r'구매\s*적립\s*\(\+\s*([\d,]+)\s*원\)', _body_text)
        # 4723399 케이스: "적립금 선할인⏎5,540원⏎-5,540원" — 사이 텍스트 허용
        _py_predisc = re.search(r'적립금\s*선할인[\s\S]{0,40}?-\s*([\d,]+)\s*원', _body_text)
        # "선할인 불가" 는 false positive 차단
        if _py_predisc and re.search(r'적립금\s*선할인\s*불가', _body_text):
            _py_predisc = None
        _py_active = bool(_py_purchase or _py_predisc)
        _py_purchase_amt = int(_py_purchase.group(1).replace(',', '')) if _py_purchase else 0
        _py_predisc_amt = int(_py_predisc.group(1).replace(',', '')) if _py_predisc else 0
        # 장바구니쿠폰 — Python 측 raw text 매칭
        _py_cart_coupons = []
        for m in re.finditer(
            r'([가-힣A-Za-z][^/\n]{0,50}?장바구니\s*쿠폰)[\s\S]{0,200}?'
            r'([\d,]+)\s*(만|천)?\s*원?\s*이상\s*(?:구매)?[\s\S]{0,80}?'
            r'([\d,]+)\s*(만|천)?\s*원\s*(?:추가\s*)?할인',
            _body_text):
            name = re.sub(r'\s+', ' ', m.group(1)).strip()
            min_amt = int(m.group(2).replace(',', '')) * (10000 if m.group(3) == '만' else 1000 if m.group(3) == '천' else 1)
            disc_amt = int(m.group(4).replace(',', '')) * (10000 if m.group(5) == '만' else 1000 if m.group(5) == '천' else 1)
            if name and min_amt > 0 and disc_amt > 0:
                key = f"{name}|{min_amt}|{disc_amt}"
                if key not in [f"{c['name']}|{c['min_order_amount']}|{c['discount_amount']}" for c in _py_cart_coupons]:
                    _py_cart_coupons.append({
                        'name': name,
                        'min_order_amount': min_amt,
                        'discount_amount': disc_amt,
                    })
        # raw["breakdown"] 보강 (옵션 dict 박힐 때 활용)
        _bd_aug = raw.get("breakdown") or {}
        _bd_aug['py_purchase_or_predisc_active'] = _py_active
        _bd_aug['py_purchase_amt'] = _py_purchase_amt
        _bd_aug['py_predisc_amt'] = _py_predisc_amt
        _bd_aug['py_cart_coupons'] = _py_cart_coupons
        raw["breakdown"] = _bd_aug

        # ★ 2026-05-15 정정 #2 — 펼침 성공 진짜 검증 (PointDetailWrap 핵심 텍스트 존재)
        #   실패 시 page.reload() 후 1회 자동 재시도 (이 함수 외부에서 처리)
        expand_result = raw.get("expandResult") or {}
        if not expand_result.get("ok"):
            attempts = expand_result.get("attempts", 0)
            txt_len = expand_result.get("last_text_len", 0)
            raise ExpandFailedError(
                f"[무신사] 펼침 검증 실패 (시도 {attempts}회, 마지막 textContent {txt_len}자) "
                f"— PointDetailWrap 안에 '후기 적립' / '등급 적립' / '결제수단 적립' "
                f"중 하나도 노출 안 됨. URL: {product_url}"
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

        # ★ Fail-safe 검증 — 사용자 확정 정책 (2026-05-05 / 2026-05-15 정정):
        #   "상세 펼쳐서 정보 추출 못하면 차라리 크롤링 실패하는게 나음. 가격 잘못되면 엄청난 금전적 손실"
        #   ★ 2026-05-06 강화: 3중 검증 + Sanity check (LV별 한계율 + 매입가 비율)
        #   ★ 2026-05-15 정정: "혜택 거의 없음" 상품 (등급할인 불가 + 구매적립 불가) 은
        #     정상 케이스 → Fail-safe 의 textContent 길이·머니섹션 검증 우회
        wrap_found             = bool(bd.get("wrap_found"))
        text_length            = int(bd.get("text_length") or 0)
        point_detail_wrap_found = bool(bd.get("point_detail_wrap_found"))
        has_grade              = bool(bd.get("has_grade_section"))
        has_review             = bool(bd.get("has_review_section"))
        has_money              = bool(bd.get("has_money_section"))
        has_my_discount        = bool(bd.get("has_my_discount_section"))
        is_no_benefit          = bool(bd.get("is_no_benefit_product"))

        # 검증 1: wrap 발견
        if not wrap_found:
            raise RuntimeError(
                "[무신사] 가격 상세 영역(MaxBenefitPrice) 미발견 — "
                "페이지 구조 변경 가능성. 가격 산출 불가 (Fail-safe)"
            )
        # 검증 2: 펼침 직접 증거 (PointDetailWrap 존재)
        #   "혜택 거의 없음" 상품도 PointDetailWrap 은 노출되어야 정상 (후기 적립 항목 때문)
        if not point_detail_wrap_found:
            raise RuntimeError(
                "[무신사] PointDetailWrap 미발견 — 적립 상세 펼침 실패 (PointSummaryWrap 클릭 무효). "
                "가격 산출 불가 (Fail-safe)"
            )
        # 검증 3·4: 본 검증은 일반 혜택 상품에만 적용 (혜택 거의 없음 상품은 우회)
        if not is_no_benefit:
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
        else:
            # 혜택 거의 없음 상품 — 최소 후기 적립 섹션은 있어야 정상 (모든 상품 공통)
            if not has_review:
                raise RuntimeError(
                    "[무신사] '후기 적립' 섹션 미노출 — 펼침 불완전. 가격 산출 불가 (Fail-safe)"
                )
            logger.info("[무신사] 혜택 거의 없음 상품 감지 (등급할인+구매적립 모두 불가) — Fail-safe 완화 적용")
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

        # ════════════════════════════════════════════════
        # ★ 2026-05-15 — 사용자 명세 재확정 후 산식 정정:
        #   명세표 9항목 × 자동/크롤링 분리:
        #     · 등급할인 (LV별)  : 자동 ❌ / 크롤링 ✅ → 크롤러가 차감
        #     · 상품 쿠폰        : 자동 ❌ / 크롤링 ✅ → 크롤러가 차감 (정기쿠폰 제외)
        #     · 구매적립 OR 선할인: 자동 ❌ / 크롤링 ✅ → 크롤러가 차감 (활성 옵션만)
        #     · 등급 적립 (LV별) : 자동 ❌ / 크롤링 ✅ → 크롤러가 차감
        #     · 후기 적립        : 자동 ✅ (DB 500원) / 크롤링 ❌ → 크롤러 차감 안 함
        #     · 무신사머니 적립  : 자동 ✅ / 크롤링 ✅ → 활성=크롤러 / 비활성=현대카드 2.73% fallback
        #
        #   ★ 더블카운팅 회피:
        #     compute_breakdown 가 후기 500 + 현대카드 2.73% 자동 적용함.
        #     크롤러는 후기 500 을 차감하지 않음 (DB 가 처리).
        #     무신사머니 비활성 시 크롤러도 차감 안 함 → DB 현대카드 fallback 발동.
        # ════════════════════════════════════════════════
        # ── 단계 1: 표면가 - 등급할인(활성시) - 쿠폰
        base1 = max(sale_price - grade_discount - coupon, 0)

        # ── 단계 2: 등급 적립 (= 구매 적립, 활성 시) + 구매 추가 적립 (활성 시)
        grade_reward_amt = int(base1 * grade_reward_rate) if (grade_reward_active and grade_reward_rate > 0) else 0
        base2 = max(base1 - grade_reward_amt - purchase_extra_reward, 0)

        # ── 단계 3: 무신사머니 적립 — 활성 시 크롤러 차감 / 비활성 시 DB fallback (= 0)
        money_active = (money_reward_rate > 0)
        if money_active:
            money_reward_amt = int(base2 * money_reward_rate)
            payment_source = f"musinsa_money({money_reward_rate*100:.2f}%)"
        else:
            # ★ 무신사머니 비활성 → 크롤러는 0 차감 (compute_breakdown 의
            #   현대카드 2.73% fallback DB 항목이 자동 적용됨)
            money_reward_amt = 0
            payment_source = "deferred_to_db_card_fallback"

        # ── 후기 적립 — 크롤링 ❌ (자동 DB 처리). 정보용 노출만.
        review_reward_fixed = 0  # 크롤러 차감 0 (정책 변경)
        review_reward_active = has_review_reward  # 정보 보존

        tier1_confirmed = base1  # 호환성 (기존 코드가 참조)
        payment_benefit = money_reward_amt
        tier2_expected = max(base2 - money_reward_amt, 0)
        # base3 호환 — 호환성 유지 (구 옵션 dict 참조용)
        base3 = base2

        # ── Sanity check (매입가 비율) ─────────────────────
        #   매입가가 sale_price 의 50%~100% 범위 벗어나면 비정상 (잘못된 추출 가능성)
        #   ★ 2026-05-15 — "혜택 거의 없음" 상품은 ratio 95~100% 가 정상 → 임계 완화
        if sale_price > 0:
            ratio = tier2_expected / sale_price
            # ★ 2026-05-15 정정 #2 — 특별 혜택 40% 쿠폰까지 허용. 누적식 + 쿠폰
            #   합치면 매입가가 sale_price 의 25% 까지 떨어질 수 있음 (예: 6111473 헤지스).
            min_ratio = 0.20
            max_deduct_pct = 0.80
            if ratio < min_ratio:
                raise RuntimeError(
                    f"[무신사] 매입가 비율 비정상 ({ratio*100:.1f}% < {min_ratio*100:.0f}%) — "
                    f"tier2={tier2_expected:,}원 / sale={sale_price:,}원. 과차감 가능성 (Fail-safe)"
                )
            if ratio > 1.0:
                raise RuntimeError(
                    f"[무신사] 매입가가 sale_price 보다 큼 ({ratio*100:.1f}%) — 산식 오류 (Fail-safe)"
                )
            # 차감 합계 (sale - tier2) 가 sale 의 max_deduct_pct 초과면 의심 (과차감)
            total_deduction = sale_price - tier2_expected
            if total_deduction > sale_price * max_deduct_pct:
                raise RuntimeError(
                    f"[무신사] 차감 합계 과다 ({total_deduction:,}원, {total_deduction/sale_price*100:.1f}% of sale) "
                    f"— {max_deduct_pct*100:.0f}% 초과 비정상 (Fail-safe)"
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
                    "grade_discount_rate":   float(bd.get("grade_discount_rate") or 0),
                    "coupon":                coupon,
                    "pre_discount":          pre_disc,         # 정책 미사용 (구매적립 선택)
                    "card_discount":         card,             # 정책 미사용
                    "point_use_ignored":     point_use,        # 정책 미사용 (이중차감 방지)
                    # 적립 차감 항목 (누적식)
                    "review_reward_fixed":   review_reward_fixed,  # ★ 0 (DB 가 처리)
                    "review_reward_active":  review_reward_active, # 후기적립 항목 존재 여부 (정보용)
                    "grade_reward_active":   grade_reward_active,
                    "grade_reward_rate":     grade_reward_rate,
                    "grade_reward_amount":   grade_reward_amt,
                    "purchase_extra_reward": purchase_extra_reward,
                    "money_active":          money_active,       # 무신사머니 활성 여부
                    "money_reward":          money_reward_ui,
                    "money_reward_rate":     money_reward_rate,
                    "money_reward_amount":   money_reward_amt,
                    "payment_benefit":       payment_benefit,
                    "payment_source":        payment_source,
                    # 누적식 단계별 베이스 (디버깅)
                    "base1_after_grade":     base1,
                    "base2_after_grade_rwd": base2,
                    "base3_after_money":     base3,
                    "ui_max_benefit_price":  int(raw.get("benefitPriceFromUI") or 0),
                    # ★ 비혜택 상품 감지 플래그 (4210142 케이스)
                    "is_no_benefit_product": is_no_benefit,
                    "coupon_skipped_regular": bool(bd.get("coupon_skipped_regular")),
                    # ★ 2026-05-15 정정 #5 — Python 측 raw text 매칭 결과
                    "py_purchase_or_predisc_active": bool(bd.get("py_purchase_or_predisc_active")),
                    "py_purchase_amt": bd.get("py_purchase_amt") or 0,
                    "py_predisc_amt": bd.get("py_predisc_amt") or 0,
                    "py_cart_coupons": bd.get("py_cart_coupons") or [],
                },
            })

        if not options:
            # ★ 2026-05-15 정정 #5 — 단품 폴백에도 breakdown 박기 (이전엔 누락)
            options.append({
                "option_id": f"{product_id}||",
                "color_text": "", "size_text": "",
                "price": tier2_expected, "stock": SOURCING_AUTH.get("stock_cap", 10),
                "original_price": orig_price,
                "sale_price": tier1_confirmed,
                "benefit_price": tier2_expected,
                "breakdown": dict(bd),  # raw breakdown 그대로 (Python 측 보강 포함)
            })

        coupon_name = raw.get("couponName") or ""
        # 누적식 정책 요약 텍스트 (2026-05-15 — 후기/현대카드 fallback 은 DB compute_breakdown 가 처리)
        parts = []
        if grade_discount > 0:
            _gd_rate = float(bd.get("grade_discount_rate") or 0)
            parts.append(f"등급할인 -{grade_discount:,}원({_gd_rate*100:.1f}%)")
        if coupon > 0:
            parts.append(f"쿠폰 -{coupon:,}원")
        if grade_reward_active and grade_reward_rate > 0:
            parts.append(f"등급적립 {grade_reward_rate*100:.1f}%")
        if purchase_extra_reward > 0:
            parts.append(f"구매추가 +{purchase_extra_reward:,}원")
        if money_active:
            parts.append(f"무신사머니 {money_reward_rate*100:.1f}%")
        else:
            parts.append("머니 비활성→DB 현대카드 fallback")
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
