"""판매처 마켓 브라우저 — Playwright persistent_context 영구 쿠키 로그인.

Flask 에서 detached subprocess 로 호출하는 standalone 스크립트.
사용자가 창을 닫을 때까지 살아있고, 닫히면 쿠키가 user_data_dir 에 영구 저장됨.

사용 예:
    python open_marketplace_browser.py \\
        --source smartstore \\
        --account-key SMARTSTORE_MAIN \\
        --url https://sell.smartstore.naver.com/

송장전송기 패턴 — lemouton/auth/login_wizard.py:_login_persistent 와 동일 핵심.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# .env 자동 로드 — Flask 경유 spawn 시는 부모 env inherit 으로 충분하지만,
# Bash 직접 실행·CLI 디버깅 등 standalone 호출 시에도 동작하도록 명시 로드
try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv(ROOT / ".env", override=True)
except ImportError:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="[open_browser] %(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


def _try_login_fill(page, account_key: str) -> bool:
    """로그인 폼에 .env 의 ID/PW 자동 입력 + form submit. 성공 시 True."""
    env_prefix = (account_key or "").upper()
    login_id = (
        os.environ.get(f"{env_prefix}_LOGIN_ID")
        or os.environ.get("SMARTSTORE_LOGIN_ID")
        or ""
    )
    login_pw = (
        os.environ.get(f"{env_prefix}_LOGIN_PW")
        or os.environ.get("SMARTSTORE_LOGIN_PW")
        or ""
    )
    if not (login_id and login_pw):
        logger.info("[_try_login_fill] %s_LOGIN_ID/PW 미등록", env_prefix)
        return False
    logger.info("[_try_login_fill] creds 로드됨 — input 대기 중")

    try:
        # SPA 가 form 없이 div 로 감싸는 경우도 있어 form 한정자 제거
        try:
            page.wait_for_selector('input[type="password"]', state="visible", timeout=10000)
        except Exception as e:
            logger.warning("[_try_login_fill] password input 대기 timeout: %s", e)
            return False

        pw_input = page.locator('input[type="password"]:visible').first
        if pw_input.count() == 0:
            logger.warning("[_try_login_fill] password input 없음")
            return False
        id_input = None
        for sel in [
            'input[type="email"]:visible',
            'input[name="id"]:visible',
            'input[placeholder*="아이디"]:visible',
            'input[placeholder*="이메일"]:visible',
            'input[type="text"]:not([type="hidden"]):visible',
        ]:
            loc = page.locator(sel).first
            if loc.count() > 0:
                id_input = loc
                logger.info("[_try_login_fill] ID input found via %s", sel)
                break
        if id_input is None:
            logger.warning("[_try_login_fill] ID input 못 찾음")
            return False

        id_input.click(timeout=3000)
        id_input.fill(login_id, timeout=3000)
        pw_input.click(timeout=3000)
        pw_input.fill(login_pw, timeout=3000)
        page.wait_for_timeout(500)

        # submit 버튼 — 탭/링크가 아닌 form-submit 형태만 시도
        for sel in [
            'button[type="submit"]:visible',
            'input[type="submit"]:visible',
        ]:
            btn = page.locator(sel).first
            if btn.count() > 0:
                btn.click(timeout=3000)
                logger.info("[_try_login_fill] submit 클릭 (selector=%s)", sel)
                return True
        # fallback 1: PW Enter
        try:
            pw_input.press("Enter")
            logger.info("[_try_login_fill] Enter 키 fallback")
            return True
        except Exception:
            pass
        return False
    except Exception as e:
        logger.warning("[_try_login_fill] 실패: %s", e)
        return False


def _try_click_first_product(page) -> bool:
    """검색 결과 페이지에서 첫 상품 행의 [수정] 버튼 클릭. 성공 시 True.

    JS 직접 click 으로 visibility/actionable check 우회.
    """
    try:
        clicked = page.evaluate("""() => {
            // tbody 안에 있는 버튼들 중 [수정] 텍스트를 포함하는 첫 번째 클릭
            const all = document.querySelectorAll('tbody button, tbody a, table button, table a');
            for (const el of all) {
                const txt = (el.textContent || '').trim();
                if (txt === '수정' || txt === '편집' || txt === '상품 수정') {
                    el.click();
                    return 'tbody-' + el.tagName.toLowerCase();
                }
            }
            // fallback: 페이지 전체 [수정] 버튼 (header/nav 제외)
            const buttons = document.querySelectorAll('button, a');
            for (const el of buttons) {
                if ((el.textContent || '').trim() === '수정') {
                    if (el.closest('header, nav, [role="navigation"]')) continue;
                    el.click();
                    return 'global-' + el.tagName.toLowerCase();
                }
            }
            return false;
        }""")
        if clicked:
            return True
    except Exception:
        pass
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, help="smartstore | coupang | ...")
    ap.add_argument("--account-key", required=True, help="env_prefix or account_key")
    ap.add_argument("--url", required=True, help="이동할 URL")
    ap.add_argument("--auto-click-first-product", action="store_true",
                    help="페이지 로드 후 첫 상품 행 자동 클릭 → 편집 페이지 직행")
    args = ap.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.error("Playwright 미설치 — `pip install playwright && playwright install chromium`")
        return 1

    from lemouton.auth.profile_store import (
        default_store, STEALTH_ARGS, STEALTH_INIT_SCRIPT,
    )

    store = default_store()
    profile_path = store.profile_dir(args.source, args.account_key)
    store.kill_chrome_using(profile_path)
    store.cleanup_lock(profile_path)
    already_logged_in = store.has_profile(args.source, args.account_key)
    logger.info(
        "프로필: %s — %s",
        profile_path,
        "기존 쿠키 사용" if already_logged_in else "신규 (첫 로그인 필요)",
    )

    with sync_playwright() as p:
        context = None
        for attempt in range(1, 4):
            try:
                use_channel = "chrome" if attempt <= 2 else None
                context = p.chromium.launch_persistent_context(
                    user_data_dir=str(profile_path),
                    headless=False,
                    channel=use_channel,
                    args=list(STEALTH_ARGS),
                    ignore_default_args=["--enable-automation"],
                    locale="ko-KR",
                )
                break
            except Exception as e:
                logger.warning("부팅 실패 %d/3 (channel=%s): %s", attempt, use_channel, e)
                if attempt == 3:
                    logger.error("브라우저 부팅 실패 3회 — 종료")
                    return 2
                store.kill_chrome_using(profile_path)
                store.cleanup_lock(profile_path)
                time.sleep(2)

        try:
            context.add_init_script(STEALTH_INIT_SCRIPT)
        except Exception:
            pass

        page = context.pages[0] if context.pages else context.new_page()
        try:
            page.goto(args.url, wait_until="domcontentloaded", timeout=30000)
            logger.info("이동 완료: %s", args.url)
        except Exception as e:
            logger.warning("초기 이동 실패 (사용자가 직접 이동 가능): %s", e)

        # SmartStore 전용: 상태 머신 — about → 로그인폼 → 검색결과 단계별 자동화
        # 매 단계 후 Naver SPA 가 다음 페이지로 redirect 할 때까지 폴링
        if args.source == "coupang":
            # 쿠팡 윙: vendor-inventory/list?keyword={sellerProductId} → 첫 행 [수정] 자동 클릭
            for iteration in range(20):  # 최대 60초 폴링
                try:
                    page.wait_for_timeout(3000)
                    cur = (page.url or "")
                    logger.info("[coupang] poll#%d url=%s", iteration, cur[:80])
                    # 로그인 페이지 → 사용자 직접 처리 (영구 로그인 안 됐을 경우)
                    if "/login" in cur or "accounts.coupang" in cur:
                        logger.info("[coupang] 로그인 페이지 — 사용자 직접 처리 필요")
                        break
                    # 검색 결과 페이지 도달 → 첫 행 자동 클릭
                    if "vendor-inventory/list" in cur:
                        if args.auto_click_first_product:
                            page.wait_for_timeout(3000)  # 결과 렌더 대기
                            clicked = page.evaluate("""() => {
                                // 쿠팡 윙 상품관리 검색 결과 — 첫 행의 a 태그 또는 [수정] 버튼
                                // tbody 안에서 클릭 가능한 첫 요소 (수정/편집 텍스트 우선)
                                const tbody_targets = document.querySelectorAll('tbody a, tbody button');
                                for (const el of tbody_targets) {
                                    const txt = (el.textContent || '').trim();
                                    if (/수정|편집|상품수정/.test(txt)) { el.click(); return 'tbody-edit-' + el.tagName.toLowerCase(); }
                                }
                                // fallback: 상품명 링크 클릭 (첫 a[href])
                                const link = document.querySelector('tbody tr:first-child a[href]');
                                if (link) { link.click(); return 'tbody-link-first'; }
                                // ng/react SPA 클릭 영역 (행 자체)
                                const row = document.querySelector('tbody tr:first-child');
                                if (row) { row.click(); return 'tbody-row-first'; }
                                return false;
                            }""")
                            if clicked:
                                logger.info("[coupang] 검색 결과 첫 행 자동 클릭 → %s", clicked)
                                page.wait_for_timeout(2000)
                                break
                            else:
                                logger.info("[coupang] 첫 행 자동 클릭 실패 — 사용자 직접 처리")
                                break
                        else:
                            break
                except Exception as e:
                    logger.debug("[coupang] poll#%d 예외: %s", iteration, e)
                    break

        elif args.source == "smartstore":
            handled_about = False
            handled_login_form = False
            redirected_to_target = False
            for iteration in range(20):  # 최대 60초 폴링 (3초 × 20)
                try:
                    page.wait_for_timeout(3000)
                    cur = (page.url or "")
                    logger.info("[smartstore] poll#%d url=%s", iteration, cur[:80])

                    # 로그인 후 dashboard 도달 → JS 직접 click (visibility/actionable 우회)
                    if "/home/dashboard" in cur and not redirected_to_target:
                        # Step A: [상품관리] 카테고리 펼치기 — JS 강제 click
                        try:
                            expanded = page.evaluate("""() => {
                                const items = document.querySelectorAll('a[role="menuitem"], .seller-side-nav a');
                                for (const el of items) {
                                    if ((el.textContent || '').trim() === '상품관리') {
                                        el.click();
                                        return true;
                                    }
                                }
                                return false;
                            }""")
                            logger.info("[smartstore] [상품관리] JS click 시도 → %s", expanded)
                            if expanded:
                                page.wait_for_timeout(1800)
                        except Exception as e:
                            logger.warning("[smartstore] [상품관리] JS click 실패: %s", e)

                        # Step B: [상품 조회/수정] 자식 클릭 — JS 강제
                        clicked_menu = False
                        try:
                            clicked_menu = page.evaluate("""() => {
                                const a = document.querySelector('a[href="#/products/origin-list"]');
                                if (a) { a.click(); return true; }
                                // fallback: text 매칭
                                const all = document.querySelectorAll('a');
                                for (const el of all) {
                                    if ((el.textContent || '').trim() === '상품 조회/수정') {
                                        el.click();
                                        return true;
                                    }
                                }
                                return false;
                            }""")
                            logger.info("[smartstore] [상품 조회/수정] JS click → %s", clicked_menu)
                        except Exception as e:
                            logger.warning("[smartstore] [상품 조회/수정] JS click 실패: %s", e)
                        if clicked_menu:
                            redirected_to_target = True
                            page.wait_for_timeout(4000)  # origin-list 페이지 렌더 대기
                            # 검색: 라디오 [원상품번호] 선택 + input fill + [검색] 버튼 클릭 (DOM inspect 결과 기반)
                            try:
                                origin_keyword = args.url.split("searchKeyword=")[-1].split("&")[0]
                                if origin_keyword:
                                    # Step 1: searchKeywordType 라디오 중 정확히 "원상품번호" 라벨만 매칭
                                    radio_result = page.evaluate("""() => {
                                        const radios = document.querySelectorAll('input[type="radio"][name="searchKeywordType"]');
                                        let firstPass = null, secondPass = null;
                                        for (const r of radios) {
                                            let label = null;
                                            if (r.id) label = document.querySelector(`label[for="${r.id}"]`);
                                            if (!label) label = r.closest('label');
                                            if (!label) {
                                                let p = r.parentElement;
                                                while (p && !label && p !== document.body) {
                                                    label = p.querySelector('label');
                                                    p = p.parentElement;
                                                }
                                            }
                                            const txt = label ? (label.textContent || '').trim() : '';
                                            // 1순위: 정확히 "원상품번호" 단어 포함
                                            if (txt.includes('원상품번호')) { firstPass = {radio: r, txt: txt}; break; }
                                            // 2순위: "상품번호" 인데 "판매자" 안 포함
                                            if (txt.includes('상품번호') && !txt.includes('판매자')) {
                                                if (!secondPass) secondPass = {radio: r, txt: txt};
                                            }
                                        }
                                        const pick = firstPass || secondPass;
                                        if (pick) { pick.radio.click(); return 'radio-' + pick.txt.slice(0, 20); }
                                        return 'no-match';
                                    }""")
                                    logger.info("[smartstore] 검색 라디오 선택 → %s", radio_result)
                                    page.wait_for_timeout(500)

                                    # Step 2: 검색 input fill (정확한 placeholder)
                                    fill_result = page.evaluate("""([keyword]) => {
                                        const candidates = [
                                            'input[placeholder="입력 후 검색하세요."]',
                                            'input[placeholder*="검색하세요"]',
                                        ];
                                        for (const sel of candidates) {
                                            const inp = document.querySelector(sel);
                                            if (inp) {
                                                inp.focus();
                                                // ng-model 인식 위해 native value setter + input event
                                                const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                                                setter.call(inp, keyword);
                                                inp.dispatchEvent(new Event('input', {bubbles: true}));
                                                inp.dispatchEvent(new Event('change', {bubbles: true}));
                                                return sel;
                                            }
                                        }
                                        return false;
                                    }""", [origin_keyword])
                                    logger.info("[smartstore] 검색 input fill → %s", fill_result)
                                    page.wait_for_timeout(500)

                                    # Step 3: 검색 버튼 클릭
                                    search_clicked = page.evaluate("""() => {
                                        const candidates = [
                                            'button.btn-primary[type="submit"]',
                                            'a.btn-search',
                                            'button[type="submit"]',
                                        ];
                                        for (const sel of candidates) {
                                            const btn = document.querySelector(sel);
                                            if (btn) {
                                                const txt = (btn.textContent || '').trim();
                                                if (/검색|조회/.test(txt)) {
                                                    btn.click();
                                                    return sel;
                                                }
                                            }
                                        }
                                        return false;
                                    }""")
                                    logger.info("[smartstore] 검색 버튼 클릭 → %s", search_clicked)

                                    # Step 4: 검색 결과 렌더 대기 + 첫 행 [수정] 직접 클릭 (다음 poll 기다리지 않음)
                                    if search_clicked:
                                        page.wait_for_timeout(5000)  # filter 결과 렌더
                                        if args.auto_click_first_product:
                                            if _try_click_first_product(page):
                                                logger.info("[smartstore] 검색 후 첫 행 [수정] 클릭 — 편집 페이지 진입")
                                            else:
                                                logger.info("[smartstore] 첫 행 [수정] 클릭 실패 — 사용자 직접 처리")
                                        # 다음 iteration 에서 또 first_product 시도 안 하도록 redirected_to_target 유지
                            except Exception as e:
                                logger.warning("[smartstore] 검색 자동화 실패: %s", e)
                            # 직접 처리했으니 더 이상 polling 의 first_product 분기 안 들어가게
                            break
                        else:
                            logger.info("[smartstore] 사이드바 selector 미매칭")
                            redirected_to_target = True

                    # 상태 1: about 랜딩 → [로그인하기] 클릭
                    if not handled_about and "/home/about" in cur:
                        try:
                            btn = page.locator('a:has-text("로그인하기"), button:has-text("로그인하기")').first
                            if btn.count() > 0:
                                btn.click(timeout=3000)
                                handled_about = True
                                logger.info("[smartstore] about → [로그인하기] 자동 클릭")
                                continue
                        except Exception as e:
                            logger.warning("[smartstore] [로그인하기] 클릭 실패: %s", e)

                    # 상태 2: 로그인 폼 → ID/PW fill + submit
                    if not handled_login_form and (
                        "accounts.commerce.naver.com" in cur or "/login" in cur
                    ):
                        if _try_login_fill(page, args.account_key):
                            handled_login_form = True
                            logger.info("[smartstore] 로그인 폼 자동 처리 완료 — 디바이스 인증 대기")
                            continue
                        else:
                            logger.info("[smartstore] 로그인 폼 자동 fill 실패 — 사용자 직접 입력")
                            break  # 사용자가 처리

                    # 상태 3: 검색 결과 페이지 도달 → 첫 행 클릭
                    if "/products/list" in cur or "/products" in cur:
                        if args.auto_click_first_product:
                            if _try_click_first_product(page):
                                logger.info("[smartstore] 첫 상품 행 자동 클릭")
                                break
                            # 안 됐으면 다음 iteration 에서 재시도
                            continue
                        break

                    # 상태 4: 알 수 없는 페이지 — 사용자 처리
                    if iteration >= 5 and not handled_about and not handled_login_form:
                        # 5회 폴링 후에도 알려진 상태 아님 → 종료
                        logger.info("[smartstore] 알려진 페이지 패턴 미매칭 — 사용자 처리")
                        break
                except Exception as e:
                    logger.debug("[smartstore] poll#%d 예외 (무시): %s", iteration, e)
                    break

        # 사용자가 창을 닫을 때까지 대기 — context.pages 가 비면 종료
        try:
            while True:
                try:
                    pages = context.pages
                except Exception:
                    break
                if not pages:
                    break
                time.sleep(1)
        except KeyboardInterrupt:
            pass

        logger.info("창 종료 — 쿠키 자동 저장됨")
    return 0


if __name__ == "__main__":
    sys.exit(main())
