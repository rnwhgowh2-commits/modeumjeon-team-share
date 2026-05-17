"""SSG 페치 — 네이버 쇼핑 검색 → SSG link 클릭 흐름 흉내."""
import sys, io, os, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from playwright.sync_api import sync_playwright

USER_DATA_DIR = os.path.abspath('data/profiles/ssg_ditodalal_pw')

# 검색어: 밀레 카고팬츠 MVTUP423
NAVER_SHOP_SEARCH = 'https://search.shopping.naver.com/search/all?query=%EB%B0%80%EB%A0%88+%EC%B9%B4%EA%B3%A0%ED%8C%AC%EC%B8%A0+MVTUP423'
TARGET_ITEM_ID = '1000807328520'

with sync_playwright() as pw:
    context = pw.chromium.launch_persistent_context(
        user_data_dir=USER_DATA_DIR, headless=False,
        args=['--disable-blink-features=AutomationControlled'],
        viewport={'width': 1280, 'height': 900}, locale='ko-KR',
        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    )
    context.add_init_script("Object.defineProperty(navigator, 'webdriver', { get: () => undefined })")
    page = context.pages[0] if context.pages else context.new_page()

    # 1. 네이버 쇼핑 검색 페이지 방문
    print('=== Step 1: 네이버 쇼핑 검색 ===')
    print(f'  URL: {NAVER_SHOP_SEARCH}')
    page.goto(NAVER_SHOP_SEARCH, wait_until='domcontentloaded', timeout=30000)
    page.wait_for_timeout(5000)
    # 검색 결과 lazy load
    page.evaluate("window.scrollTo(0, 1500)")
    page.wait_for_timeout(3000)
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(2000)

    # 2. SSG.com 으로 가는 link 찾기
    print()
    print('=== Step 2: SSG.com / 1000807328520 link 찾기 ===')
    # ssg.com 도메인 + itemId=1000807328520 포함 link
    all_links = page.evaluate("""() => {
        const links = Array.from(document.querySelectorAll('a[href]'));
        return links
            .map(a => a.href)
            .filter(h => h.includes('ssg.com') || h.includes('1000807328520'));
    }""")
    print(f'  찾은 link 수: {len(all_links)}')
    for h in all_links[:10]:
        print(f'    {h[:200]}')

    # 첫 ssg link 클릭 (또는 직접 nav)
    target_link = None
    for h in all_links:
        if 'ssg.com' in h.lower() and '1000807328520' in h:
            target_link = h
            break
    if not target_link and all_links:
        # 1000807328520 만 포함하는 링크 (네이버 redirect URL)
        target_link = all_links[0]

    if target_link:
        print()
        print(f'=== Step 3: link 클릭 (직접 navigate) ===')
        print(f'  → {target_link[:200]}')
        # link 가 네이버 redirect URL 일 수 있음 (cr.shopping.naver.com → SSG)
        page.goto(target_link, wait_until='domcontentloaded', timeout=60000)
        page.wait_for_timeout(5000)
        # SSG 도착 후 url 확인
        print(f'  최종 도착 URL: {page.url[:200]}')
        # 풀 스크롤
        page.evaluate("""(async () => { const t=document.body.scrollHeight; for(let c=0;c<t;c+=300){window.scrollTo(0,c);await new Promise(r=>setTimeout(r,300));} window.scrollTo(0,0);})();""")
        page.wait_for_timeout(5000)

        body = page.locator('body').inner_text()
        print()
        print(f'  body 길이: {len(body):,}')
        # 차단 체크
        if '연속적인 접근' in body:
            print('  ❌ reCAPTCHA 차단')
        else:
            for kw in ['상품쿠폰', '제휴할인', '다운로드', '최대 2만원', '백화점 8%', '8% 상품']:
                positions = [m.start() for m in re.finditer(re.escape(kw), body)]
                if positions:
                    print(f'  ⭐ body "{kw}": {len(positions)}회')
                    for pos in positions[:3]:
                        ctx = body[max(0,pos-50):pos+250].replace('\n', '⏎')
                        print(f'    ...{ctx[:300]}...')
                else:
                    print(f'  body "{kw}": 0회')
            # 39,690 주변
            print()
            print('  === "39,690" 주변 dump ===')
            for m in re.finditer(r'39,?690', body):
                pos = m.start()
                ctx = body[max(0,pos-30):pos+500].replace('\n', '⏎')
                print(f'    ...{ctx[:600]}...')
                break
    else:
        print('  ❌ SSG link 못 찾음 — 네이버 검색 결과에 SSG.com 매물 없을 수 있음')

    context.close()
