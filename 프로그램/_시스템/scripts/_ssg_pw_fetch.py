"""SSG 3개 URL — launch_persistent_context (로그인 세션) 으로 페치 → 상품쿠폰 영역 확인."""
import sys, io, os, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from playwright.sync_api import sync_playwright

USER_DATA_DIR = os.path.abspath('data/profiles/ssg_ditodalal_pw')

URLS = [
    ('1000809938058 (나이키 리엑스)',
     'https://www.ssg.com/item/itemView.ssg?itemId=1000809938058&siteNo=6009&salestrNo=1004'),
    ('1000807328520 (밀레)',
     'https://www.ssg.com/item/itemView.ssg?itemId=1000807328520&siteNo=6009&salestrNo=1009'),
    ('1000644956258 (나이키 카고팬츠)',
     'https://www.ssg.com/item/itemView.ssg?itemId=1000644956258&siteNo=6009&salestrNo=1004'),
]

with sync_playwright() as pw:
    context = pw.chromium.launch_persistent_context(
        user_data_dir=USER_DATA_DIR,
        headless=False,  # 봇 탐지 우회
        args=['--disable-blink-features=AutomationControlled'],
        viewport={'width': 1280, 'height': 900},
        locale='ko-KR',
        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    )
    context.add_init_script(
        "Object.defineProperty(navigator, 'webdriver', { get: () => undefined })"
    )
    page = context.pages[0] if context.pages else context.new_page()

    for label, url in URLS:
        print('=' * 90)
        print(f'  {label}')
        print('=' * 90)
        try:
            page.goto(url, wait_until='networkidle', timeout=30000)
            page.wait_for_timeout(2000)
            # 상품쿠폰 영역 lazy load 트리거
            page.evaluate("window.scrollTo(0, 800)")
            page.wait_for_timeout(2000)
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(2000)

            html = page.content()
            body = page.locator('body').inner_text()
            print(f'  HTML 길이: {len(html):,}  body 길이: {len(body):,}')

            # 차단 페이지 체크
            if '연속적인 접근으로' in body or 'recaptcha' in html.lower():
                print(f'  ❌ reCAPTCHA 차단')
                continue

            # 상품쿠폰 키워드 검색
            for kw in ['상품쿠폰', '8%', '최대 2만원', '제휴할인', '다운로드 1일', '백화점']:
                positions = [m.start() for m in re.finditer(re.escape(kw), body)]
                if positions:
                    print(f'  body "{kw}": {len(positions)}회')
                    for pos in positions[:2]:
                        ctx = body[max(0,pos-60):pos+150].replace('\n', '⏎')
                        print(f'    ...{ctx}...')

            # DOM 셀렉터
            for sel in ['dl.cdtl_cpn_wrap', '.cdtl_benefit_coupon', 'dt:has-text("상품쿠폰")', '.cpn_txt']:
                try:
                    cnt = page.locator(sel).count()
                    if cnt > 0:
                        print(f'  selector "{sel}": {cnt}개')
                        txt = page.locator(sel).first.inner_text()[:300]
                        print(f'    text: {txt}')
                except Exception:
                    pass
        except Exception as e:
            import traceback
            print(f'  ❌ ERROR: {e}')
            traceback.print_exc()
        print()

    context.close()
