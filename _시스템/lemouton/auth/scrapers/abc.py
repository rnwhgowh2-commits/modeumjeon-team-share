"""ABC마트 / GrandStage / ABC GS 스크래퍼 — 송장전송기 sync 포팅.

ABC마트와 그랜드스테이지는 동일한 a-rt.com 시스템 — URL만 다름.
"""
from __future__ import annotations

import random
import time
from .base import BaseScraper


class ABCMartScraper(BaseScraper):
    site_key = "abc"
    site_name = "ABC마트"
    login_url = "https://abcmart.a-rt.com/login"

    # 네이버 SSO — login_method == "naver" 시 사용 (송장전송기 1:1)
    naver_login_config = {
        "login_url": "https://abcmart.a-rt.com/login",
        "naver_btn": 'button.btn-sns[data-id="10000"], button:has-text("네이버"), a:has-text("네이버")',
        "main_url": "https://abcmart.a-rt.com",
    }

    def _do_login(self, account_id: str, account_pw: str) -> bool:
        try:
            self._page.goto(self.login_url, wait_until="domcontentloaded", timeout=15000)
            time.sleep(2)
            self.close_chatbots(self._page)

            # ID 3단계 방어
            self._page.evaluate("""
                () => {
                    document.querySelectorAll('input[name="loginId"], #loginId').forEach(el => {
                        el.value=''; el.dispatchEvent(new Event('input',{bubbles:true})); el.dispatchEvent(new Event('change',{bubbles:true}));
                    });
                }
            """)
            id_input = self._page.locator('input[name="loginId"], #loginId').first
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
                    document.querySelectorAll('input[name="loginPwd"], #loginPwd').forEach(el => {
                        el.value=''; el.dispatchEvent(new Event('input',{bubbles:true})); el.dispatchEvent(new Event('change',{bubbles:true}));
                    });
                }
            """)
            pw_input = self._page.locator('input[name="loginPwd"], #loginPwd').first
            try: pw_input.click(force=True, timeout=5000)
            except Exception: pw_input.focus()
            time.sleep(0.2)
            self._page.keyboard.press("Control+a"); self._page.keyboard.press("Backspace")
            for ch in account_pw:
                self._page.keyboard.type(ch, delay=random.choice([25,50,100,200]) + random.randint(0,50))
            time.sleep(0.4 + random.random() * 0.4)

            # 로그인 버튼
            clicked = False
            for sel in ['button[type="submit"]', '.btn-login', 'button:has-text("로그인")']:
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

            time.sleep(2)

            def _success() -> bool:
                return "login" not in self._page.url.lower()

            if _success():
                self.log("info", f"[{self.site_name}] ✅ 로그인 성공: {account_id}")
                return True

            ok = self.wait_for_login_or_user(success_check=_success, timeout=120, poll_interval=2.0)
            if ok:
                self.log("info", f"[{self.site_name}] ✅ 로그인 성공: {account_id}")
                return True

            self.log("warning", f"[{self.site_name}] 로그인 실패: {account_id} (URL: {self._page.url[:80]})")
            return False
        except Exception as e:
            self.log("error", f"[{self.site_name}] 로그인 오류: {e}")
            return False


class ABCMartGSScraper(ABCMartScraper):
    """ABC마트 GS — grandstage.a-rt.com 시스템 (송장전송기 abcGs 매핑 1:1)."""
    site_key = "abcGs"
    site_name = "ABC마트 GS"
    login_url = "https://grandstage.a-rt.com/login"

    naver_login_config = {
        "login_url": "https://grandstage.a-rt.com/login",
        "naver_btn": 'button.btn-sns[data-id="10000"], button:has-text("네이버"), a:has-text("네이버")',
        "main_url": "https://grandstage.a-rt.com",
    }


class GrandStageScraper(ABCMartScraper):
    """그랜드스테이지 — ABC마트와 동일 구조, URL 만 다름."""
    site_key = "grandstage"
    site_name = "그랜드스테이지"
    login_url = "https://grandstage.a-rt.com/login"

    naver_login_config = {
        "login_url": "https://grandstage.a-rt.com/login",
        "naver_btn": 'button.btn-sns[data-id="10000"], button:has-text("네이버"), a:has-text("네이버")',
        "main_url": "https://grandstage.a-rt.com",
    }
