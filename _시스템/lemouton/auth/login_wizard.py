"""소싱처 자동 로그인 위저드 — Playwright 부팅 + storage_state 저장.

설계:
  · ``start(source, account_key, login_url)`` → ``WizardResult(wizard_id, QUEUED)``
  · ``execute(wizard_id)`` → 부팅 + 사용자 수동 로그인 대기 + 세션 저장
  · 봇탐지 / 캡차 감지 시 ``USER_ACTION_REQUIRED`` 분기
  · 타임아웃 시 ``EXPIRED``
  · 일반 예외 시 ``FAILED`` (메시지 포함)

Phase 2-C 는 ``_launch_browser_and_wait`` 를 실제 Playwright 코드로 채움.
지금은 시그니처만 정의 (테스트는 Mock 으로 가로챔).
"""
from __future__ import annotations

import enum
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, Optional

from lemouton.auth.session_store import SessionStore

logger = logging.getLogger(__name__)


class LoginWizardError(RuntimeError):
    """위저드 실행 중 발생한 일반 오류."""


class BotDetectedError(LoginWizardError):
    """봇 탐지 / 캡차 감지 — 사용자 수동 개입 필요."""


class WizardStatus(enum.Enum):
    QUEUED = "queued"                          # 시작 직후
    LAUNCHING = "launching"                    # Playwright 부팅 중
    AWAITING_USER = "awaiting_user"            # 사용자 수동 로그인 대기
    SAVING = "saving"                          # storage_state 저장 중
    SUCCESS = "success"                        # 완료
    EXPIRED = "expired"                        # 타임아웃
    USER_ACTION_REQUIRED = "user_action_required"  # 봇탐지/캡차
    FAILED = "failed"                          # 일반 실패


@dataclass
class WizardResult:
    wizard_id: str
    source: str
    account_key: str
    login_url: str
    status: WizardStatus
    message: str = ""
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None


