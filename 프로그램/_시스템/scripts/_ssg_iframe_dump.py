"""SSG 10개 iframe 모두 dump + reload 후 재검사."""
import sys, io, os, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from playwright.sync_api import sync_playwright

USER_DATA_DIR = os.path.abspath('data/profiles/ssg_ditodalal_pw')
URL = 'https://www.ssg.com/item/itemView.ssg?itemId=1000807328520&siteNo=6009&salestrNo=1009'

with sync_playwright() as pw:
    context = pw.chromium.launch_persistent_context(
        user_data_dir=USER_DATA_DIR, headless=False,
        args=['--disable-blink-features=AutomationControlled'],
        viewport={'width': 1280, 'height': 900}, locale='ko-KR',
        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    )
    context.add_init_script("Object.defineProperty(navigator, 'webdriver', { get: () => undefined })")
    page = context.pages[0] if context.pages else context.new_page()
    page.goto(URL, wait_until='domcontentloaded', timeout=30000)
    page.wait_for_timeout(5000)
    # 풀 스크롤
    page.evaluate("""(async () => { const t=document.body.scrollHeight; for(let c=0;c<t;c+=300){window.scrollTo(0,c);await new Promise(r=>setTimeout(r,300));} window.scrollTo(0,0);})();""")
    page.wait_for_timeout(5000)
    # reload (실제 사용자 환경 흉내)
    page.reload(wait_until='domcontentloaded')
    page.wait_for_timeout(5000)
    page.evaluate("""(async () => { const t=document.body.scrollHeight; for(let c=0;c<t;c+=300){window.scrollTo(0,c);await new Promise(r=>setTimeout(r,300));} window.scrollTo(0,0);})();""")
    page.wait_for_timeout(5000)

    # 1. iframe 전부 dump
    print('=== iframe 10개 dump ===')
    for i, frame in enumerate(page.frames):
        try:
            ft = frame.locator('body').inner_text(timeout=2000)[:300]
            ft = re.sub(r'\s+', ' ', ft)
            url_short = frame.url[:80] if frame.url else ''
            print(f'  [{i}] {url_short}')
            print(f'      "{ft[:200]}"')
            # 상품쿠폰 검색
            if '쿠폰' in ft or '8%' in ft or '제휴' in ft:
                print(f'      ⭐ 쿠폰/8%/제휴 발견!')
        except Exception as e:
            print(f'  [{i}] ERROR {e}')

    # 2. 페이지 가격 영역 (이미 본 결과: 39,690원) 주변에 "혜택" 항목이 있는지
    print()
    print('=== "39,690원" 주변 200자 ===')
    body = page.locator('body').inner_text()
    for m in re.finditer(r'39,?690', body):
        pos = m.start()
        ctx = body[max(0,pos-50):pos+400].replace('\n', '⏎')
        print(f'  ...{ctx}...')
        break

    # 3. body 길이 + body 통째 끝부분
    print()
    print(f'=== body 끝 1000자 ===')
    print(body[-1000:].replace('\n', '⏎'))

    # 4. HTML 안에 "8%" / "상품쿠폰" 진짜 0건인지 다시 확인
    html = page.content()
    print()
    print(f'=== HTML "쿠폰" 검색 ===')
    for m in re.finditer(r'쿠폰', html):
        pos = m.start()
        ctx = html[max(0,pos-50):pos+150].replace('\n', '⏎')
        print(f'  ...{ctx[:250]}...')

    context.close()
