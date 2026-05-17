"""SSG 페치 v2 — raw HTML 전체 + iframe + 더 긴 lazy load wait."""
import sys, io, os, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from playwright.sync_api import sync_playwright

USER_DATA_DIR = os.path.abspath('data/profiles/ssg_ditodalal_pw')

URLS = [
    ('1000807328520 (밀레)',
     'https://www.ssg.com/item/itemView.ssg?itemId=1000807328520&siteNo=6009&salestrNo=1009'),
]

with sync_playwright() as pw:
    context = pw.chromium.launch_persistent_context(
        user_data_dir=USER_DATA_DIR,
        headless=False,
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
        page.goto(url, wait_until='domcontentloaded', timeout=30000)
        page.wait_for_timeout(3000)
        # 페이지 전체 스크롤 (lazy load 모두 트리거)
        page.evaluate("""
            (async () => {
                const total = document.body.scrollHeight;
                let cur = 0;
                while (cur < total) {
                    window.scrollTo(0, cur);
                    await new Promise(r => setTimeout(r, 500));
                    cur += 500;
                }
                window.scrollTo(0, 0);
            })();
        """)
        page.wait_for_timeout(5000)

        html = page.content()
        body = page.locator('body').inner_text()
        print(f'  HTML 길이: {len(html):,}  body 길이: {len(body):,}')

        # raw HTML 에서 "상품쿠폰" / "쿠폰" 검색
        for kw in ['상품쿠폰', 'cdtl_cpn_wrap', 'cdtl_benefit_coupon', 'cpn_txt',
                   '제휴할인', '다운로드 1일', '최대 2만원', '최대2만원']:
            html_count = len(list(re.finditer(re.escape(kw), html)))
            body_count = len(list(re.finditer(re.escape(kw), body)))
            print(f'  "{kw}": HTML {html_count}회 / body {body_count}회')

        # iframe 검사
        frames = page.frames
        print(f'  iframe 수: {len(frames)}')
        for i, frame in enumerate(frames):
            try:
                ftext = frame.locator('body').inner_text(timeout=2000)[:500]
                if '쿠폰' in ftext or '8%' in ftext:
                    print(f'    [{i}] {frame.url[:80]}')
                    print(f'      text: {ftext[:300]}')
            except Exception:
                pass

        # 모든 a/div with "쿠폰" or "8%" or "제휴" 텍스트 찾기
        # 그래디언트 배너 찾기 (보통 background 또는 특정 클래스)
        for sel in ['[class*="cpn"]', '[class*="coupon"]', '[class*="banner"]',
                    'a:has-text("쿠폰")', 'div:has-text("8% 상품쿠폰")',
                    '[class*="benefit"]', '[class*="promo"]']:
            try:
                cnt = page.locator(sel).count()
                if cnt > 0 and cnt < 50:
                    print(f'  selector "{sel}": {cnt}개')
                    for i in range(min(3, cnt)):
                        try:
                            t = page.locator(sel).nth(i).inner_text(timeout=1000)[:200]
                            if t.strip():
                                print(f'    [{i}] {t}')
                        except Exception:
                            pass
            except Exception:
                pass

        # 8% 쿠폰 배너의 가능한 위치 — img alt / data-react-unit-text
        print()
        print('  data-react-unit-text 안의 "쿠폰" / "8%" 검색:')
        m_react = list(re.finditer(r'data-react-unit-text=[\'"](\[[^\'"]*?쿠폰[^\'"]*?\])[\'"]', html))
        for m in m_react[:5]:
            print(f'    {m.group(1)[:300]}')

    context.close()
