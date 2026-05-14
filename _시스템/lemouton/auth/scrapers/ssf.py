"""SSF샵 스크래퍼 — 송장전송기 sourcing_scrapers.py:SSFShopScraper 의 sync 포팅.

2026-04 기준:
  - URL: /public/member/login (구 /member/login 은 404)
  - ID: ``#userId`` (구 ``#id``)
  - PW: ``#password`` (구 ``#pw``)
  - 3단계 방어: JS 초기화 + click(force) + Ctrl+A+Backspace + 불규칙 타이핑
"""
from __future__ import annotations

import random
import time
from .base import BaseScraper


class SSFShopScraper(BaseScraper):
    site_key = "ssf"
    site_name = "SSF샵"
    login_url = "https://www.ssfshop.com/public/member/login"

    # 2026-05-05 디스크 진단: SSF 의 핵심 로그인 토큰 = MBRNO (회원번호) 가 session 만료 발급됨
    #   → Chrome 종료 시 사라져 다음 인스턴스가 비로그인. 30일 영구 변환 필수.
    #   (PCID/PC_JSESSIONID/e_mbr 는 이미 persistent 로 발급됨)
    SESSION_TO_PERSISTENT_COOKIES = ["MBRNO"]

    def _do_login(self, account_id: str, account_pw: str) -> bool:
        """SSF샵 로그인 — 송장전송기 sourcing_scrapers.py:1786 와 100% 동일."""
        try:
            self._page.goto(self.login_url, wait_until="domcontentloaded", timeout=15000)
            time.sleep(2)
            self.close_chatbots(self._page)

            # ID 입력 — 3단계 방어
            self._page.evaluate("""
                () => {
                    const el = document.querySelector('#userId');
                    if (el) {
                        el.value = '';
                        el.dispatchEvent(new Event('input', {bubbles:true}));
                        el.dispatchEvent(new Event('change', {bubbles:true}));
                    }
                }
            """)
            id_input = self._page.locator('#userId')
            try:
                id_input.click(force=True, timeout=5000)
            except Exception:
                id_input.focus()
            time.sleep(0.2)
            self._page.keyboard.press("Control+a")
            self._page.keyboard.press("Backspace")
            for ch in account_id:
                delay = random.choice([30, 60, 120, 250]) + random.randint(0, 50)
                self._page.keyboard.type(ch, delay=delay)
            time.sleep(0.3 + random.random() * 0.3)

            # PW 입력 — 동일 3단계 방어
            self._page.evaluate("""
                () => {
                    const el = document.querySelector('#password');
                    if (el) {
                        el.value = '';
                        el.dispatchEvent(new Event('input', {bubbles:true}));
                        el.dispatchEvent(new Event('change', {bubbles:true}));
                    }
                }
            """)
            pw_input = self._page.locator('#password')
            try:
                pw_input.click(force=True, timeout=5000)
            except Exception:
                pw_input.focus()
            time.sleep(0.2)
            self._page.keyboard.press("Control+a")
            self._page.keyboard.press("Backspace")
            for ch in account_pw:
                delay = random.choice([25, 50, 100, 200]) + random.randint(0, 50)
                self._page.keyboard.type(ch, delay=delay)
            time.sleep(0.4 + random.random() * 0.4)

            # 로그인 버튼 (#loginForm 내부)
            submit = self._page.locator('#loginForm button:has-text("로그인"), #loginForm [type="submit"]').first
            try:
                submit.click(force=True, timeout=5000)
            except Exception:
                submit.click()

            # 초기 서버 응답 대기
            time.sleep(2)

            def _success() -> bool:
                return "login" not in self._page.url.lower()

            if _success():
                self.log("info", f"[SSF샵] ✅ 로그인 성공: {account_id}")
                return True

            # reCAPTCHA / 봇 검사 / 2단계 인증 — 사용자 개입 2분 대기
            ok = self.wait_for_login_or_user(
                success_check=_success,
                timeout=120,
                poll_interval=2.0,
            )
            if ok:
                self.log("info", f"[SSF샵] ✅ 로그인 성공: {account_id}")
                return True

            self.log("warning", f"[SSF샵] 로그인 실패: {account_id} (URL: {self._page.url[:80]})")
            return False
        except Exception as e:
            self.log("error", f"[SSF샵] 로그인 오류: {e}")
            return False
