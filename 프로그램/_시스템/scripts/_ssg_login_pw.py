"""SSG 로그인 1회 (launch_persistent_context — 영구 cookies 보관).

- user_data_dir: data/profiles/ssg_ditodalal_pw/ — 매 페치마다 재사용
- 로그인 감지: body 텍스트에 '로그아웃' 포함 (URL 패턴 무관, SSG 흐름 robust)
- timeout: 10분
- 보너스: storage_state 도 별도 저장 (cffi/playwright 호환)
"""
import sys, io, os, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from playwright.sync_api import sync_playwright

USER_DATA_DIR = os.path.abspath('data/profiles/ssg_ditodalal_pw')
STATE_PATH = os.path.abspath('data/auth/ssg_ditodalal.json')
os.makedirs(USER_DATA_DIR, exist_ok=True)
os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)

print(f'  user_data_dir: {USER_DATA_DIR}')
print(f'  storage_state: {STATE_PATH}')

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
    print('\n  브라우저 창에서 SSG 로그인을 완료해주세요 (최대 10분 대기)')
    print('  → 로그인 후 "로그아웃" 텍스트가 화면에 나타나면 자동 감지\n')
    page.goto('https://www.ssg.com/login.ssg', timeout=30000)

    detected = False
    for i in range(600):  # 10분
        try:
            body = page.locator('body').inner_text(timeout=2000)
            if '로그아웃' in body:
                detected = True
                print(f'  ✅ 로그인 감지 (대기: {i+1}초)')
                break
        except Exception:
            pass
        time.sleep(1)

    if detected:
        # 안정화 (cookies 저장 완료 보장)
        page.wait_for_timeout(3000)
        # storage_state 별도 저장 (호환용)
        context.storage_state(path=STATE_PATH)
        print(f'  ✅ storage_state 저장: {STATE_PATH}')
        print(f'  ✅ user_data_dir cookies 저장 (영구)')
    else:
        print('  ❌ 타임아웃 — 로그인 안 됨')

    context.close()  # persistent context — cookies 영구 보관
