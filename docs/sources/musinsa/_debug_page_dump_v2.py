"""musinsa 4677240 진단 v2 — lazy-load BEFORE/AFTER 가격 element 차이 확인.

가설: _EXTRACT_JS 의 lazy-load 액션 (scroll + 체크박스 클릭 등) 후 페이지 상태가 변하면서
     CalculatedPrice 가 220,320 → 165,240 으로 바뀌는지 검증.
"""
from __future__ import annotations
import os, sys, json
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

SYSTEM = Path(r"C:\Users\seung\OneDrive\바탕 화면\모음전 관리 프로그램\프로그램\_시스템")
sys.path.insert(0, str(SYSTEM))
os.chdir(SYSTEM)

from playwright.sync_api import sync_playwright
from lemouton.sourcing.auth import new_context_with_state

URL = "https://www.musinsa.com/products/4677240"

DUMP_BEFORE_JS = r"""
() => {
    function parsePrice(text) {
        const m = (text || '').replace(/\s/g, '').match(/([0-9,]+)원/);
        return m ? parseInt(m[1].replace(/,/g, '')) : 0;
    }
    const origEl = document.querySelector('[class*="DiscountWrap"]');
    const saleEl = document.querySelector('[class*="CalculatedPrice"]');
    const curEl = document.querySelector('[class*="CurrentPrice"]');
    return {
        stage: 'BEFORE_LAZYLOAD',
        DiscountWrap_text: origEl ? origEl.innerText.slice(0, 100) : null,
        DiscountWrap_parsed: origEl ? parsePrice(origEl.innerText) : null,
        CalculatedPrice_text: saleEl ? saleEl.innerText.slice(0, 100) : null,
        CalculatedPrice_parsed: saleEl ? parsePrice(saleEl.innerText) : null,
        CurrentPrice_text: curEl ? curEl.innerText.slice(0, 100) : null,
        CurrentPrice_parsed: curEl ? parsePrice(curEl.innerText) : null,
        body_has_165240: (document.body.textContent || '').includes('165,240'),
        body_has_220320: (document.body.textContent || '').includes('220,320'),
        body_has_215320: (document.body.textContent || '').includes('215,320'),
    };
}
"""

LAZYLOAD_AND_DUMP_JS = r"""
async () => {
    function parsePrice(text) {
        const m = (text || '').replace(/\s/g, '').match(/([0-9,]+)원/);
        return m ? parseInt(m[1].replace(/,/g, '')) : 0;
    }
    // ★ musinsa_playwright._EXTRACT_JS 의 lazy-load 액션 그대로 복제
    document.querySelectorAll('[class*="Dimmed"], [class*="Modal"]').forEach(el => {
        try { el.remove(); } catch(_) {}
    });
    window.scrollTo(0, 800);
    await new Promise(r => setTimeout(r, 1500));
    window.scrollTo(0, 0);
    await new Promise(r => setTimeout(r, 1500));
    document.querySelectorAll('[class*="MaxBenefitPriceTitle__CollapseButton"]').forEach(el => {
        try { el.click(); } catch(_) {}
    });
    await new Promise(r => setTimeout(r, 800));
    // 적립금 사용 체크박스 자동 OFF
    let checkbox_unclicked = 0;
    document.querySelectorAll('input[type="checkbox"]').forEach(c => {
        const parent = c.closest('label, div, [class*="Wrapper"], [class*="Section"]');
        const lbl = (parent ? parent.textContent : (c.parentElement ? c.parentElement.textContent : '')) || '';
        if (/적립금\s*사용/.test(lbl) && c.checked) {
            try { c.click(); checkbox_unclicked++; } catch(_) {}
        }
    });
    await new Promise(r => setTimeout(r, 800));

    // 펼침 (15 retry)
    for (let i = 0; i < 5; i++) {
        document.querySelectorAll('[class*="MaxBenefitPrice__PointSummaryWrap"]').forEach(el => {
            try { el.click(); } catch(_) {}
        });
        await new Promise(r => setTimeout(r, 500));
    }

    // ★ AFTER 가격 덤프
    const origEl = document.querySelector('[class*="DiscountWrap"]');
    const saleEl = document.querySelector('[class*="CalculatedPrice"]');
    const curEl = document.querySelector('[class*="CurrentPrice"]');
    return {
        stage: 'AFTER_LAZYLOAD',
        checkbox_unclicked,
        DiscountWrap_text: origEl ? origEl.innerText.slice(0, 100) : null,
        DiscountWrap_parsed: origEl ? parsePrice(origEl.innerText) : null,
        CalculatedPrice_text: saleEl ? saleEl.innerText.slice(0, 100) : null,
        CalculatedPrice_parsed: saleEl ? parsePrice(saleEl.innerText) : null,
        CurrentPrice_text: curEl ? curEl.innerText.slice(0, 100) : null,
        CurrentPrice_parsed: curEl ? parsePrice(curEl.innerText) : null,
        body_has_165240: (document.body.textContent || '').includes('165,240'),
        body_has_220320: (document.body.textContent || '').includes('220,320'),
        body_has_215320: (document.body.textContent || '').includes('215,320'),
        // 165,240 주변 문맥
        ctx_165240: (() => {
            const body = document.body.textContent || '';
            const i = body.indexOf('165,240');
            return i < 0 ? null : body.slice(Math.max(0, i-100), i+200);
        })(),
        // PriceTotal 텍스트
        PriceTotal_text: (() => {
            const el = document.querySelector('[class*="PriceTotal"]');
            return el ? el.innerText.slice(0, 300) : null;
        })(),
    };
}
"""

print(f"[INFO] URL={URL}\n")

with sync_playwright() as pw:
    browser, context = new_context_with_state(pw, "musinsa", "영빈", browser=None)
    try:
        page = context.new_page()
        page.goto(URL, timeout=30000, wait_until="domcontentloaded")
        page.wait_for_selector('[class*="CalculatedPrice"], [class*="CurrentPrice"]', timeout=10000)

        before = page.evaluate(DUMP_BEFORE_JS)
        after = page.evaluate(LAZYLOAD_AND_DUMP_JS)

        page.close()
    finally:
        context.close()
        browser.close()

print("=" * 70)
print("[BEFORE lazy-load 액션]")
print("=" * 70)
print(json.dumps(before, ensure_ascii=False, indent=2))
print()
print("=" * 70)
print("[AFTER lazy-load 액션 (스크롤+CollapseButton+적립금사용 체크박스 OFF+펼침)]")
print("=" * 70)
print(json.dumps(after, ensure_ascii=False, indent=2))