class PlaywrightLoginWizard:
    """소싱처 자동 로그인 오케스트레이터.

    Args:
        store: ``SessionStore`` 인스턴스 (성공 시 storage_state 저장)
        manual_login_wait_sec: 사용자 수동 로그인 대기 한계 (기본 300s)
    """

    def __init__(
        self,
        store: SessionStore,
        manual_login_wait_sec: int = 300,
    ) -> None:
        self.store = store
        self.manual_login_wait_sec = manual_login_wait_sec
        self._wizards: dict[str, WizardResult] = {}
        self.on_stage_change: Optional[Callable[[str, WizardStatus], None]] = None

    # ──────────────────────────────────────────────────────
    #  공개 API
    # ──────────────────────────────────────────────────────

    def start(
        self,
        source: str,
        account_key: str,
        login_url: str,
    ) -> WizardResult:
        """위저드 시작 — wizard_id 발급 후 QUEUED 상태."""
        wizard_id = f"wiz_{source}_{account_key}_{uuid.uuid4().hex[:8]}"
        result = WizardResult(
            wizard_id=wizard_id,
            source=source,
            account_key=account_key,
            login_url=login_url,
            status=WizardStatus.QUEUED,
        )
        self._wizards[wizard_id] = result
        logger.info("[wizard] queued — %s/%s id=%s", source, account_key, wizard_id)
        return result

    def get_status(self, wizard_id: str) -> WizardStatus:
        result = self._wizards.get(wizard_id)
        if result is None:
            raise LoginWizardError(f"unknown wizard_id: {wizard_id}")
        return result.status

    def execute(self, wizard_id: str) -> WizardResult:
        """동기 실행 — 부팅 → 대기 → 저장 단계 끝까지 진행 후 결과 반환."""
        result = self._wizards.get(wizard_id)
        if result is None:
            raise LoginWizardError(f"unknown wizard_id: {wizard_id}")

        try:
            # LAUNCHING
            self._set_status(wizard_id, WizardStatus.LAUNCHING)

            # AWAITING_USER (사용자 수동 로그인)
            self._set_status(wizard_id, WizardStatus.AWAITING_USER)
            storage_state = self._launch_browser_and_wait(
                source=result.source,
                login_url=result.login_url,
                wait_sec=self.manual_login_wait_sec,
            )

            if storage_state is None:
                # 타임아웃
                result.status = WizardStatus.EXPIRED
                result.message = (
                    f"타임아웃 ({self.manual_login_wait_sec}s) — "
                    f"사용자가 시간 내에 로그인하지 못함"
                )
                self._set_status(wizard_id, WizardStatus.EXPIRED)
                return result

            # SAVING
            self._set_status(wizard_id, WizardStatus.SAVING)
            self.store.save_session(result.source, result.account_key, storage_state)

            # SUCCESS
            result.status = WizardStatus.SUCCESS
            result.message = f"{result.source}/{result.account_key} 세션 저장 완료"
            result.finished_at = time.time()
            self._set_status(wizard_id, WizardStatus.SUCCESS)
            logger.info(
                "[wizard] success — %s/%s id=%s elapsed=%.1fs",
                result.source, result.account_key, wizard_id,
                result.finished_at - result.started_at,
            )
            return result

        except BotDetectedError as e:
            result.status = WizardStatus.USER_ACTION_REQUIRED
            result.message = (
                f"봇 탐지 / 캡차 발견 ({e}) — 사용자 직접 브라우저에서 로그인 후 재시도 필요"
            )
            result.finished_at = time.time()
            self._set_status(wizard_id, WizardStatus.USER_ACTION_REQUIRED)
            return result

        except Exception as e:
            result.status = WizardStatus.FAILED
            result.message = str(e)
            result.finished_at = time.time()
            self._set_status(wizard_id, WizardStatus.FAILED)
            logger.error(
                "[wizard] failed — %s/%s id=%s error=%s",
                result.source, result.account_key, wizard_id, e,
            )
            return result

    # ──────────────────────────────────────────────────────
    #  내부 — Phase 2-C 활성화 시 실 Playwright 코드로 교체
    # ──────────────────────────────────────────────────────

    def _launch_browser_and_wait(
        self,
        source: str,
        login_url: str,
        wait_sec: int,
        account_key: str = "default",
    ) -> Optional[dict]:
        """Phase 2-C — persistent_context 기반 영구 쿠키 로그인 (송장전송기 패턴).

        핵심:
          · 계정별 user_data_dir = ``data/profiles/{source}_{account_key}/``
          · 한 번 로그인하면 쿠키가 디스크에 영구 저장됨
          · 다음 호출 시 자동 로그인 상태 유지 (재로그인 불필요)
          · 다른 계정 전환 시 다른 user_data_dir 사용 → 격리 (봇/보안 이슈 방지)

        반환:
            성공 시 storage_state dict (호환용, 실 쿠키는 user_data_dir 에 저장),
            타임아웃 시 None.

        예외:
            BotDetectedError — 캡차/봇탐지
            RuntimeError — Playwright 미설치 / 브라우저 크래시
            ValueError — 자격증명 누락
        """
        try:
            from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
        except ImportError:
            raise RuntimeError(
                "Playwright 미설치 — `python -m pip install playwright && playwright install chromium`"
            )

        from lemouton.auth.sourcing_credentials import default_store as creds_store
        from lemouton.auth.profile_store import (
            default_store as profile_default_store,
            STEALTH_ARGS, STEALTH_INIT_SCRIPT,
            get_mini_window_args, set_window_bounds_cdp,
        )

        # 1) 자격증명 조회
        creds = creds_store().get(source, account_key)
        if not creds:
            all_creds = creds_store().load_all().get(source, {})
            if all_creds:
                first_key = next(iter(all_creds))
                creds = all_creds[first_key]
                account_key = first_key  # 계정 키도 갱신
                logger.info("[wizard] %s default 없음 → %s 사용", source, first_key)

        if not creds or not creds.get("id") or not creds.get("pw"):
            raise ValueError(
                f"{source} 자격증명 미등록 — /accounts/sourcing 위저드에서 ID/PW 입력 필요"
            )

        login_method = creds.get("login_method", "direct")

        # 2) 계정별 프로필 준비 (송장전송기 패턴)
        profile_store = profile_default_store()
        profile_path = profile_store.profile_dir(source, account_key)
        already_logged_in = profile_store.has_profile(source, account_key)

        # 같은 프로필 사용 중인 Chrome 강제 종료 (SingletonLock 충돌 방지)
        profile_store.kill_chrome_using(profile_path)
        profile_store.cleanup_lock(profile_path)

        logger.info(
            "[wizard] %s/%s 프로필 %s — %s",
            source, account_key,
            "기존 쿠키 사용" if already_logged_in else "신규 생성",
            profile_path,
        )

        # 3) launch_persistent_context — 쿠키 자동 저장 (송장전송기 패턴: 실 Chrome 우선)
        stealth_args = list(STEALTH_ARGS) + get_mini_window_args()  # 우측 상단 미니창
        with sync_playwright() as p:
            context = None
            for attempt in range(1, 4):
                try:
                    # 송장전송기 sourcing_scrapers.py:368 — 1·2회 시도는 실 Chrome, 3회는 chromium fallback
                    use_channel = "chrome" if attempt <= 2 else None
                    context = p.chromium.launch_persistent_context(
                        user_data_dir=str(profile_path),
                        headless=False,
                        channel=use_channel,
                        args=stealth_args,
                        ignore_default_args=["--enable-automation"],
                        locale="ko-KR",
                    )
                    break
                except Exception as e:
                    logger.warning("[wizard] launch_persistent_context 실패 %d/3 (channel=%s): %s",
                                   attempt, use_channel, e)
                    if attempt == 3:
                        raise RuntimeError(f"브라우저 부팅 실패 3회: {e}")
                    profile_store.kill_chrome_using(profile_path)
                    profile_store.cleanup_lock(profile_path)
                    time.sleep(2)

            try:
                page = context.pages[0] if context.pages else context.new_page()
                page.add_init_script(STEALTH_INIT_SCRIPT)

                # 우측 상단 미니창으로 강제 (송장전송기 sourcing_scrapers.py:387)
                set_window_bounds_cdp(page)

                try:
                    page.goto(login_url, wait_until="domcontentloaded", timeout=30000)
                except PWTimeout:
                    raise RuntimeError(f"{login_url} 접속 타임아웃")

                # 챗봇 자동 닫기 (무신사 happytalk 등)
                self._close_chatbots(page)

                # 4) 이미 로그인된 상태면 스킵
                if self._already_logged_in(page, source):
                    logger.info("[wizard] %s 이미 로그인됨 — 자동 입력 스킵", source)
                else:
                    # 5) 로그인 자동 재시작 — 송장전송기 LoginFailedError 패턴 (5/10/20초 backoff)
                    last_err = None
                    for attempt in range(1, 4):
                        try:
                            if login_method == "manual":
                                logger.info("[wizard] manual 모드 — 사용자 직접 로그인 대기")
                            elif login_method in ("naver", "kakao", "google"):
                                self._login_sns(page, source, login_method,
                                                creds["id"], creds["pw"])
                            else:
                                self._auto_fill_credentials(page, source,
                                                            creds["id"], creds["pw"])

                            if self._wait_login_success(page, source, wait_sec):
                                break
                            raise BotDetectedError(f"로그인 미완료 (attempt {attempt})")
                        except BotDetectedError:
                            raise  # 봇 탐지는 즉시 상위로 (재시작 의미 X)
                        except Exception as e:
                            last_err = e
                            logger.warning("[wizard] %s 로그인 실패 %d/3: %s", source, attempt, e)
                            if attempt == 3:
                                logger.error("[wizard] %s 로그인 최종 실패", source)
                                return None
                            backoff = [5, 10, 20][attempt - 1]
                            logger.info("[wizard] %d초 후 재시도", backoff)
                            time.sleep(backoff)
                            try:
                                page.goto(login_url, wait_until="domcontentloaded", timeout=30000)
                                self._close_chatbots(page)
                            except Exception:
                                pass

                # 6) storage_state 호환 반환 (실 쿠키는 user_data_dir 에 저장됨)
                state = context.storage_state()
                return state
            finally:
                if context:
                    context.close()

    def _already_logged_in(self, page, source: str) -> bool:
        """페이지 진입 시 이미 로그인된 상태인지 빠르게 검사."""
        SUCCESS_PATTERNS = self._success_patterns().get(source, {})
        try:
            cur_url = page.url
            url_ok = not any(p in cur_url for p in SUCCESS_PATTERNS.get("url_not_contains", ["/login"]))
            for s in SUCCESS_PATTERNS.get("selectors", []):
                try:
                    if page.locator(s).count() > 0:
                        return True
                except Exception:
                    pass
            return url_ok and bool(SUCCESS_PATTERNS.get("selectors"))
        except Exception:
            return False

    def _success_patterns(self) -> dict:
        return {
            "musinsa": {
                "url_not_contains": ["/auth/login", "/login"],
                "selectors": ["a[href*='logout']", '[class*="my"]', '[data-mds*="MyPage"]'],
            },
            "ssf": {
                "url_not_contains": ["/login", "/member/login"],
                "selectors": ["a[href*='logout']", "a[href*='myssf']"],
            },
            "lemouton": {
                "url_not_contains": ["/login.html"],
                "selectors": ["a[href*='logout']"],
            },
        }

    def _auto_fill_credentials(self, page, source: str, user_id: str, user_pw: str) -> None:
        """사이트별 자격증명 자동 입력 — 송장전송기 sourcing_scrapers.py 패턴 그대로 이식.

        무신사·SSF 둘 다 자동 클릭 + 자동 입력 + 자동 제출 (송장전송기와 100% 동일).
        성공 시 토스트, 실패 시 Playwright 창에 안내 배너.
        """
        try:
            if source == "musinsa":
                self._login_musinsa(page, user_id, user_pw)
            elif source == "ssf":
                self._login_ssf(page, user_id, user_pw)
            elif source == "lemouton":
                self._login_lemouton(page, user_id, user_pw)
            else:
                logger.warning("[wizard] %s 셀렉터 미정의 — 사용자 직접 로그인", source)
                self._inject_manual_banner(page, source, "셀렉터 미정의")
        except Exception as e:
            logger.warning("[wizard] %s 자동 입력 실패 (%s) — 사용자 직접 입력 필요", source, e)
            self._inject_manual_banner(page, source, str(e)[:80])

    def _login_musinsa(self, page, user_id: str, user_pw: str) -> None:
        """무신사 통합 로그인 (member.one.musinsa.com) — 송장전송기 sourcing_scrapers.py:1063 그대로.

        2026-03 기준 셀렉터: placeholder 기반 (name/id 없음)
        """
        import time
        # /auth/login → member.one.musinsa.com 자동 리디렉트 대기
        time.sleep(3)
        cur_url = page.url
        # 이미 로그인됨 (마이페이지로 리다이렉트)
        if "login" not in cur_url and "member.one" not in cur_url and "auth" not in cur_url:
            self._inject_input_done_banner(page, "musinsa", "이미 로그인됨")
            return

        # ID 입력 — 3단계 방어 (자동완성·잔존 값 누적 방지)
        page.wait_for_selector('input[placeholder*="통합계정"]', timeout=10000)
        page.evaluate("""
            () => {
                document.querySelectorAll('input[placeholder*="통합계정"], input[placeholder*="이메일"]').forEach(el => {
                    el.value = '';
                    el.dispatchEvent(new Event('input', {bubbles:true}));
                    el.dispatchEvent(new Event('change', {bubbles:true}));
                });
            }
        """)
        id_input = page.locator('input[placeholder*="통합계정"]')
        try:
            id_input.click(force=True, timeout=5000)
        except Exception:
            id_input.focus()
        time.sleep(0.2)
        page.keyboard.press("Control+a")
        page.keyboard.press("Backspace")
        id_input.press_sequentially(user_id, delay=50)
        time.sleep(0.3)

        # PW 입력 — 동일 3단계 방어
        page.evaluate("""
            () => {
                document.querySelectorAll('input[placeholder*="비밀번호"]').forEach(el => {
                    el.value = '';
                    el.dispatchEvent(new Event('input', {bubbles:true}));
                    el.dispatchEvent(new Event('change', {bubbles:true}));
                });
            }
        """)
        pw_input = page.locator('input[placeholder*="비밀번호"]')
        try:
            pw_input.click(force=True, timeout=5000)
        except Exception:
            pw_input.focus()
        time.sleep(0.2)
        page.keyboard.press("Control+a")
        page.keyboard.press("Backspace")
        pw_input.press_sequentially(user_pw, delay=30)
        time.sleep(0.5)

        # 로그인 버튼 자동 클릭 — 명확한 셀렉터 + force + 폴백
        clicked = False
        for sel in [
            'button.login-v2-button__item--black',
            'button.login-v2-button__item[type="submit"]',
            'button[type="submit"]:has-text("로그인")',
            'button[type="submit"]',
        ]:
            try:
                btn = page.locator(sel).first
                if btn.count() > 0:
                    btn.click(force=True, timeout=5000)
                    logger.info("[wizard] 무신사 클릭 성공 (셀렉터: %s)", sel)
                    clicked = True
                    break
            except Exception as e:
                logger.debug("[wizard] 무신사 셀렉터 %s 실패: %s", sel, e)
                continue
        if not clicked:
            try:
                page.keyboard.press("Enter")
                logger.info("[wizard] 무신사 Enter 키로 제출")
            except Exception:
                logger.warning("[wizard] 무신사 자동 클릭 실패 — 사용자 직접 누르세요")
        self._inject_input_done_banner(page, "musinsa", "로그인 클릭됨 — 결과 대기")

    def _login_ssf(self, page, user_id: str, user_pw: str) -> None:
        """SSF샵 로그인 — 송장전송기 sourcing_scrapers.py:1786 그대로.

        2026-04 셀렉터: #userId, #password (구 #id, #pw 에서 변경됨)
        3단계 방어: JS 초기화 + click(force) + Ctrl+A+Backspace + 불규칙 타이핑
        """
        import random
        import time

        # ID 입력 — 3단계 방어
        page.evaluate("""
            () => {
                const el = document.querySelector('#userId');
                if (el) {
                    el.value = '';
                    el.dispatchEvent(new Event('input', {bubbles:true}));
                    el.dispatchEvent(new Event('change', {bubbles:true}));
                }
            }
        """)
        id_input = page.locator('#userId')
        try:
            id_input.click(force=True, timeout=5000)
        except Exception:
            id_input.focus()
        time.sleep(0.2)
        page.keyboard.press("Control+a")
        page.keyboard.press("Backspace")
        for ch in user_id:
            delay = random.choice([30, 60, 120, 250]) + random.randint(0, 50)
            page.keyboard.type(ch, delay=delay)
        time.sleep(0.3 + random.random() * 0.3)

        # PW 입력 — 동일 3단계 방어
        page.evaluate("""
            () => {
                const el = document.querySelector('#password');
                if (el) {
                    el.value = '';
                    el.dispatchEvent(new Event('input', {bubbles:true}));
                    el.dispatchEvent(new Event('change', {bubbles:true}));
                }
            }
        """)
        pw_input = page.locator('#password')
        try:
            pw_input.click(force=True, timeout=5000)
        except Exception:
            pw_input.focus()
        time.sleep(0.2)
        page.keyboard.press("Control+a")
        page.keyboard.press("Backspace")
        for ch in user_pw:
            delay = random.choice([25, 50, 100, 200]) + random.randint(0, 50)
            page.keyboard.type(ch, delay=delay)
        time.sleep(0.4 + random.random() * 0.4)

        # 로그인 버튼 (#loginForm 내부)
        submit = page.locator('#loginForm button:has-text("로그인"), #loginForm [type="submit"]').first
        try:
            submit.click(force=True, timeout=5000)
        except Exception:
            submit.click()
        logger.info("[wizard] SSF ID/PW 입력 + 로그인 클릭 완료")
        self._inject_input_done_banner(page, "ssf", "로그인 클릭됨 — 결과 대기")

    def _close_chatbots(self, page) -> None:
        """챗봇·해피톡 등 셀렉터 가리는 요소 자동 제거 — 송장전송기 sourcing_scrapers.py:1127."""
        try:
            page.evaluate("""
                document.querySelectorAll(
                    '[class*="chatbot"], [class*="happytalk"], [id*="chatbot"], '
                    + '[class*="channel-talk"], [id*="channelio"]'
                ).forEach(el => el.remove())
            """)
        except Exception:
            pass

    def _login_sns(self, page, source: str, sns_method: str,
                   user_id: str, user_pw: str) -> None:
        """SNS 로그인 분기 — 네이버/카카오/구글 (송장전송기 sourcing_scrapers.py:511 패턴).

        SNS 로그인 버튼 셀렉터는 사이트별로 다름 → 사용자 직접 클릭 권장 + 안내 배너.
        """
        import time
        SNS_BUTTON_SELECTORS = {
            "naver": 'button:has-text("네이버"), a:has-text("네이버"), [class*="naver"], a#naverLogin',
            "kakao": 'button:has-text("카카오"), a:has-text("카카오"), [class*="kakao"]',
            "google": 'button:has-text("Google"), a:has-text("Google"), [class*="google"]',
        }
        sel = SNS_BUTTON_SELECTORS.get(sns_method)
        if not sel:
            self._inject_manual_banner(page, source, f"SNS 메서드 미지원: {sns_method}")
            return

        try:
            sns_btn = page.locator(sel).first
            sns_btn.click(force=True, timeout=5000)
            time.sleep(2)
            # 네이버/카카오 로그인 페이지로 이동 → ID/PW 자동 입력 시도
            if sns_method == "naver":
                self._naver_fill(page, user_id, user_pw)
            elif sns_method == "kakao":
                self._kakao_fill(page, user_id, user_pw)
            self._inject_input_done_banner(page, source, f"{sns_method} 로그인 진행 중")
        except Exception as e:
            logger.warning("[wizard] %s SNS(%s) 로그인 실패 (%s) — 사용자 직접 처리",
                           source, sns_method, e)
            self._inject_manual_banner(page, source,
                                       f"{sns_method} 자동 클릭 실패 — 직접 로그인하세요")

    def _naver_fill(self, page, user_id: str, user_pw: str) -> None:
        """네이버 로그인 — 송장전송기 sourcing_scrapers.py:631."""
        import time
        try:
            page.wait_for_url("**nid.naver.com**", timeout=10000)
        except Exception:
            pass
        try:
            page.fill('#id', user_id)
            time.sleep(0.3)
            page.fill('#pw', user_pw)
            time.sleep(0.5)
            page.click('button[type="submit"]')
        except Exception as e:
            logger.warning("[wizard] 네이버 자동 입력 실패: %s", e)

    def _kakao_fill(self, page, user_id: str, user_pw: str) -> None:
        """카카오 로그인 (간단 폴백)."""
        import time
        try:
            page.wait_for_url("**accounts.kakao.com**", timeout=10000)
        except Exception:
            pass
        try:
            page.fill('input[name="loginId"], #loginId-loginKey', user_id)
            time.sleep(0.3)
            page.fill('input[name="password"], input[type="password"]', user_pw)
            time.sleep(0.5)
            page.click('button[type="submit"]')
        except Exception as e:
            logger.warning("[wizard] 카카오 자동 입력 실패: %s", e)

    def _login_lemouton(self, page, user_id: str, user_pw: str) -> None:
        """르무통 회원 로그인 — Cafe24 표준."""
        import time
        page.wait_for_selector('input[name="member_id"]', timeout=10000)
        id_input = page.locator('input[name="member_id"]')
        id_input.click()
        id_input.press_sequentially(user_id, delay=50)
        time.sleep(0.3)
        pw_input = page.locator('input[name="member_passwd"]')
        pw_input.click()
        pw_input.press_sequentially(user_pw, delay=30)
        time.sleep(0.5)
        page.click('button[type="submit"], a:has-text("로그인")')
        self._inject_input_done_banner(page, "lemouton", "로그인 클릭됨")

    def _inject_input_done_banner(self, page, source: str, note: str = "") -> None:
        """자동 입력 + 자동 클릭 완료 안내 (송장전송기 패턴 — 자동으로 다 누름)."""
        try:
            page.evaluate(f"""() => {{
                const old = document.getElementById('__lemouton_banner');
                if (old) old.remove();
                const div = document.createElement('div');
                div.id = '__lemouton_banner';
                div.style.cssText = 'position:fixed;top:0;left:0;right:0;background:#1AB053;color:white;padding:14px 20px;z-index:999999;font-family:system-ui;font-weight:700;text-align:center;box-shadow:0 4px 12px rgba(0,0,0,0.2)';
                div.innerHTML = '✅ {source} 자동 로그인 진행 중 — <span style="font-weight:400">{note or "캡차/2FA 뜨면 직접 처리"}. 로그인 성공 시 자동 감지 후 창 닫힘.</span>';
                document.body.appendChild(div);
            }}""")
        except Exception:
            pass

    def _inject_manual_banner(self, page, source: str, error: str) -> None:
        """자동 입력 실패 — 사용자 직접 입력 안내 배너."""
        try:
            page.evaluate(f"""() => {{
                const old = document.getElementById('__lemouton_banner');
                if (old) old.remove();
                const div = document.createElement('div');
                div.id = '__lemouton_banner';
                div.style.cssText = 'position:fixed;top:0;left:0;right:0;background:#F2994A;color:white;padding:14px 20px;z-index:999999;font-family:system-ui;font-weight:700;text-align:center;box-shadow:0 4px 12px rgba(0,0,0,0.2)';
                div.innerHTML = '⚠️ {source} 자동 입력 실패 — <span style="font-weight:400">ID/PW를 직접 입력 후 로그인 누르세요. 성공 시 자동 감지됩니다.</span>';
                document.body.appendChild(div);
            }}""")
        except Exception:
            pass

    def _wait_login_success(self, page, source: str, wait_sec: int) -> bool:
        """로그인 성공 신호 폴링 — URL이 로그인 페이지를 벗어나거나, 로그아웃 셀렉터 등장."""
        import time
        pattern = self._success_patterns().get(source, {"url_not_contains": ["/login"], "selectors": []})

        deadline = time.time() + wait_sec
        while time.time() < deadline:
            try:
                cur_url = page.url
                url_ok = not any(p in cur_url for p in pattern["url_not_contains"])
                sel_ok = False
                for s in pattern["selectors"]:
                    try:
                        if page.locator(s).count() > 0:
                            sel_ok = True
                            break
                    except Exception:
                        pass
                if url_ok or sel_ok:
                    return True
            except Exception:
                pass
            time.sleep(1.0)

        return False

    def _set_status(self, wizard_id: str, status: WizardStatus) -> None:
        result = self._wizards.get(wizard_id)
        if result is None:
            return
        result.status = status
        if self.on_stage_change is not None:
            try:
                self.on_stage_change(wizard_id, status)
            except Exception as e:
                logger.warning("[wizard] stage callback raised: %s", e)
