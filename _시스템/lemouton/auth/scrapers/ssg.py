"""SSG 스크래퍼 — 송장전송기 sourcing_scrapers.py:SSGScraper sync 포팅."""
from __future__ import annotations

import random
import time
from .base import BaseScraper


class SSGScraper(BaseScraper):
    site_key = "ssg"
    site_name = "SSG"
    # 2026-05 실측: login.ssg.com 서브도메인 폐기 → member.ssg.com 으로 이동
    login_url = "https://member.ssg.com/member/login.ssg"

    naver_login_config = {
        "login_url": "https://member.ssg.com/member/login.ssg",
        # 2026-05 실측: <a onclick="snsLoginByType('naver')"> 가 정확한 OAuth 트리거.
        # 기존 [class*="naver"] 는 자식 span (cmem_ico_naver) 만 잡아 onclick 발화 안 됨.
        "naver_btn": 'a[onclick*="snsLoginByType(\'naver\')"], a:has(.cmem_ico_naver), a:has-text("네이버 로그인")',
        "main_url": "https://www.ssg.com",
    }

    def _do_login(self, account_id: str, account_pw: str) -> bool:
        try:
            self._page.goto(self.login_url, wait_until="domcontentloaded", timeout=15000)
            time.sleep(2)
            self.close_chatbots(self._page)

            # ID 3단계 방어
            self._page.evaluate("""
                () => {
                    const el = document.querySelector('#id');
                    if (el) { el.value=''; el.dispatchEvent(new Event('input',{bubbles:true})); el.dispatchEvent(new Event('change',{bubbles:true})); }
                }
            """)
            id_input = self._page.locator('#id')
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
                    const el = document.querySelector('#pw');
                    if (el) { el.value=''; el.dispatchEvent(new Event('input',{bubbles:true})); el.dispatchEvent(new Event('change',{bubbles:true})); }
                }
            """)
            pw_input = self._page.locator('#pw')
            try: pw_input.click(force=True, timeout=5000)
            except Exception: pw_input.focus()
            time.sleep(0.2)
            self._page.keyboard.press("Control+a"); self._page.keyboard.press("Backspace")
            for ch in account_pw:
                self._page.keyboard.type(ch, delay=random.choice([25,50,100,200]) + random.randint(0,50))
            time.sleep(0.4 + random.random() * 0.4)

            # 로그인 버튼
            try:
                self._page.locator('.btn_login').first.click(force=True, timeout=5000)
            except Exception:
                self._page.keyboard.press("Enter")

            time.sleep(2)

            def _success() -> bool:
                return "login" not in self._page.url.lower()

            if _success():
                self.log("info", f"[SSG] ✅ 로그인 성공: {account_id}")
                return True

            ok = self.wait_for_login_or_user(success_check=_success, timeout=120, poll_interval=2.0)
            if ok:
                self.log("info", f"[SSG] ✅ 로그인 성공: {account_id}")
                return True

            self.log("warning", f"[SSG] 로그인 실패: {account_id} (URL: {self._page.url[:80]})")
            return False
        except Exception as e:
            self.log("error", f"[SSG] 로그인 오류: {e}")
            return False
