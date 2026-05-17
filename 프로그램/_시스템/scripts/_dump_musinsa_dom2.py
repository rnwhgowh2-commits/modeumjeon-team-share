"""4653692 페이지 DOM 분석 — 더 긴 wait + scroll lazy load."""
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
        page.goto('https://www.musinsa.com/products/4653692', wait_until='networkidle', timeout=30000)
        page.wait_for_timeout(3000)
        # 스크롤 시도 — lazy load 발동
        page.evaluate("window.scrollTo(0, 800)")
        page.wait_for_timeout(2000)
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(2000)
        # "나의 할인가" 영역 펼침 시도 (collapse button 클릭)
        page.evaluate("""
            document.querySelectorAll('[class*="MaxBenefitPriceTitle__CollapseButton"]').forEach(el => {
                try { el.click(); } catch(_) {}
            });
            document.querySelectorAll('[class*="MaxBenefitPrice__PointSummaryWrap"]').forEach(el => {
                try { el.click(); } catch(_) {}
            });
        """)
        page.wait_for_timeout(2000)
        # 페이지 textContent 에 "나의 할인가" 또는 "구매 적립" 또는 "선할인" 검색
        body_text = page.locator('body').inner_text()
        print(f'body_text length: {len(body_text)}')
        for kw in ['나의 할인가', '구매 적립', '선할인', '적립금 사용', '쿠폰 변경', '쿠폰변경']:
            count = body_text.count(kw)
            print(f'  "{kw}" count: {count}')
            if count > 0:
                # 첫 매치 주변 100자
                idx = body_text.find(kw)
                ctx = body_text[max(0,idx-30):idx+100].replace('\n', '⏎')
                print(f'    첫 매치 주변: ...{ctx}...')
        page.close()
    finally:
        context.close()
        browser.close()
