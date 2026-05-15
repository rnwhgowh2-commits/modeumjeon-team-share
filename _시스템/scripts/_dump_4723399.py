"""4723399 page dump."""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from playwright.sync_api import sync_playwright
from lemouton.sourcing.auth import has_state, new_context_with_state

src = '무신사' if has_state('무신사', '영빈') else 'musinsa'

with sync_playwright() as pw:
    browser, context = new_context_with_state(pw, src, '영빈', browser=None)
    try:
        page = context.new_page()
        page.set_viewport_size({'width': 1280, 'height': 900})
        page.goto('https://www.musinsa.com/products/4723399', wait_until='networkidle', timeout=30000)
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
        print(f'body_text length: {len(body_text)}')
        for kw in ['나의 할인가', '구매 적립', '선할인', '핸드볼', '장바구니 쿠폰']:
            count = body_text.count(kw)
            print(f'  "{kw}" count: {count}')
            if count > 0:
                idx = body_text.find(kw)
                ctx = body_text[max(0,idx-30):idx+150].replace('\n', '⏎')
                print(f'    주변: ...{ctx}...')
        page.close()
    finally:
        context.close()
        browser.close()
