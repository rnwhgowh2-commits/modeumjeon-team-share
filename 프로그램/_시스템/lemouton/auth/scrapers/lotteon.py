"""롯데온 스크래퍼 — 송장전송기 sourcing_scrapers.py:LotteonScraper sync 포팅."""
from __future__ import annotations

import random
import time
from .base import BaseScraper


class LotteonScraper(BaseScraper):
    site_key = "lotteon"
    site_name = "롯데온"
    # 2026-05 실측: /login 은 무한 리다이렉트 → /p/member/gate/forwarding/login 사용
    login_url = "https://www.lotteon.com/p/member/gate/forwarding/login"

    naver_login_config = {
        "login_url": "https://www.lotteon.com/p/member/gate/forwarding/login",
        "naver_btn": 'button.naverLoginBtn, button:has-text("네이버"), a:has-text("네이버")',
        "main_url": "https://www.lotteon.com",
    }

    def _do_login(self, account_id: str, account_pw: str) -> bool:
        # 2026-05 — 롯데온은 자체 ID/PW 로그인 미지원 → 네이버 SSO 강제 분기
        # base 의 login_method 가 "naver" 가 아니어도 무조건 네이버 로그인 시도
        self.log("info", f"[롯데온] 네이버 SSO 로그인 시도 — 자체 ID/PW 미지원")
        return self._do_naver_login(account_id, account_pw)

    # ↓↓ 아래는 사용 안 됨 (legacy / backward compat) — 자체 로그인 페이지 ID/PW 셀렉터
    def _do_login_LEGACY_unused(self, account_id: str, account_pw: str) -> bool:
        try:
            self._page.goto(self.login_url, wait_until="domcontentloaded", timeout=15000)
            time.sleep(2)
            self.close_chatbots(self._page)
            try:
                self._page.wait_for_selector(
                    'input[name="memberId"], #memberId, input[name="inId"], #inId',
                    timeout=8000,
                )
            except Exception:
                self.log("warning", "[롯데온] ID input 셀렉터 대기 타임아웃 (8s) — 셀렉터 변경 가능성")

            # ID 3단계 방어 — 2026-05 셀렉터 갱신 (memberId → inId 변경)
            self._page.evaluate("""
                () => {
                    document.querySelectorAll('input[name="memberId"], #memberId, input[name="inId"], #inId').forEach(el => {
                        el.value=''; el.dispatchEvent(new Event('input',{bubbles:true})); el.dispatchEvent(new Event('change',{bubbles:true}));
                    });
                }
            """)
            id_input = self._page.locator(
                'input[name="memberId"], #memberId, input[name="inId"], #inId'
            ).first
            try: id_input.click(force=True, timeout=5000)
            except Exception: id_input.focus()
            time.sleep(0.2)
            self._page.keyboard.press("Control+a"); self._page.keyboard.press("Backspace")
            for ch in account_id:
                self._page.keyboard.type(ch, delay=random.choice([30,60,120,250]) + random.randint(0,50))
            time.sleep(0.3 + random.random() * 0.3)

            # PW 3단계 방어 — 2026-05 셀렉터 갱신 (password → Password 대문자 변경)
            self._page.evaluate("""
                () => {
                    document.querySelectorAll('input[name="password"], #password, input[name="Password"], #Password').forEach(el => {
                        el.value=''; el.dispatchEvent(new Event('input',{bubbles:true})); el.dispatchEvent(new Event('change',{bubbles:true}));
                    });
                }
            """)
            pw_input = self._page.locator(
                'input[name="password"], #password, input[name="Password"], #Password'
            ).first
            try: pw_input.click(force=True, timeout=5000)
            except Exception: pw_input.focus()
            time.sleep(0.2)
            self._page.keyboard.press("Control+a"); self._page.keyboard.press("Backspace")
            for ch in account_pw:
                self._page.keyboard.type(ch, delay=random.choice([25,50,100,200]) + random.randint(0,50))
            time.sleep(0.4 + random.random() * 0.4)

            # 로그인 버튼
            clicked = False
            for sel in ['button[type="submit"]', '.btn_login', 'button:has-text("로그인")']:
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
                self.log("info", f"[롯데온] ✅ 로그인 성공: {account_id}")
                return True

            ok = self.wait_for_login_or_user(success_check=_success, timeout=120, poll_interval=2.0)
            if ok:
                self.log("info", f"[롯데온] ✅ 로그인 성공: {account_id}")
                return True

            self.log("warning", f"[롯데온] 로그인 실패: {account_id} (URL: {self._page.url[:80]})")
            return False
        except Exception as e:
            self.log("error", f"[롯데온] 로그인 오류: {e}")
            return False
