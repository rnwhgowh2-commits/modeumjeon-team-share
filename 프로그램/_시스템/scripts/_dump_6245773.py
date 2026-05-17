"""6245773 — 구매적립 텍스트 분석 (사용자 사이트 1,430 vs 우리 1,330)."""
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
        page.goto('https://www.musinsa.com/products/6245773', wait_until='networkidle', timeout=30000)
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
        # "구매 적립" 모든 매치 발췌
        for m in re.finditer(r'구매\s*적립\s*\(\+\s*([\d,]+)\s*원\)', body_text):
            idx = m.start()
            ctx = body_text[max(0,idx-30):idx+80].replace('\n', '⏎')
            print(f'match: "{m.group()}" → ...{ctx}...')
        # 정가 표시 dump
        print('\n--- 정가 텍스트 ---')
        for m in re.finditer(r'65,?[78]00원', body_text):
            idx = m.start()
            ctx = body_text[max(0,idx-50):idx+50].replace('\n', '⏎')
            print(f'  "{m.group()}" → ...{ctx}...')
        page.close()
    finally:
        context.close()
        browser.close()
