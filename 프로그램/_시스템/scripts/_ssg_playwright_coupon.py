"""Playwright 로 SSG 밀레 페치 → '상품쿠폰' 영역이 JS 렌더 후 노출되는지 확인.

별도 API XHR 도 캡처해서 API endpoint 파악.
"""
import sys, io, re, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from playwright.sync_api import sync_playwright

URL = 'https://www.ssg.com/item/itemView.ssg?itemId=1000807328520&siteNo=6009&salestrNo=1009'

xhr_logs = []

def on_response(resp):
    try:
        url = resp.url
        # 쿠폰 관련 API 만 캡처 (cpn / coupon / benefit)
        if any(k in url.lower() for k in ['cpn', 'coupon', 'benefit', 'promo']):
            xhr_logs.append({
                'url': url,
                'status': resp.status,
                'ct': resp.headers.get('content-type', ''),
            })
    except Exception:
        pass

with sync_playwright() as pw:
    # headless=False — SSG 봇 탐지 우회 (헤드리스는 차단)
    browser = pw.chromium.launch(headless=False, args=['--disable-blink-features=AutomationControlled'])
    context = browser.new_context(viewport={'width': 1280, 'height': 900},
                                  locale='ko-KR',
                                  user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
    # navigator.webdriver 제거 (탐지 우회)
    context.add_init_script("Object.defineProperty(navigator, 'webdriver', { get: () => undefined })")
    page = context.new_page()
    # 6.6KB 짜리 응답 본문 확인용
    print('[debug] 첫 응답 dump 후 진행')
    page.on('response', on_response)
    print(f'[fetch] {URL}')
    page.goto(URL, wait_until='networkidle', timeout=30000)
    page.wait_for_timeout(3000)
    # 스크롤로 lazy load 트리거
    page.evaluate("window.scrollTo(0, 800)")
    page.wait_for_timeout(2000)
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(2000)

    html = page.content()
    body = page.locator('body').inner_text()
    print(f'HTML 길이: {len(html):,}')
    print(f'body text 길이: {len(body):,}')
    if len(html) < 20000:
        print(f'[debug] 짧은 HTML 전체 dump:\n{html[:3000]}')
        print(f'[debug] body text 전체:\n{body}')

    # body inner_text 에서 "상품쿠폰" 검색
    for kw in ['상품쿠폰', '8%', '최대 2만원', '제휴할인', '다운로드', '백화점 8%', '백화점']:
        positions = [m.start() for m in re.finditer(re.escape(kw), body)]
        print(f'  body "{kw}": {len(positions)}회')
        for pos in positions[:2]:
            ctx = body[max(0,pos-50):pos+150].replace('\n', '⏎')
            print(f'    ...{ctx}...')

    # HTML 의 "상품쿠폰" 검색
    print()
    for kw in ['상품쿠폰', '제휴할인', 'cpn_txt', 'cdtl_cpn_wrap', 'cdtl_benefit_coupon']:
        positions = [m.start() for m in re.finditer(re.escape(kw), html)]
        print(f'  html "{kw}": {len(positions)}회')

    # XHR 로그
    print()
    print(f'XHR cpn/coupon/benefit/promo 요청: {len(xhr_logs)}건')
    for log in xhr_logs[:10]:
        print(f'  [{log["status"]}] {log["url"][:160]}')

    # DOM selector 시도
    print()
    for sel in ['dl.cdtl_cpn_wrap', '.cdtl_benefit_coupon', '[class*="coupon"]', '[class*="cpn"]', 'dt:has-text("상품쿠폰")']:
        try:
            count = page.locator(sel).count()
            print(f'  selector "{sel}": {count}개')
            if count > 0:
                txt = page.locator(sel).first.inner_text()[:300]
                print(f'    text: {txt}')
        except Exception as e:
            print(f'  selector "{sel}": ERROR {e}')

    page.close()
    context.close()
    browser.close()
