"""롯데홈쇼핑 (롯데아이몰) 스크래퍼 — 송장전송기 sourcing_scrapers.py:LotteimallScraper sync 포팅.

특징:
  · L.POINT SSO — fnLogin() JS 함수 호출
  · CAPTCHA 감지 시 base.wait_for_login_or_user() 로 사용자 입력 2분 대기
  · 3회 재시도 패턴 + 3단계 방어
"""
from __future__ import annotations

import random
import time
from .base import BaseScraper


class LotteimallScraper(BaseScraper):
    site_key = "lotteimall"
    site_name = "롯데홈쇼핑"
    login_url = "https://www.lotteimall.com/member/login/forward.LCLoginMem.lotte"

    def _do_login(self, account_id: str, account_pw: str) -> bool:
        max_retry = 3
        for attempt in range(1, max_retry + 1):
            try:
                self.log("info", f"[롯데홈쇼핑] 로그인 시도 {attempt}/{max_retry}")
                self._page.goto(self.login_url, wait_until="domcontentloaded", timeout=15000)
                time.sleep(2)
                self.close_chatbots(self._page)

                self._page.wait_for_selector('#login_id', timeout=5000)

                # ID 3단계 방어
                self._page.evaluate("""
                    () => {
                        const el = document.querySelector('#login_id');
                        if (el) { el.value=''; el.dispatchEvent(new Event('input',{bubbles:true})); el.dispatchEvent(new Event('change',{bubbles:true})); }
                    }
                """)
                id_input = self._page.locator('#login_id')
                try: id_input.click(force=True, timeout=5000)
                except Exception: id_input.focus()
                time.sleep(0.2)
                self._page.keyboard.press("Control+a"); self._page.keyboard.press("Backspace")
                time.sleep(0.1)
                for ch in account_id:
                    self._page.keyboard.type(ch, delay=random.choice([30,60,120,250]) + random.randint(0,50))
                time.sleep(0.3 + random.random() * 0.3)

                # PW 3단계 방어
                self._page.evaluate("""
                    () => {
                        const el = document.querySelector('#password');
                        if (el) { el.value=''; el.dispatchEvent(new Event('input',{bubbles:true})); el.dispatchEvent(new Event('change',{bubbles:true})); }
                    }
                """)
                pw_input = self._page.locator('#password')
                try: pw_input.click(force=True, timeout=5000)
                except Exception: pw_input.focus()
                time.sleep(0.2)
                self._page.keyboard.press("Control+a"); self._page.keyboard.press("Backspace")
                time.sleep(0.1)
                for ch in account_pw:
                    self._page.keyboard.type(ch, delay=random.choice([25,50,100,200]) + random.randint(0,50))
                time.sleep(0.4 + random.random() * 0.4)

                # fnLogin() 호출
                self._page.evaluate("if (typeof fnLogin === 'function') fnLogin()")
                time.sleep(3)

                def _success() -> bool:
                    cur = self._page.url.lower()
                    return "login" not in cur and "lcloginmem" not in cur

                if _success():
                    self.log("info", f"[롯데홈쇼핑] ✅ 로그인 성공: {account_id}")
                    return True

                # CAPTCHA / 보안 문자 / 추가 인증 — base 헬퍼로 2분 대기
                # (송장전송기는 즉시 실패 반환했지만, 본 구현은 사용자 직접 풀 기회 부여)
                captcha_selectors = [
                    'iframe[src*="recaptcha"]',
                    '[name="captcha"]', '[id*="captcha"]', '[name="securityCode"]',
                    'img[src*="captcha"]', 'img[src*="security"]',
                ]
                ok = self.wait_for_login_or_user(
                    success_check=_success,
                    captcha_selectors=captcha_selectors,
                    timeout=120,
                    poll_interval=2.0,
                )
                if ok:
                    self.log("info", f"[롯데홈쇼핑] ✅ 로그인 성공: {account_id}")
                    return True

                self.log("warning", f"[롯데홈쇼핑] 로그인 실패 (시도 {attempt}) — URL: {self._page.url[:80]}")
                if attempt < max_retry:
                    time.sleep(2)
            except Exception as e:
                self.log("error", f"[롯데홈쇼핑] 로그인 오류 (시도 {attempt}): {e}")
                if attempt < max_retry:
                    time.sleep(2)

        self.log("error", f"[롯데홈쇼핑] 로그인 {max_retry}회 시도 모두 실패")
        return False
