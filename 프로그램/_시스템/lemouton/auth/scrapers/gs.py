"""GS샵 + 폴더스타일 스크래퍼 — 송장전송기 sync 포팅."""
from __future__ import annotations

import random
import time
from .base import BaseScraper


class GSScraper(BaseScraper):
    site_key = "gs"
    site_name = "GS샵"
    # 2026-05 실측: /member/login.gs 는 405 Method Not Allowed → /cust/login/login.gs 사용
    login_url = "https://www.gsshop.com/cust/login/login.gs"

    naver_login_config = {
        "login_url": "https://www.gsshop.com/cust/login/login.gs",
        "naver_btn": 'a#naverLogin, a:has-text("네이버"), [class*="naver"]',
        "main_url": "https://www.gsshop.com",
        # ★ GS샵은 grm.gsretail.com 브리지 팝업 방식 — window.open 가로채기 시 콜백 stuck.
        #   진짜 팝업으로 처리해야 로그인 완료 (송장전송기 popup_mode=True 동일).
        "popup_mode": True,
    }

    def _do_login(self, account_id: str, account_pw: str) -> bool:
        try:
            self._page.goto(self.login_url, wait_until="domcontentloaded", timeout=15000)
            time.sleep(2)
            self.close_chatbots(self._page)

            # ID 3단계 방어
            self._page.evaluate("""
                () => {
                    const el = document.querySelector('#mbr_id');
                    if (el) { el.value=''; el.dispatchEvent(new Event('input',{bubbles:true})); el.dispatchEvent(new Event('change',{bubbles:true})); }
                }
            """)
            id_input = self._page.locator('#mbr_id')
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
                    const el = document.querySelector('#mbr_pw');
                    if (el) { el.value=''; el.dispatchEvent(new Event('input',{bubbles:true})); el.dispatchEvent(new Event('change',{bubbles:true})); }
                }
            """)
            pw_input = self._page.locator('#mbr_pw')
            try: pw_input.click(force=True, timeout=5000)
            except Exception: pw_input.focus()
            time.sleep(0.2)
            self._page.keyboard.press("Control+a"); self._page.keyboard.press("Backspace")
            for ch in account_pw:
                self._page.keyboard.type(ch, delay=random.choice([25,50,100,200]) + random.randint(0,50))
            time.sleep(0.4 + random.random() * 0.4)

            # 로그인 버튼
            try:
                self._page.locator('#btn_login').first.click(force=True, timeout=5000)
            except Exception:
                self._page.keyboard.press("Enter")

            time.sleep(2)

            def _success() -> bool:
                return "login" not in self._page.url.lower()

            if _success():
                self.log("info", f"[GS샵] ✅ 로그인 성공: {account_id}")
                return True

            ok = self.wait_for_login_or_user(success_check=_success, timeout=120, poll_interval=2.0)
            if ok:
                self.log("info", f"[GS샵] ✅ 로그인 성공: {account_id}")
                return True

            self.log("warning", f"[GS샵] 로그인 실패: {account_id} (URL: {self._page.url[:80]})")
            return False
        except Exception as e:
            self.log("error", f"[GS샵] 로그인 오류: {e}")
            return False


class FolderScraper(BaseScraper):
    site_key = "folder"
    site_name = "폴더스타일"
    login_url = "https://www.folderstyle.com/member/login.html"

    def _do_login(self, account_id: str, account_pw: str) -> bool:
        try:
            self._page.goto(self.login_url, wait_until="domcontentloaded", timeout=15000)
            time.sleep(2)
            self.close_chatbots(self._page)

            # ID 3단계 방어
            self._page.evaluate("""
                () => {
                    const el = document.querySelector('#member_id');
                    if (el) { el.value=''; el.dispatchEvent(new Event('input',{bubbles:true})); el.dispatchEvent(new Event('change',{bubbles:true})); }
                }
            """)
            id_input = self._page.locator('#member_id')
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
                    const el = document.querySelector('#member_passwd');
                    if (el) { el.value=''; el.dispatchEvent(new Event('input',{bubbles:true})); el.dispatchEvent(new Event('change',{bubbles:true})); }
                }
            """)
            pw_input = self._page.locator('#member_passwd')
            try: pw_input.click(force=True, timeout=5000)
            except Exception: pw_input.focus()
            time.sleep(0.2)
            self._page.keyboard.press("Control+a"); self._page.keyboard.press("Backspace")
            for ch in account_pw:
                self._page.keyboard.type(ch, delay=random.choice([25,50,100,200]) + random.randint(0,50))
            time.sleep(0.4 + random.random() * 0.4)

            # 로그인 버튼
            clicked = False
            for sel in ['.btnLogin', 'button[type="submit"]', 'button:has-text("로그인")']:
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
                self.log("info", f"[폴더스타일] ✅ 로그인 성공: {account_id}")
                return True

            ok = self.wait_for_login_or_user(success_check=_success, timeout=120, poll_interval=2.0)
            if ok:
                self.log("info", f"[폴더스타일] ✅ 로그인 성공: {account_id}")
                return True

            self.log("warning", f"[폴더스타일] 로그인 실패: {account_id} (URL: {self._page.url[:80]})")
            return False
        except Exception as e:
            self.log("error", f"[폴더스타일] 로그인 오류: {e}")
            return False
