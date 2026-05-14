"""무신사 스크래퍼 — 송장전송기 sourcing_scrapers.py:MusinsaScraper 의 sync 포팅.

2026-03 기준 셀렉터: placeholder 기반 (name/id 없음)
  - 통합계정: ``input[placeholder*="통합계정"]``
  - 비밀번호: ``input[placeholder*="비밀번호"]``
"""
from __future__ import annotations

import time
from .base import BaseScraper


class MusinsaScraper(BaseScraper):
    site_key = "musinsa"
    site_name = "무신사"
    login_url = "https://www.musinsa.com/auth/login"

    # ★ 무신사 로그인 토큰 — 발급 시 expires_utc=0 (session) 으로 발급되어 Chrome 종료시 사라짐.
    #   마법사 종료 직전 BaseScraper._persist_session_cookies() 가 SQLite UPDATE 로 30일 영구 변환.
    #   ※ B 방안 (자동로그인 체크박스) 가 작동하면 무신사가 영구 토큰 발급 → 본 변환 불필요.
    #     실패 대비 안전망.
    SESSION_TO_PERSISTENT_COOKIES = ["app_atk", "app_rtk", "mss_last_login"]

    def _do_login(self, account_id: str, account_pw: str) -> bool:
        """무신사 통합 로그인 (member.one.musinsa.com).

        송장전송기 sourcing_scrapers.py:1063 와 100% 동일 로직.
        """
        try:
            self._page.goto(self.login_url, wait_until="domcontentloaded", timeout=15000)
            time.sleep(3)

            cur_url = self._page.url
            self.log("info", f"[무신사] 로그인 페이지: {cur_url[:60]}")

            # 이미 로그인된 상태면 성공
            if "login" not in cur_url and "member.one" not in cur_url and "auth" not in cur_url:
                self.close_chatbots(self._page)
                return True

            # 챗봇 제거
            self.close_chatbots(self._page)

            # ID 입력 — 3단계 방어 (자동완성·잔존 값 누적 방지)
            self._page.wait_for_selector('input[placeholder*="통합계정"]', timeout=10000)
            self._page.evaluate("""
                () => {
                    document.querySelectorAll('input[placeholder*="통합계정"], input[placeholder*="이메일"]').forEach(el => {
                        el.value = '';
                        el.dispatchEvent(new Event('input', {bubbles:true}));
                        el.dispatchEvent(new Event('change', {bubbles:true}));
                    });
                }
            """)
            id_input = self._page.locator('input[placeholder*="통합계정"]')
            try:
                id_input.click(force=True, timeout=5000)
            except Exception:
                id_input.focus()
            time.sleep(0.2)
            self._page.keyboard.press("Control+a")
            self._page.keyboard.press("Backspace")
            id_input.press_sequentially(account_id, delay=50)
            time.sleep(0.3)

            # PW 입력 — 동일 3단계 방어
            self._page.evaluate("""
                () => {
                    document.querySelectorAll('input[placeholder*="비밀번호"]').forEach(el => {
                        el.value = '';
                        el.dispatchEvent(new Event('input', {bubbles:true}));
                        el.dispatchEvent(new Event('change', {bubbles:true}));
                    });
                }
            """)
            pw_input = self._page.locator('input[placeholder*="비밀번호"]')
            try:
                pw_input.click(force=True, timeout=5000)
            except Exception:
                pw_input.focus()
            time.sleep(0.2)
            self._page.keyboard.press("Control+a")
            self._page.keyboard.press("Backspace")
            pw_input.press_sequentially(account_pw, delay=30)
            time.sleep(0.5)

            # 자동 로그인 체크 — DOM 분석 결과 (2026-05):
            #   <input type="checkbox" name="autologin" class="blind ..." />
            #   class="blind" = 시각 숨김 (bounding rect 0px) → Playwright 기본 .check() 는 actionability 실패
            #   → JS 직접 evaluate 로 checked=true + change 이벤트 dispatch (React state 동기화)
            try:
                cb = self._page.locator('input[name="autologin"]').first
                if cb.count() > 0:
                    is_checked_now = cb.evaluate("el => el.checked")
                    if not is_checked_now:
                        cb.evaluate("""
                            el => {
                                el.checked = true;
                                el.dispatchEvent(new Event('change', {bubbles: true}));
                                el.dispatchEvent(new Event('input', {bubbles: true}));
                            }
                        """)
                        # 검증 — React state 가 실제로 동기화됐는지
                        verified = cb.evaluate("el => el.checked")
                        if verified:
                            self.log("info", "[무신사] ✅ 자동로그인 체크박스 활성화 (영구 토큰 발급)")
                        else:
                            self.log("warning", "[무신사] ⚠ 자동로그인 체크 실패 — session 쿠키만 발급됨 (안전망 변환 작동)")
            except Exception as e:
                self.log("debug", f"[무신사] 자동로그인 시도 예외: {e}")

            # 로그인 버튼 자동 클릭 — 명확한 셀렉터 + force + 폴백
            self.log("info", "[무신사] 로그인 버튼 자동 클릭 시도")
            clicked = False
            for sel in [
                'button.login-v2-button__item--black',  # 검은색 로그인 버튼 (가장 명확)
                'button.login-v2-button__item[type="submit"]',
                'button[type="submit"]:has-text("로그인")',
                'button[type="submit"]',
            ]:
                try:
                    btn = self._page.locator(sel).first
                    if btn.count() > 0:
                        btn.click(force=True, timeout=5000)
                        self.log("info", f"[무신사] 클릭 성공 (셀렉터: {sel})")
                        clicked = True
                        break
                except Exception as e:
                    self.log("debug", f"[무신사] 셀렉터 {sel} 실패: {e}")
                    continue

            if not clicked:
                # 마지막 수단: Enter 키
                try:
                    self._page.keyboard.press("Enter")
                    self.log("info", "[무신사] Enter 키로 제출")
                except Exception:
                    self.log("warning", "[무신사] 자동 클릭 실패 — 사용자가 직접 누르세요")

            # 초기 응답 시간 (서버 응답 대기)
            time.sleep(3)

            # 성공 판정 함수 — URL 이 로그인 페이지 벗어났는지
            def _success() -> bool:
                cur = self._page.url
                return ("login" not in cur
                        and "member.one" not in cur
                        and "auth" not in cur)

            if _success():
                self.close_chatbots(self._page)
                self.log("info", f"[무신사] ✅ 로그인 성공: {account_id}")
                return True

            # reCAPTCHA / 봇 검사 / 2단계 인증 — 사용자 개입 2분 대기
            ok = self.wait_for_login_or_user(
                success_check=_success,
                timeout=120,
                poll_interval=2.0,
            )
            if ok:
                self.close_chatbots(self._page)
                self.log("info", f"[무신사] ✅ 로그인 성공: {account_id}")
                return True

            # 에러 메시지
            error_msg = ""
            try:
                err_el = self._page.query_selector('.login-v2-member__error, [class*="error"]')
                if err_el:
                    error_msg = err_el.inner_text().strip()
            except Exception:
                pass
            self.log("warning", f"[무신사] 로그인 실패: {account_id} {error_msg}")
            return False
        except Exception as e:
            self.log("error", f"[무신사] 로그인 오류: {e}")
            return False
