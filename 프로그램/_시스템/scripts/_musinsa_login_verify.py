"""무신사 로그인 검증 — profile_dir(rnwhgowh) 로 직접 페이지 페치 → 로그인 마커 + sale_price + dyn 확인."""
import sys, io, re, os, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from playwright.sync_api import sync_playwright

PROFILE_DIR = os.path.abspath('data/profiles/musinsa_rnwhgowh')
URL = 'https://www.musinsa.com/products/3728480'

print(f'  profile_dir: {PROFILE_DIR}')
print(f'  URL: {URL}')
print()

t0 = time.time()
with sync_playwright() as pw:
    context = None
    for ch in ("chrome", "msedge", None):
        try:
            kwargs = dict(user_data_dir=PROFILE_DIR, headless=True,
                          args=["--disable-blink-features=AutomationControlled"])
            if ch: kwargs["channel"] = ch
            context = pw.chromium.launch_persistent_context(**kwargs)
            print(f'  [채널] {ch or "bundled chromium"}')
            break
        except Exception as e:
            print(f'  [채널 실패] {ch}: {e}')
    if not context:
        sys.exit(1)
    page = context.pages[0] if context.pages else context.new_page()
    page.set_viewport_size({'width': 1280, 'height': 900})

    # 1. 메인 페이지로 먼저 가서 로그인 상태 확인
    print()
    print('  === Step 1: 메인 페이지 로그인 상태 확인 ===')
    page.goto('https://www.musinsa.com/', wait_until='domcontentloaded', timeout=30000)
    page.wait_for_timeout(3000)
    body = page.locator('body').inner_text()[:3000]
    has_logout = '로그아웃' in body
    has_login_btn = '로그인' in body and not has_logout
    has_mypage = '마이' in body or 'MY' in body
    nick_m = re.search(r'([가-힣A-Za-z0-9_]{2,20})\s*님', body)
    print(f'    "로그아웃" 노출: {has_logout}')
    print(f'    "로그인 버튼" 노출: {has_login_btn}')
    print(f'    "마이/MY" 노출: {has_mypage}')
    print(f'    "XXX님" 매치: {nick_m.group(1) if nick_m else "없음"}')

    # 2. 상품 페이지로 이동
    print()
    print('  === Step 2: 르무통 클래식 페이지 페치 ===')
    page.goto(URL, wait_until='domcontentloaded', timeout=30000)
    page.wait_for_timeout(3000)
    # lazy load + 나의 할인가 영역 펼침
    page.evaluate("window.scrollTo(0, 800)")
    page.wait_for_timeout(2000)
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(2000)
    page.evaluate("""
        document.querySelectorAll('[class*="MaxBenefitPriceTitle__CollapseButton"]').forEach(el => el.click());
        document.querySelectorAll('[class*="MaxBenefitPrice__PointSummaryWrap"]').forEach(el => el.click());
    """)
    page.wait_for_timeout(2000)

    body = page.locator('body').inner_text()
    print(f'    body 길이: {len(body):,}')

    # 가격 패턴 검색
    print()
    print('  === Step 3: 가격 + 혜택 영역 추출 ===')
    for kw in ['로그아웃', '나의 할인가', '나의할인가', '등급', '회원가', '구매적립', '선할인', '무신사머니']:
        cnt = body.count(kw)
        if cnt > 0:
            idx = body.find(kw)
            ctx = body[max(0,idx-50):idx+150].replace('\n', '⏎')
            print(f'    "{kw}" ({cnt}회): ...{ctx[:200]}...')

    # 가격 추출
    print()
    prices = re.findall(r'([0-9]{2,3},?[0-9]{3})\s*원', body)
    print(f'  발견된 원화 가격 (앞 15개): {prices[:15]}')

    # 등급/할인율 영역
    rate_m = re.findall(r'(\d+)\s*%', body[:5000])
    print(f'  % 등장 (앞 10개): {rate_m[:10]}')

    dt = time.time() - t0
    print()
    print(f'  ✅ 소요시간: {dt:.1f}s')

    page.close()
    context.close()
