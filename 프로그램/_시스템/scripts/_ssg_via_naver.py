"""SSG 페치 — 네이버 referer 박아서 8% 상품쿠폰 발급 트리거 시도."""
import sys, io, os, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from playwright.sync_api import sync_playwright

USER_DATA_DIR = os.path.abspath('data/profiles/ssg_ditodalal_pw')

URL = 'https://www.ssg.com/item/itemView.ssg?itemId=1000807328520&siteNo=6009&salestrNo=1009'
NAVER_REFERER = 'https://search.shopping.naver.com/search/all?query=%EB%B0%80%EB%A0%88+%EC%B9%B4%EA%B3%A0%ED%8C%AC%EC%B8%A0'

with sync_playwright() as pw:
    context = pw.chromium.launch_persistent_context(
        user_data_dir=USER_DATA_DIR, headless=False,
        args=['--disable-blink-features=AutomationControlled'],
        viewport={'width': 1280, 'height': 900}, locale='ko-KR',
        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    )
    context.add_init_script("Object.defineProperty(navigator, 'webdriver', { get: () => undefined })")
    page = context.pages[0] if context.pages else context.new_page()

    # 시나리오 A: referer 직접 설정 후 SSG 접속
    print('=== 시나리오 A: page.goto(URL, referer=NAVER) ===')
    page.goto(URL, referer=NAVER_REFERER, wait_until='domcontentloaded', timeout=30000)
    page.wait_for_timeout(5000)
    # 풀 스크롤
    page.evaluate("""(async () => { const t=document.body.scrollHeight; for(let c=0;c<t;c+=300){window.scrollTo(0,c);await new Promise(r=>setTimeout(r,300));} window.scrollTo(0,0);})();""")
    page.wait_for_timeout(5000)

    body = page.locator('body').inner_text()
    print(f'  body 길이: {len(body):,}')
    for kw in ['상품쿠폰', '8%', '제휴할인', '다운로드', '최대 2만원', '백화점 8%']:
        positions = [m.start() for m in re.finditer(re.escape(kw), body)]
        if positions:
            print(f'  body "{kw}": {len(positions)}회')
            for pos in positions[:3]:
                ctx = body[max(0,pos-50):pos+200].replace('\n', '⏎')
                print(f'    ...{ctx[:250]}...')

    # 시나리오 B: 네이버 검색 페이지 방문 후 새 탭으로 SSG 열기 (자연스러운 referer)
    print()
    print('=== 시나리오 B: 네이버 검색 페이지 거쳐서 SSG 이동 ===')
    page.goto('https://www.naver.com', wait_until='domcontentloaded', timeout=30000)
    page.wait_for_timeout(2000)
    # 새 탭으로 SSG 열기 (직접 navigate)
    new_page = context.new_page()
    # naver 도메인 → SSG 이동 (referer 자동 설정)
    new_page.goto(URL, referer='https://search.shopping.naver.com/', wait_until='domcontentloaded', timeout=30000)
    new_page.wait_for_timeout(5000)
    new_page.evaluate("""(async () => { const t=document.body.scrollHeight; for(let c=0;c<t;c+=300){window.scrollTo(0,c);await new Promise(r=>setTimeout(r,300));} window.scrollTo(0,0);})();""")
    new_page.wait_for_timeout(5000)

    body2 = new_page.locator('body').inner_text()
    print(f'  body 길이: {len(body2):,}')
    for kw in ['상품쿠폰', '8%', '제휴할인', '다운로드', '최대 2만원', '백화점 8%']:
        positions = [m.start() for m in re.finditer(re.escape(kw), body2)]
        if positions:
            print(f'  body "{kw}": {len(positions)}회')
            for pos in positions[:3]:
                ctx = body2[max(0,pos-50):pos+200].replace('\n', '⏎')
                print(f'    ...{ctx[:250]}...')

    # 시나리오 C: 39,690원 주변 dump (혜택 영역 확인)
    print()
    print('=== "39,690" 주변 (시나리오 B) ===')
    for m in re.finditer(r'39,?690', body2):
        pos = m.start()
        ctx = body2[max(0,pos-30):pos+500].replace('\n', '⏎')
        print(f'  ...{ctx[:600]}...')
        break

    context.close()
