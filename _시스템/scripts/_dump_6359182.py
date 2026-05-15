"""6359182 — 상품쿠폰 false positive 분석."""
import sys, io, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from playwright.sync_api import sync_playwright
from lemouton.sourcing.auth import has_state, new_context_with_state

src = '무신사' if has_state('무신사', '영빈') else 'musinsa'
with sync_playwright() as pw:
    browser, context = new_context_with_state(pw, src, '영빈', browser=None)
    try:
        page = context.new_page()
        page.set_viewport_size({'width': 1280, 'height': 900})
        page.goto('https://www.musinsa.com/products/6359182', wait_until='networkidle', timeout=30000)
        page.wait_for_timeout(3000)
        page.evaluate("window.scrollTo(0, 800)")
        page.wait_for_timeout(2000)
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(2000)
        page.evaluate("""
            document.querySelectorAll('[class*="MaxBenefitPriceTitle__CollapseButton"]').forEach(el => el.click());
            document.querySelectorAll('[class*="MaxBenefitPrice__PointSummaryWrap"]').forEach(el => el.click());
        """)
        page.wait_for_timeout(2000)
        body_text = page.locator('body').inner_text()
        # "상품 쿠폰" 영역 dump
        idx = body_text.find('상품 쿠폰')
        print(f'상품 쿠폰 idx={idx}')
        if idx >= 0:
            ctx = body_text[idx:idx+200].replace('\n', '⏎')
            print(f'  주변 200자: ...{ctx}...')
        # 우리 정규식 매칭 시뮬레이션
        m = re.search(r'상품\s*쿠폰([\s\S]*?)(?=적립금\s*사용|구매\s*적립|제휴카드)', body_text)
        if m:
            section = m.group(1)
            print(f'\n매칭된 section: "{section[:200]}"')
            amt = re.search(r'-([\d,]+)\s*원', section)
            if amt:
                print(f'  -X원 매칭: {amt.group()}')
        page.close()
    finally:
        context.close()
        browser.close()
