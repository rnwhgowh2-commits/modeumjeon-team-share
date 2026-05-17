"""쿠팡 Wing (셀러 포털) 자동 로그인 스크래퍼.

URL: https://wing.coupang.com/
로그인 방식: ID/PW 직접 입력
2단계 인증: 발생 시 wait_for_login_or_user 로 사용자 직접 처리
"""
from __future__ import annotations

import random
import time
from .base import BaseScraper


class CoupangWingScraper(BaseScraper):
    site_key = "coupang_wing"
    site_name = "쿠팡 Wing"
    login_url = "https://wing.coupang.com/"

    def _do_login(self, account_id: str, account_pw: str) -> bool:
        try:
            self._page.goto(self.login_url, wait_until="domcontentloaded", timeout=15000)
            time.sleep(3)
            self.close_chatbots(self._page)

            # 이미 로그인 상태 (URL 에 login 없음) 체크
            cur = self._page.url.lower()
            if "login" not in cur and "wing.coupang.com" in cur and "/wmd/login" not in cur:
                self.log("info", f"[쿠팡 Wing] ✅ 이미 로그인됨: {account_id}")
                return True

            # ID 3단계 방어
            self._page.evaluate("""
                () => {
                    const el = document.querySelector('input[name="username"], #username, input[type="email"]');
                    if (el) { el.value=''; el.dispatchEvent(new Event('input',{bubbles:true})); el.dispatchEvent(new Event('change',{bubbles:true})); }
                }
            """)
            id_input = self._page.locator('input[name="username"], #username, input[type="email"]').first
            try: id_input.click(force=True, timeout=5000)
            except Exception: id_input.focus()
            time.sleep(0.2)
            self._page.keyboard.press("Control+a"); self._page.keyboard.press("Backspace")
            for ch in account_id:
                self._page.keyboard.type(ch, delay=random.choice([30,60,120,250]) + random.randint(0,50))
            time.sleep(0.3 + random.random() * 0.3)

            # PW 3단계 방어
            self._page.evaluate("""
                () => {
                    const el = document.querySelector('input[name="password"], #password, input[type="password"]');
                    if (el) { el.value=''; el.dispatchEvent(new Event('input',{bubbles:true})); el.dispatchEvent(new Event('change',{bubbles:true})); }
                }
            """)
            pw_input = self._page.locator('input[name="password"], #password, input[type="password"]').first
            try: pw_input.click(force=True, timeout=5000)
            except Exception: pw_input.focus()
            time.sleep(0.2)
            self._page.keyboard.press("Control+a"); self._page.keyboard.press("Backspace")
            for ch in account_pw:
                self._page.keyboard.type(ch, delay=random.choice([25,50,100,200]) + random.randint(0,50))
            time.sleep(0.4 + random.random() * 0.4)

            # 로그인 버튼
            clicked = False
            for sel in ['button[type="submit"]', 'button:has-text("로그인")', '.btn-login']:
                try:
                    btn = self._page.locator(sel).first
                    if btn.count() > 0:
                        btn.click(force=True, timeout=5000)
                        clicked = True
                        break
                except Exception:
                    continue
            if not clicked:
                self._page.keyboard.press("Enter")

            time.sleep(3)

            def _success() -> bool:
                u = self._page.url.lower()
                # Wing 메인으로 갔거나 /wmd/login 이 아니면 성공
                return "wing.coupang.com" in u and "/wmd/login" not in u and "/login" not in u

            if _success():
                self.log("info", f"[쿠팡 Wing] ✅ 로그인 성공: {account_id}")
                return True

            # 2단계 인증·캡차 등장 시 사용자 입력 대기
            ok = self.wait_for_login_or_user(success_check=_success, timeout=180, poll_interval=2.0)
            if ok:
                self.log("info", f"[쿠팡 Wing] ✅ 로그인 성공: {account_id}")
                return True

            self.log("warning", f"[쿠팡 Wing] 로그인 실패: {account_id} (URL: {self._page.url[:80]})")
            return False
        except Exception as e:
            self.log("error", f"[쿠팡 Wing] 로그인 오류: {e}")
            return False
