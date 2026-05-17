"""4653692 페이지 DOM 분석 — 펼침 가능한 요소 식별."""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from playwright.sync_api import sync_playwright
from lemouton.sourcing.auth import has_state, new_context_with_state

src = '무신사' if has_state('무신사', '영빈') else 'musinsa'

JS_DUMP = r"""
() => {
    const out = {classes: [], aria_btns: []};
    const re = /MaxBenefit|MyDiscount|MyBenefit|DiscountSummary|BenefitSummary|MaxDiscount|Accordion/;
    document.querySelectorAll('*').forEach(el => {
        const cls = (el.className && typeof el.className === 'string') ? el.className : '';
        if (re.test(cls)) {
            out.classes.push({cls: cls.split(' ')[0], txt_len: (el.textContent || '').length});
        }
    });
    document.querySelectorAll('[aria-expanded]').forEach(el => {
        out.aria_btns.push({
            expanded: el.getAttribute('aria-expanded'),
            text: ((el.textContent || '').slice(0, 50)).replace(/\n/g, ' '),
            cls: ((el.className && typeof el.className === 'string') ? el.className : '').slice(0, 80),
        });
    });
    return out;
}
"""

with sync_playwright() as pw:
    browser, context = new_context_with_state(pw, src, '영빈', browser=None)
    try:
        page = context.new_page()
        page.goto('https://www.musinsa.com/products/4653692', wait_until='domcontentloaded', timeout=30000)
        page.wait_for_timeout(3000)
        info = page.evaluate(JS_DUMP)
        seen = set()
        print('=== Benefit 관련 클래스 (unique) ===')
        for c in info['classes']:
            if c['cls'] in seen: continue
            seen.add(c['cls'])
            print(f"  {c['cls']:<60} txt_len={c['txt_len']}")
        print('\n=== aria-expanded 버튼 ===')
        for b in info['aria_btns']:
            print(f"  expanded={b['expanded']:<5} text='{b['text']}' cls='{b['cls']}'")
        page.close()
    finally:
        context.close()
        browser.close()
