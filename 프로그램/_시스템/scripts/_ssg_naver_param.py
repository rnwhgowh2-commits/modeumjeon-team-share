"""SSG 페치 — ckwhere=ssg_naver + utm 파라미터 박아서 8% 상품쿠폰 발급 트리거."""
import sys, io, os, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from playwright.sync_api import sync_playwright

USER_DATA_DIR = os.path.abspath('data/profiles/ssg_ditodalal_pw')

# 사용자가 알려준 정확한 패턴
NAVER_PARAMS = (
    '&ckwhere=ssg_naver&appPopYn=n'
    '&utm_medium=PCS&utm_source=naver&utm_campaign=naver_pcs'
)

URLS = [
    ('1000809938058 (나이키 리엑스 — 사용자 제공 URL 그대로)',
     'https://www.ssg.com/item/itemView.ssg?itemId=1000809938058&siteNo=6009&salestrNo=1004&ckwhere=ssg_naver&appPopYn=n&utm_medium=PCS&utm_source=naver&utm_campaign=naver_pcs&NaPm=ct%3Dmp6ystew%7Cci%3D247d06d58249d160a120dbe636f2482217b50b41%7Ctr%3Dslsl%7Csn%3D218835%7Chk%3Dd87a5342016876d9a7fcf1f38909b08fe1821294'),
    ('1000807328520 (밀레 — 같은 파라미터 박음)',
     f'https://www.ssg.com/item/itemView.ssg?itemId=1000807328520&siteNo=6009&salestrNo=1009{NAVER_PARAMS}'),
    ('1000644956258 (나이키 카고팬츠 — 같은 파라미터 박음)',
     f'https://www.ssg.com/item/itemView.ssg?itemId=1000644956258&siteNo=6009&salestrNo=1004{NAVER_PARAMS}'),
]

NAVER_REFERER = 'https://search.shopping.naver.com/'

with sync_playwright() as pw:
    context = pw.chromium.launch_persistent_context(
        user_data_dir=USER_DATA_DIR, headless=False,
        args=['--disable-blink-features=AutomationControlled'],
        viewport={'width': 1280, 'height': 900}, locale='ko-KR',
        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    )
    context.add_init_script("Object.defineProperty(navigator, 'webdriver', { get: () => undefined })")
    page = context.pages[0] if context.pages else context.new_page()

    for label, url in URLS:
        print('=' * 90)
        print(f'  {label}')
        print('=' * 90)
        try:
            page.goto(url, referer=NAVER_REFERER, wait_until='domcontentloaded', timeout=30000)
            page.wait_for_timeout(5000)
            page.evaluate("""(async () => { const t=document.body.scrollHeight; for(let c=0;c<t;c+=300){window.scrollTo(0,c);await new Promise(r=>setTimeout(r,300));} window.scrollTo(0,0);})();""")
            page.wait_for_timeout(5000)

            body = page.locator('body').inner_text()
            print(f'  body 길이: {len(body):,}')
            if '연속적인 접근' in body:
                print('  ❌ reCAPTCHA 차단')
                continue

            # 핵심 키워드 검색
            found_any = False
            for kw in ['상품쿠폰', '제휴할인', '다운로드', '최대 2만원', '백화점 8%', '8% 상품']:
                positions = [m.start() for m in re.finditer(re.escape(kw), body)]
                if positions:
                    found_any = True
                    print(f'  ⭐ "{kw}": {len(positions)}회')
                    for pos in positions[:2]:
                        ctx = body[max(0,pos-50):pos+250].replace('\n', '⏎')
                        print(f'    ...{ctx[:300]}...')

            if not found_any:
                print('  (상품쿠폰 영역 미노출)')

            # 가격 주변 dump
            print()
            print('  === 가격 + 혜택 영역 dump ===')
            for m in re.finditer(r'(70,?805|39,?690|60,?605)', body):
                pos = m.start()
                ctx = body[max(0,pos-20):pos+500].replace('\n', '⏎')
                print(f'    ...{ctx[:600]}...')
                break
        except Exception as e:
            print(f'  ❌ ERROR: {e}')
        print()

    context.close()
