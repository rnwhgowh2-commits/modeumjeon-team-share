"""소싱처 스크래퍼 베이스 — 송장전송기 sourcing_scrapers.py:BaseScraper 의 sync 포팅.

핵심:
  · 계정별 독립 크롬 프로필 (persistent context)
  · 우측 상단 미니창 (PC 사용 방해 최소화)
  · 봇 회피 args + stealth init script
  · launch_persistent_context channel="chrome" 1·2회 + chromium fallback
  · CDP 창 위치 강제 (Browser.setWindowBounds)
  · SingletonLock 충돌 자동 정리

송장전송기는 async/await — 본 모듈은 sync_playwright 사용.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Optional, Callable

from lemouton.auth.profile_store import (
    ProfileStore, default_store as profile_default_store,
    STEALTH_ARGS, STEALTH_INIT_SCRIPT,
    get_mini_window_args, set_window_bounds_cdp,
)

logger = logging.getLogger(__name__)

# 세션 storage_state JSON 백업 위치 (송장전송기 SESSION_DIR 패턴 포팅)
#   base.py = _시스템/lemouton/auth/scrapers/base.py → parents[3] = _시스템
SESSION_DIR = Path(__file__).resolve().parents[3] / "data" / "sessions"


class BaseScraper:
    """소싱처 스크래퍼 베이스 — 송장전송기 BaseScraper sync 포팅.

    Subclass 가 구현해야 하는 메서드:
      · ``_do_login(page, account_id, account_pw)`` → bool
      · ``_check_login_status(page)`` → bool (선택, 기본은 URL 기반)
      · ``site_key``, ``site_name``, ``login_url`` (클래스 속성)

    Subclass 가 사용하는 헬퍼 (이 클래스가 제공):
      · ``open_profile(account_id, login_method)`` — 미니창 + 페이지 반환
      · ``close()`` — 브라우저 닫음 (쿠키 디스크 자동 저장)
      · ``log(level, message)`` — 콜백 가능 로깅
      · ``close_chatbots(page)`` — 챗봇 자동 제거
    """

    site_key: str = ""
    site_name: str = ""
    login_url: str = ""

    # ★ session 만료 (expires_utc=0) 인 로그인 토큰 쿠키 이름 — 마법사 종료 직전 강제로 persistent 변환
    #   (Chrome 정책: session 쿠키는 브라우저 종료시 디스크에서 삭제되어 다음 인스턴스가 비로그인됨)
    #   Subclass 에서 사이트별로 override
    SESSION_TO_PERSISTENT_COOKIES: list = []

    def __init__(self, log_callback: Optional[Callable[[str, str], None]] = None,
                 profile_store: Optional[ProfileStore] = None):
        self._log_callback = log_callback
        self._profile_store = profile_store or profile_default_store()
        self._playwright = None
        self._browser = None
        self._page = None

    # ──────────────────────────────────────────────────────
    #  로깅
    # ──────────────────────────────────────────────────────

    def log(self, level: str, message: str) -> None:
        getattr(logger, level, logger.info)(message)
        if self._log_callback:
            try:
                self._log_callback(level, message)
            except Exception:
                pass

    # ──────────────────────────────────────────────────────
    #  Playwright 세션 관리
    # ──────────────────────────────────────────────────────

    def _start_playwright(self):
        if self._playwright is None:
            from playwright.sync_api import sync_playwright
            self._playwright = sync_playwright().start()

    def _stop_playwright(self):
        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception:
                pass
            self._playwright = None

    # ──────────────────────────────────────────────────────
    #  프로필 디렉터리 + Chrome 부팅
    # ──────────────────────────────────────────────────────

    def open_profile(self, account_id: str, login_method: str = "direct") -> bool:
        """계정별 프로필 부팅 — 미니창 + stealth + 채널 fallback.

        Returns True if 페이지 열림.
        """
        self.close()
        self._start_playwright()

        # [2026-06-05] 송장자동화와 동일 프로필(invoice_profiles/{...}) 사용 — 로그인이
        #   크롤과 같은 프로필에 저장돼야 함(직접=한글명_{id}, naver 등=key_method_{id}).
        from lemouton.auth.profile_store import resolve_profile_dir
        profile_path = resolve_profile_dir(self.site_key, account_id, login_method)
        profile_path.mkdir(parents=True, exist_ok=True)
        is_new = not any((profile_path / m).exists()
                         for m in ("Default", "Local State", "Cookies"))

        # SingletonLock 충돌 정리
        self._profile_store.kill_chrome_using(profile_path)
        self._profile_store.cleanup_lock(profile_path)

        stealth_args = list(STEALTH_ARGS) + get_mini_window_args()

        for attempt in range(1, 4):
            try:
                use_channel = "chrome" if attempt <= 2 else None
                self._browser = self._playwright.chromium.launch_persistent_context(
                    user_data_dir=str(profile_path),
                    headless=False,
                    channel=use_channel,
                    args=stealth_args,
                    ignore_default_args=["--enable-automation"],
                    locale="ko-KR",
                )
                self._page = self._browser.pages[0] if self._browser.pages else self._browser.new_page()
                self._page.add_init_script(STEALTH_INIT_SCRIPT)
                self._page.set_default_timeout(15000)

                # 우측 상단 미니창 강제
                set_window_bounds_cdp(self._page)

                status = "신규 생성" if is_new else "기존 쿠키"
                self.log("info", f"[{self.site_name}] 프로필 열기: {account_id} ({status})")
                return True
            except Exception as e:
                self.log("warning", f"[{self.site_name}] 프로필 열기 실패 ({attempt}/3): {e}")
                self.close()
                if attempt < 3:
                    time.sleep(2)
                    self._profile_store.kill_chrome_using(profile_path)
                    self._profile_store.cleanup_lock(profile_path)

        return False

    def close(self) -> None:
        """브라우저 닫기 + Playwright 종료 — 쿠키 자동 디스크 저장.

        송장전송기 _close_browser 패턴 + 자원 누수 방지를 위해 Playwright 도 같이 stop.
        """
        if self._browser:
            try:
                self._browser.close()
            except Exception:
                pass
            time.sleep(1)  # ← 송장전송기 sourcing_scrapers.py:428 동일 (쿠키 disk flush 대기)
        self._browser = None
        self._page = None
        # 자원 누수 방지 — Playwright 인스턴스도 함께 종료
        self._stop_playwright()

    def _persist_session_cookies(self, profile_path: Path, days: int = 30) -> int:
        """로그인 성공 후 session 쿠키 (expires_utc=0) 를 persistent 로 강제 변환.

        Chrome 의 기본 정책: session 쿠키는 브라우저 종료 시 디스크에서 삭제 →
        다음 인스턴스가 비로그인됨. 무신사처럼 로그인 토큰을 session 으로만
        발급하는 사이트에선 마법사 직후엔 잠깐 로그인되지만 Chrome 닫히면 사라짐.

        본 헬퍼: ``SESSION_TO_PERSISTENT_COOKIES`` 에 명시한 쿠키 이름의
        ``expires_utc`` 를 미래 (기본 30일) 로 강제 갱신 + ``is_persistent=1``.

        Args:
            profile_path: 영구 프로필 경로 (Chrome user_data_dir)
            days: 만료 일수 (기본 30)

        Returns:
            업데이트된 쿠키 row 수
        """
        if not self.SESSION_TO_PERSISTENT_COOKIES:
            return 0

        # Chrome 96+ : Default/Network/Cookies, Chrome 95- : Default/Cookies
        cookies_db = profile_path / "Default" / "Network" / "Cookies"
        if not cookies_db.exists():
            cookies_db = profile_path / "Default" / "Cookies"
        if not cookies_db.exists():
            self.log("warning", f"[{self.site_name}] Cookies SQLite 없음 — session 쿠키 변환 skip")
            return 0

        # Chrome epoch (1601-01-01) 기준 microseconds
        import datetime as _dt
        future = _dt.datetime.utcnow() + _dt.timedelta(days=days)
        chrome_epoch = _dt.datetime(1601, 1, 1)
        future_us = int((future - chrome_epoch).total_seconds() * 1_000_000)

        try:
            import sqlite3
            conn = sqlite3.connect(str(cookies_db), timeout=5)
            cur = conn.cursor()
            placeholders = ",".join(["?"] * len(self.SESSION_TO_PERSISTENT_COOKIES))
            params = [future_us] + list(self.SESSION_TO_PERSISTENT_COOKIES)
            cur.execute(
                f"UPDATE cookies SET expires_utc=?, is_persistent=1, has_expires=1 "
                f"WHERE name IN ({placeholders}) AND expires_utc=0",
                params,
            )
            n = cur.rowcount
            conn.commit()
            conn.close()
            if n > 0:
                self.log("info",
                         f"[{self.site_name}] session 쿠키 {n}개 → persistent 변환 (만료 +{days}일)")
            else:
                self.log("debug",
                         f"[{self.site_name}] 변환 대상 session 쿠키 없음 ({self.SESSION_TO_PERSISTENT_COOKIES})")
            return n
        except Exception as e:
            self.log("warning", f"[{self.site_name}] session 쿠키 변환 실패: {e}")
            return 0

    # ──────────────────────────────────────────────────────
    #  공통 헬퍼
    # ──────────────────────────────────────────────────────

    # ──────────────────────────────────────────────────────
    #  세션 storage_state JSON 저장/복원 (송장전송기 _save/_restore_session 포팅)
    #  ★ 네이버/구글 SSO 로그인 토큰(NID_AUT·NID_SES 등)은 session 쿠키(expires=-1)라
    #    Chrome 종료 시 디스크에서 소멸 → persistent 프로필만으로는 유지 불가.
    #    JSON 백업분을 매 실행 시 컨텍스트에 주입해 무인 재로그인 없이 세션 이어감.
    # ──────────────────────────────────────────────────────

    def _session_file_path(self, account_id: str, login_method: str = "direct") -> Path:
        """세션 JSON 경로 — 송장전송기와 동일 명명: {site_key}_{id}_{method}.json"""
        import re
        safe_id = re.sub(r"[^\w\-.]", "_", account_id or "default")
        safe_method = re.sub(r"[^\w\-]", "_", login_method or "direct")
        return SESSION_DIR / f"{self.site_key}_{safe_id}_{safe_method}.json"

    def _save_session(self, account_id: str, login_method: str = "direct") -> bool:
        """로그인 성공 후 storage_state(세션 쿠키 포함)를 JSON 에 원자적 저장."""
        ctx = self._browser
        if ctx is None:
            return False
        try:
            storage = ctx.storage_state()
            path = self._session_file_path(account_id, login_method)
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(json.dumps(storage, ensure_ascii=False), encoding="utf-8")
            tmp.replace(path)
            n = len(storage.get("cookies", []) or [])
            self.log("info", f"[{self.site_name}] 💾 세션 저장: {account_id} ({n}개 쿠키)")
            return True
        except Exception as e:
            self.log("warning", f"[{self.site_name}] 세션 저장 실패 (무시): {e}")
            return False

    def _restore_session(self, account_id: str, login_method: str = "direct") -> bool:
        """저장된 세션 쿠키가 있으면 현재 컨텍스트에 주입 (만료 쿠키는 제외).

        Playwright add_cookies 는 expires < now 인 만료 쿠키를 거부 → 세션(-1/0)·
        유효 쿠키만 복원. 서버가 무효 처리하면 어차피 재로그인으로 흐름.
        """
        ctx = self._browser
        if ctx is None:
            return False
        try:
            path = self._session_file_path(account_id, login_method)
            if not path.exists():
                return False
            storage = json.loads(path.read_text(encoding="utf-8"))
            cookies = storage.get("cookies", []) or []
            if not cookies:
                return False
            now = time.time()
            valid = []
            for c in cookies:
                exp = c.get("expires", -1)
                if exp in (-1, 0, None) or (isinstance(exp, (int, float)) and exp > now):
                    valid.append(c)
            if not valid:
                return False
            ctx.add_cookies(valid)
            self.log("info", f"[{self.site_name}] 🔑 세션 복원: {account_id} ({len(valid)}개 쿠키)")
            return True
        except Exception as e:
            self.log("warning", f"[{self.site_name}] 세션 복원 실패 (무시): {e}")
            return False

    def close_chatbots(self, page) -> None:
        """챗봇·해피톡·채널톡 등 셀렉터 가리는 요소 자동 제거."""
        try:
            page.evaluate("""
                document.querySelectorAll(
                    '[class*="chatbot"], [class*="happytalk"], [id*="chatbot"], '
                    + '[class*="channel-talk"], [id*="channelio"]'
                ).forEach(el => el.remove())
            """)
        except Exception:
            pass

    def wait_for_login_or_user(self,
                               success_check: Callable[[], bool],
                               captcha_selectors: Optional[list] = None,
                               timeout: int = 120,
                               poll_interval: float = 2.0) -> bool:
        """로그인 성공 또는 사용자 입력 완료까지 대기 — reCAPTCHA·2단계 인증 대응.

        ``success_check()`` 가 True 반환 시 즉시 성공 종료.
        타임아웃까지 미달성 시 False 반환 → 다음 계정으로 넘어감.

        Args:
            success_check: 매 폴링 시 호출 — 로그인 성공 여부 판정 (URL 변경 등)
            captcha_selectors: 사용자 개입 필요 요소 셀렉터 (감지 시 친절한 로그)
            timeout: 최대 대기 초 (기본 120초 = 2분)
            poll_interval: 폴링 주기 초

        Returns:
            True: 시간 안에 성공
            False: 타임아웃
        """
        if captcha_selectors is None:
            captcha_selectors = [
                'iframe[src*="recaptcha"]',
                'iframe[title*="reCAPTCHA"]',
                'iframe[title*="recaptcha"]',
                'div.g-recaptcha',
                'iframe[src*="captcha"]',
                '[class*="captcha"]',
            ]

        elapsed = 0.0
        captcha_notified = False
        last_log_at = 0.0

        while elapsed < timeout:
            # 1) 성공 체크
            try:
                if success_check():
                    if captcha_notified:
                        self.log("info", f"[{self.site_name}] ✅ 사용자 입력 완료 — 로그인 성공")
                    return True
            except Exception:
                pass

            # 2) 캡차/2단계 감지 → 한 번만 안내
            if not captcha_notified and self._page is not None:
                try:
                    for sel in captcha_selectors:
                        if self._page.locator(sel).count() > 0:
                            self.log("warning",
                                     f"[{self.site_name}] 🤖 reCAPTCHA / 봇 검사 감지 — "
                                     f"사용자가 직접 풀어주세요 (최대 {timeout}초 대기)")
                            captcha_notified = True
                            break
                except Exception:
                    pass

            # 3) 30초 단위 진행 로그
            if captcha_notified and (elapsed - last_log_at) >= 30:
                remaining = int(timeout - elapsed)
                self.log("info", f"[{self.site_name}] ⏳ 사용자 입력 대기 중 — 남은 시간 {remaining}초")
                last_log_at = elapsed

            time.sleep(poll_interval)
            elapsed += poll_interval

        # 타임아웃
        if captcha_notified:
            self.log("warning",
                     f"[{self.site_name}] ⏱ 사용자 입력 시간 초과 ({timeout}초) — 다음 계정으로 진행")
        else:
            self.log("warning",
                     f"[{self.site_name}] ⏱ 로그인 대기 타임아웃 ({timeout}초)")
        return False

    def check_login_status_by_logout(self, base_url: str) -> bool:
        """견고한 로그인 판별 (송장전송기 _check_login_status_by_logout 이식).

        ★ 약한 판별(URL에 'login' 없음, 콜백/브리지 도달)의 거짓 성공을 차단.
        판별 순서:
          1) 로그인 페이지로 리다이렉트 = 확정 비로그인
          2) **보이는** 로그아웃 링크 = 확정 로그인 (숨은 링크는 무시 — is_visible)
          3) **보이는** 로그인 링크 = 확정 비로그인
          4) 둘 다 없음/애매 = True (CSR 로딩 지연 + 세션 쿠키 신뢰)
        """
        if self._page is None:
            return False
        try:
            self._page.goto(base_url, wait_until="domcontentloaded", timeout=15000)
            time.sleep(2)
            cur = (self._page.url or "").lower()
            # 1) 로그인 페이지로 리다이렉트 = 확정 비로그인
            if any(k in cur for k in ("/login", "lcloginmem", "signin", "loginform", "nid.naver.com")):
                return False

            def _any_visible(selectors):
                for sel in selectors:
                    try:
                        for el in self._page.query_selector_all(sel):
                            try:
                                if el.is_visible():
                                    return True
                            except Exception:
                                continue
                    except Exception:
                        continue
                return False

            # 2) 보이는 로그아웃 링크/버튼 → 확정 로그인
            if _any_visible(['a[href*="logout"]', 'a[onclick*="logout"]',
                             'button[onclick*="logout"]', 'a:has-text("로그아웃")',
                             'button:has-text("로그아웃")', 'a:has-text("LOGOUT")']):
                return True

            # 3) 보이는 로그인 링크 → 확정 비로그인
            #    ★ href 기반만 사용 — a:has-text("로그인")은 프로모 문구("간편로그인 혜택" 등)를
            #      greedy 매칭해 로그인 상태 SSG를 오탐(False)시킴 (실측 확인). href에 login/signin
            #      포함된 실제 링크만 비로그인 신호로 인정. (javascript:redirectURL('login') 도 매칭)
            if _any_visible(['a[href*="login"]', 'a[href*="signin"]', 'a[href*="member/login"]']):
                return False

            # 4) 애매 → 낙관 (세션 쿠키 신뢰)
            return True
        except Exception as e:
            self.log("debug", f"[{self.site_name}] 로그인 상태 검사 실패: {e}")
            return False

    def _verify_logged_in(self) -> bool:
        """로그인 시도 직후 실제 로그인 여부 견고 검증 — 소싱처 main_url 기준.

        ``_do_naver_login`` / ``_do_login`` 이 콜백·브리지 URL을 거짓 성공으로
        반환하는 것을 차단하는 최종 게이트.
        """
        cfg = getattr(self, "naver_login_config", None) or {}
        main_url = cfg.get("main_url") or getattr(self, "main_url", None)
        if not main_url:
            # 자체 ID/PW 사이트 — login_url 도메인 루트 사용.
            #   login_url(로그인 경로)로 가면 URL에 'login'이 있어 항상 '미로그인' 오판됨.
            from urllib.parse import urlparse
            u = urlparse(self.login_url)
            main_url = f"{u.scheme}://{u.netloc}" if u.netloc else self.login_url
        return self.check_login_status_by_logout(main_url)

    # ──────────────────────────────────────────────────────
    #  메인 로그인 흐름 (송장전송기 ensure_logged_in 의 sync 포팅)
    # ──────────────────────────────────────────────────────

    def ensure_logged_in(self, account_id: str, account_pw: str,
                         login_method: str = "direct",
                         max_retry: int = 3,
                         skip_if_logged_in: bool = True) -> bool:
        """프로필 부팅 + 로그인 + 자동 재시작 — 송장전송기 ensure_logged_in 패턴.

        보강:
          · 사전 쿠키 검증 (cookie_checker) — 부팅 전 빠른 판단
          · 부팅 실패 시 명확한 로그
          · 종료 시 자동 cleanup (호출자 부담 없음)

        Returns:
            True: 로그인 완료 (쿠키 영구 저장됨)
            False: 최종 실패
        """
        # 0) 송장전송기 패턴 — 사전 쿠키 검증 (부팅 회피)
        try:
            from lemouton.auth.cookie_checker import is_likely_logged_in
            from lemouton.auth.profile_store import resolve_profile_dir
            profile_path = resolve_profile_dir(self.site_key, account_id, login_method)
            if skip_if_logged_in and is_likely_logged_in(profile_path, self.site_key):
                self.log("info", f"[{self.site_name}] {account_id} 쿠키 사전 검증 통과 — 부팅 시 검증 모드")
        except Exception as e:
            self.log("debug", f"[{self.site_name}] 사전 검증 skip ({e})")

        # 1) 프로필 부팅
        if not self.open_profile(account_id, login_method):
            self.log("error", f"[{self.site_name}] {account_id} 프로필 부팅 실패 — Playwright/Chrome 미설치 가능")
            return False

        # 변환 대상 프로필 경로 (성공 시 close() 후 session→persistent 변환)
        from lemouton.auth.profile_store import resolve_profile_dir as _rpd
        _profile_path = _rpd(self.site_key, account_id, login_method)
        login_success = False
        try:
            # 0) 저장된 세션 쿠키 복원 (송장전송기 패턴) — 네이버/구글 SSO 세션 부활
            #    persistent 프로필이 잃어버린 session 쿠키(NID_AUT 등)를 JSON 백업분으로 주입
            self._restore_session(account_id, login_method)

            # 2) 이미 로그인된 상태면 스킵 (★ 견고 검증 — main_url 로그아웃 링크 가시성 기준)
            if skip_if_logged_in and self._verify_logged_in():
                self.log("info", f"[{self.site_name}] {account_id} 이미 로그인됨 — 스킵 (검증 통과)")
                login_success = True
                return True

            # 3) 자동 재시작 (송장전송기 5/10/20초 backoff)
            backoffs = [5, 10, 20]
            for attempt in range(1, max_retry + 1):
                try:
                    # 로그인 시도 (네이버 SSO 또는 자체 ID/PW)
                    if login_method == "naver" and getattr(self, "naver_login_config", None):
                        attempted = self._do_naver_login(account_id, account_pw)
                    else:
                        attempted = self._do_login(account_id, account_pw)

                    # ★ 신뢰성 게이트 — 시도가 True여도 실제 로그인 검증 통과해야 성공
                    #   (콜백/브리지 URL 거짓 성공 차단 — 송장전송기 _check_login_status 패턴)
                    if attempted and self._verify_logged_in():
                        self.log("info", f"[{self.site_name}] {account_id} 로그인 성공 (검증 통과)")
                        login_success = True
                        return True
                    if attempted:
                        self.log("warning",
                                 f"[{self.site_name}] {account_id} 로그인 반환 True지만 검증 실패 — 거짓 성공 차단, 재시도")
                    if attempt < max_retry:
                        wait_sec = backoffs[min(attempt - 1, len(backoffs) - 1)]
                        self.log("warning", f"[{self.site_name}] 재시도 {wait_sec}초 후 ({attempt}/{max_retry})")
                        time.sleep(wait_sec)
                        try:
                            self._page.goto(self.login_url, wait_until="domcontentloaded", timeout=15000)
                            self.close_chatbots(self._page)
                        except Exception:
                            pass
                except Exception as e:
                    self.log("error", f"[{self.site_name}] 로그인 예외 ({attempt}/{max_retry}): {e}")
                    if attempt < max_retry:
                        time.sleep(backoffs[min(attempt - 1, len(backoffs) - 1)])

            self.log("error", f"[{self.site_name}] {account_id} 로그인 최종 실패")
            return False
        finally:
            # ★ 로그인 성공 시 storage_state JSON 저장 (close() 전 — 컨텍스트 필요)
            if login_success:
                try:
                    self._save_session(account_id, login_method)
                except Exception as e:
                    self.log("warning", f"[{self.site_name}] 세션 저장 예외: {e}")
            # 자동 cleanup — 호출자 부담 없음 (송장전송기 _close_browser 패턴)
            self.close()
            # ★ 로그인 성공 시 session 쿠키 → persistent 강제 변환
            #   (Chrome 종료 후 SQLite 직접 UPDATE — Chrome 락 풀린 상태에서)
            if login_success:
                try:
                    self._persist_session_cookies(_profile_path)
                except Exception as e:
                    self.log("warning", f"[{self.site_name}] session 쿠키 변환 예외: {e}")

    def _already_logged_in_quick(self) -> bool:
        """페이지 진입 직후 이미 로그인 상태인지 검사 (subclass 가 override 가능).

        강화 (2026-05): DNS 실패·리다이렉트 루프 시 false positive 방지.
        - goto 예외 시 무조건 False (에러 = 로그인 안 된 상태로 간주)
        - 결과 URL 이 about:blank / chrome-error / 빈 문자열이면 False
        - login_url 에 도달 못 했고 main_url 도메인에 진입한 경우만 True
        """
        try:
            self._page.goto(self.login_url, wait_until="domcontentloaded", timeout=15000)
        except Exception:
            return False

        time.sleep(2)
        cur = self._page.url or ""
        if not cur or cur.startswith("about:") or cur.startswith("chrome-error://"):
            return False

        # 로그인 관련 키워드 + nid.naver.com (네이버 OAuth 도 로그인 진행 중) → 미로그인
        login_keywords = ["/login", "/auth", "/member/login", "nid.naver.com"]
        return not any(k in cur for k in login_keywords)

    # ──────────────────────────────────────────────────────
    #  Subclass 가 구현해야 하는 추상 메서드
    # ──────────────────────────────────────────────────────

    def _do_login(self, account_id: str, account_pw: str) -> bool:
        """실제 ID/PW 입력 + 제출. Subclass 에서 구현."""
        raise NotImplementedError(f"{self.__class__.__name__}._do_login 미구현")

    # ──────────────────────────────────────────────────────
    #  네이버 SSO 로그인 (송장전송기 _do_external_login 의 sync 포팅)
    # ──────────────────────────────────────────────────────

    def _naver_fill_login(self, target_page, account_id: str, account_pw: str,
                          label: str = "페이지") -> bool:
        """네이버 로그인 폼(#id, #pw)에 ID/PW 자동 입력.

        target_page: 팝업 또는 리다이렉트된 페이지 객체
        Returns: 입력 + 제출 성공 여부
        """
        try:
            try:
                if target_page.is_closed():
                    self.log("warning", f"[{self.site_name}] 네이버 {label}: 페이지 닫힘")
                    return False
            except Exception:
                pass

            cur_url = (target_page.url or "").lower()
            self.log("info", f"[{self.site_name}] 네이버 {label} URL 확인: {cur_url[:80]}")
            # ★ 중간 브릿지 페이지(GS샵 grm.gsretail.com/.../signin/bridge?page=naver)에서
            #   네이버 로그인 폼(nid.naver.com)으로 리다이렉트되는 데 수 초 걸릴 수 있음 → 대기
            #   (송장전송기 _naver_fill_login 패턴 — 미이식 시 GS 즉시 포기 → 거짓 실패)
            if "nid.naver.com" not in cur_url:
                for _ in range(24):  # 최대 12초
                    time.sleep(0.5)
                    try:
                        cur_url = (target_page.url or "").lower()
                    except Exception:
                        break
                    if "nid.naver.com" in cur_url:
                        self.log("info", f"[{self.site_name}] 네이버 {label} 폼 리다이렉트 도달: {cur_url[:80]}")
                        break
            if "nid.naver.com" not in cur_url:
                self.log("warning", f"[{self.site_name}] 네이버 {label}: 네이버 로그인 페이지 아님")
                return False

            id_el = target_page.query_selector('#id')
            if not id_el:
                self.log("warning", f"[{self.site_name}] 네이버 {label}: #id 입력란 없음")
                return False

            self.log("info", f"[{self.site_name}] 네이버 {label} ID/PW 입력 중...")
            target_page.fill('#id', account_id)
            time.sleep(0.5)
            target_page.fill('#pw', account_pw)
            time.sleep(0.5)

            login_btn = target_page.query_selector('.btn_login, .btn_global, #log\\.login, button[type="submit"]')
            if login_btn:
                login_btn.click()
            else:
                target_page.press('#pw', 'Enter')
            self.log("info", f"[{self.site_name}] 네이버 로그인 제출 완료")
            time.sleep(4)
            return True
        except Exception as e:
            self.log("warning", f"[{self.site_name}] 네이버 {label} 자동입력 실패: {e}")
            return False

    def _do_naver_login(self, account_id: str, account_pw: str) -> bool:
        """네이버 SSO 로그인 흐름 (송장전송기 _do_external_login("naver") sync 포팅).

        흐름:
          1. ``self.naver_login_config["login_url"]`` 접속
          2. ``self.naver_login_config["naver_btn"]`` 클릭 (window.open 가로채기)
          3-A. 팝업 URL 캡처 → 같은 창에서 네이버 OAuth → ID/PW 입력
          3-B. 캡처 실패 → 리다이렉트/팝업 fallback
          4. 콜백 URL 도달 시 성공 판정

        ``self.naver_login_config`` 클래스 속성 필요:
            {
                "login_url": "...",
                "naver_btn": "셀렉터(콤마구분 가능)",
                "main_url": "...",
            }
        """
        from urllib.parse import urlparse

        cfg = getattr(self, "naver_login_config", None)
        if not cfg or not self._page:
            return False

        login_url = cfg["login_url"]
        main_url = cfg.get("main_url", "")
        naver_selector = cfg["naver_btn"]

        # 1) 로그인 페이지 접속
        try:
            self._page.goto(login_url, wait_until="domcontentloaded", timeout=30000)
        except Exception:
            try:
                self._page.goto(login_url, wait_until="load", timeout=30000)
            except Exception as e:
                self.log("warning", f"[{self.site_name}] 로그인 페이지 접속 실패: {e}")
                return False
        time.sleep(3)
        self.close_chatbots(self._page)

        # 2) 네이버 버튼 존재 확인
        naver_btn = self._page.query_selector(naver_selector)
        if not naver_btn:
            self.log("warning",
                     f"[{self.site_name}] 네이버 로그인 버튼 없음 (URL: {self._page.url[:60]})")
            return False
        self.log("info", f"[{self.site_name}] 네이버 로그인 버튼 클릭")

        # 3) window.open 가로채기 → 팝업 URL 캡처
        first_selector = naver_selector.split(",")[0].strip()
        # 따옴표 이스케이프 (JS 문자열 안에 들어가야 함)
        js_safe_selector = first_selector.replace("\\", "\\\\").replace("'", "\\'")
        # ★ popup_mode 사이트(GS 등): window.open 가로채면 콜백 페이지가 window.close()
        #   를 못 해 stuck → 브리지 URL을 거짓 성공으로 오판. 가로채기 건너뛰고 아래
        #   '진짜 팝업' 분기로 처리 (송장전송기 popup_mode 패턴).
        is_popup_mode = bool(cfg.get("popup_mode", False))
        naver_url = None
        if is_popup_mode:
            self.log("info", f"[{self.site_name}] popup_mode — window.open 가로채기 건너뜀 (진짜 팝업 처리)")
        else:
            try:
                naver_url = self._page.evaluate(f"""
                    () => {{
                        return new Promise(resolve => {{
                            const origOpen = window.open;
                            window.open = function(url) {{
                                resolve(url || null);
                                return null;
                            }};
                            const btn = document.querySelector('{js_safe_selector}');
                            if (btn) btn.click();
                            setTimeout(() => resolve(null), 3000);
                        }});
                    }}
                """)
            except Exception as e:
                # btn.click() 이 즉시 navigation 발생 시 context 파괴 — 직접 navigation 발생한 것
                self.log("info",
                         f"[{self.site_name}] 네이버 버튼 클릭 → 직접 navigation (evaluate context 파괴): {type(e).__name__}")
                # 잠깐 대기 후 현재 URL 검사
                time.sleep(3)
                cur_after_click = (self._page.url or "").lower()
                self.log("info", f"[{self.site_name}] 클릭 후 URL: {cur_after_click[:80]}")
                # 네이버 OAuth 로 이미 이동한 경우 → naver_url 은 None 으로 두고 fallback 분기로 진입

        if naver_url:
            # 상대 URL 이면 절대 URL 로 변환
            if str(naver_url).startswith("/"):
                base = urlparse(self._page.url)
                naver_url = f"{base.scheme}://{base.netloc}{naver_url}"

            self.log("info", f"[{self.site_name}] 팝업 URL 캡처 → 같은 창에서 로그인")
            try:
                self._page.goto(naver_url, wait_until="domcontentloaded", timeout=15000)
            except Exception as e:
                self.log("warning", f"[{self.site_name}] 네이버 URL 이동 실패: {e}")
            time.sleep(2)

            # 중간 페이지일 수 있음 → 네이버 OAuth 도달 또는 자동 콜백 대기
            already_done = False
            for _ in range(10):
                cur = (self._page.url or "").lower()
                if "nid.naver.com" in cur:
                    break
                domain = (urlparse(main_url).hostname or "").replace("www.", "")
                success_signs = ["login-success", "oauth/callback", "signin/bridge"]
                if (domain and domain in cur) or any(p in cur for p in success_signs):
                    already_done = True
                    break
                time.sleep(1)
            time.sleep(1)

            if not already_done:
                # reCAPTCHA / 보안 문자 등장 가능 → 사용자 입력 2분 대기 후 ID/PW 자동입력
                # 네이버 페이지 내에 캡차 떠 있는지 먼저 검사
                try:
                    captcha_seen = (self._page.locator(
                        'iframe[src*="recaptcha"], #captcha_img, [class*="captcha"]'
                    ).count() > 0)
                except Exception:
                    captcha_seen = False

                if captcha_seen:
                    self.log("warning",
                             f"[{self.site_name}] 🤖 네이버 캡차 감지 — 사용자 직접 풀어주세요 (2분 대기)")

                    def _captcha_passed() -> bool:
                        # 캡차가 사라지거나 URL 이 바뀌면 통과
                        try:
                            return self._page.locator('#captcha_img').count() == 0
                        except Exception:
                            return False

                    self.wait_for_login_or_user(success_check=_captcha_passed,
                                                timeout=120, poll_interval=2.0)

                # 폼 자동 입력
                self._naver_fill_login(self._page, account_id, account_pw, "리다이렉트")

                # 콜백 대기
                domain = (urlparse(main_url).hostname or "").replace("www.", "")
                for _ in range(15):
                    time.sleep(1)
                    cur = (self._page.url or "").lower()
                    if domain and domain in cur:
                        break
                    if "nid.naver" not in cur and "naver.com/login" not in cur:
                        break
        else:
            # window.open 미사용 — 직접 navigation / 팝업 fallback
            cur_now = (self._page.url or "").lower()
            self.log("info", f"[{self.site_name}] window.open 캡처 안 됨 (현재 URL: {cur_now[:60]})")

            popup_holder = {"page": None}

            def _on_popup(page):
                popup_holder["page"] = page

            try:
                self._browser.on("page", _on_popup)
            except Exception:
                pass

            # 이미 nid.naver.com 으로 이동했으면 클릭 재시도 안 함 (직접 navigation 케이스)
            if "nid.naver.com" not in cur_now:
                try:
                    naver_btn.click()
                except Exception as e:
                    self.log("debug", f"[{self.site_name}] 네이버 버튼 재클릭 실패: {e}")
            time.sleep(3)

            popup = popup_holder.get("page")
            if popup is not None:
                try:
                    popup.wait_for_load_state("domcontentloaded", timeout=10000)
                except Exception:
                    pass
                self.log("info", f"[{self.site_name}] 네이버 팝업 감지 → 입력 시도")
                self._naver_fill_login(popup, account_id, account_pw, "팝업")
                # 팝업 닫힘 대기 (최대 30초)
                for _ in range(30):
                    time.sleep(1)
                    try:
                        if popup.is_closed():
                            break
                    except Exception:
                        break
                time.sleep(2)
                try:
                    self._page.reload(wait_until="domcontentloaded")
                except Exception:
                    pass
                time.sleep(2)
            else:
                # 같은 창 리다이렉트
                if "nid.naver.com" in (self._page.url or "").lower():
                    self._naver_fill_login(self._page, account_id, account_pw, "리다이렉트")
                    for _ in range(15):
                        time.sleep(1)
                        cur = (self._page.url or "").lower()
                        if "nid.naver" not in cur and "naver.com/login" not in cur:
                            break
                else:
                    time.sleep(5)

        # 4) 결과 확인 — 도메인 기반 검사 (login 단어가 query string 에 들어가도 안전)
        cur_url = (self._page.url or "").lower()
        cur_host = (urlparse(self._page.url).hostname or "").lower()
        main_host = (urlparse(main_url).hostname or "").lower().replace("www.", "")
        self.log("info", f"[{self.site_name}] 네이버 로그인 후 URL: {cur_url[:80]}")

        # ① 명시적 OAuth 콜백 패턴 (path 부분 한정)
        path_only = (urlparse(self._page.url).path or "").lower()
        success_patterns = ["login-success", "/callback", "/sns/", "/signin/bridge", "oauth/callback"]
        if any(p in path_only for p in success_patterns):
            self.log("info", f"[{self.site_name}] 네이버 OAuth 콜백 성공 (path: {path_only[:60]})")
            return True

        # ② 네이버 도메인 벗어났고, 소싱처 main 도메인에 도달 → 성공
        in_naver = "nid.naver.com" in cur_host or cur_host == "naver.com" or cur_host.endswith(".naver.com")
        if not in_naver and main_host and main_host in cur_host:
            self.log("info", f"[{self.site_name}] 네이버 SSO 완료 후 {cur_host} 도달 — 성공")
            return True

        # ③ 메인 페이지에서 로그아웃/마이페이지 링크 검사 (마지막 수단)
        if main_url:
            try:
                self._page.goto(main_url, wait_until="domcontentloaded", timeout=15000)
                time.sleep(2)
                body = self._page.inner_text("body") or ""
                if "로그아웃" in body[:3000] or "마이페이지" in body[:3000] or "주문" in body[:3000]:
                    self.log("info", f"[{self.site_name}] 메인페이지 로그아웃 링크 발견 — 성공")
                    return True
            except Exception:
                pass

        self.log("warning", f"[{self.site_name}] 네이버 로그인 실패 — 수동 로그인 필요")
        return False
