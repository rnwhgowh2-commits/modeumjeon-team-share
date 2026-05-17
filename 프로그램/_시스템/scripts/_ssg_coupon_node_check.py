"""[class*=coupon] 노드 5개 상세 검사 + 페이지 전체 dl/dt 구조 dump."""
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
    page.wait_for_timeout(3000)
    page.evaluate("""(async () => { const t=document.body.scrollHeight; for(let c=0;c<t;c+=500){window.scrollTo(0,c);await new Promise(r=>setTimeout(r,400));} window.scrollTo(0,0);})();""")
    page.wait_for_timeout(5000)

    # 1. coupon 클래스 노드 detail
    print('=== [class*="coupon"] 5개 노드 detail ===')
    nodes = page.locator('[class*="coupon"]').all()
    for i, n in enumerate(nodes):
        try:
            cls = n.get_attribute('class')
            tag = n.evaluate('el => el.tagName')
            text = n.inner_text(timeout=1000) or ''
            html_snip = n.evaluate('el => el.outerHTML.substring(0, 300)')
            print(f'  [{i}] <{tag}> class="{cls}"')
            print(f'      text: "{text[:100]}"')
            print(f'      html: {html_snip[:200]}')
        except Exception as e:
            print(f'  [{i}] ERROR {e}')

    print()
    # 2. 페이지의 모든 dt 텍스트 검사 (사이트가 보여주는 "혜택" 영역)
    print('=== dt 텍스트 (혜택 영역 라벨 확인) ===')
    dts = page.locator('dt').all()
    seen = set()
    for d in dts:
        try:
            t = d.inner_text(timeout=500).strip()
            if t and t not in seen and len(t) < 30:
                seen.add(t)
                print(f'  - "{t}"')
        except Exception:
            pass

    # 3. 사이트 노출 가격 영역 dump (혜택 텍스트 전체)
    print()
    print('=== "혜택" 키워드 주변 dump (페이지 모두) ===')
    body = page.locator('body').inner_text()
    for kw in ['혜택', '쿠폰', '할인내역', '최적가']:
        for m in re.finditer(re.escape(kw), body):
            pos = m.start()
            ctx = body[max(0,pos-30):pos+150].replace('\n', '⏎')
            print(f'  ["{kw}"] ...{ctx}...')
            break  # 첫 매치만

    context.close()
