"""소싱처 로그인 세션 관리 — Playwright storage_state 방식.

설계:
  · 사용자가 1회 수동 로그인 → ``data/auth/{source}_{account}.json`` 저장
  · 이후 크롤링은 storage_state 자동 로드해서 회원 권한으로 접근
  · 사용자 Chrome 프로필과 독립 (프로파일 충돌 없음)
  · 세션 만료 시 재로그인 필요 (manager 알림은 별도)

원본: 모음전 자동화 ``modules/sourcing/auth.py`` 의 sync_api 변형 — 본 프로젝트 파이프라인이
sync 이므로 sync 버전으로 단순화. 수동 로그인은 사용자 GUI 가 필요하므로 sync_playwright
컨텍스트 매니저 안에서 직접 대기 루프 실행.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from config import SOURCING_AUTH, DEFAULT_HEADERS


logger = logging.getLogger(__name__)


def get_state_path(source: str, account_name: str = "default") -> str:
    """소싱처+계정별 storage_state 파일 경로."""
    safe = f"{source}_{account_name}".replace(" ", "_").replace("/", "_")
    auth_dir = SOURCING_AUTH["auth_dir"]
    os.makedirs(auth_dir, exist_ok=True)
    return str(Path(auth_dir) / f"{safe}.json")


def has_state(source: str, account_name: str = "default") -> bool:
    return os.path.exists(get_state_path(source, account_name))


def state_age_days(source: str, account_name: str = "default") -> Optional[float]:
    path = get_state_path(source, account_name)
    if not os.path.exists(path):
        return None
    mtime = datetime.fromtimestamp(os.path.getmtime(path))
    return (datetime.now() - mtime).total_seconds() / 86400


def delete_state(source: str, account_name: str = "default") -> bool:
    path = get_state_path(source, account_name)
    if os.path.exists(path):
        os.remove(path)
        return True
    return False


def save_state_after_manual_login(
    source: str,
    account_name: str = "default",
    login_url: Optional[str] = None,
    headless: bool = False,
) -> bool:
    """수동 로그인 헬퍼 (sync).

    브라우저를 열고 사용자가 로그인할 때까지 대기 → 완료 감지 시 storage_state 저장.

    Returns:
        성공 여부
    """
    from playwright.sync_api import sync_playwright

    url = login_url or SOURCING_AUTH["login_urls"].get(source)
    if not url:
        logger.error("[%s] login_url 미정의 — config.SOURCING_AUTH['login_urls'] 확인", source)
        return False

    state_path = get_state_path(source, account_name)
    patterns = SOURCING_AUTH.get("login_path_patterns", ["/login", "/auth"])
    max_wait = int(SOURCING_AUTH.get("manual_login_wait_sec", 300))

    logger.info("[%s] 수동 로그인 시작 — URL: %s", source, url)
    print(f"\n브라우저 창에서 직접 로그인을 완료해주세요 (최대 {max_wait}초 대기)")
    print(f"로그인이 감지되면 자동으로 세션이 저장됩니다.\n")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        try:
            context = browser.new_context(
                user_agent=DEFAULT_HEADERS["User-Agent"],
                extra_http_headers={"Accept-Language": DEFAULT_HEADERS["Accept-Language"]},
            )
            page = context.new_page()
            page.goto(url, timeout=30000)

            # 로그인 완료 감지 — URL 에 로그인 경로 패턴이 모두 사라지면 완료
            detected = False
            for _ in range(max_wait):
                time.sleep(1)
                current = (page.url or "").lower()
                if not any(p in current for p in patterns):
                    detected = True
                    break

            if not detected:
                logger.warning("[%s] 로그인 감지 실패 (타임아웃)", source)
                return False

            # 안정화 (쿠키 세팅 완료 보장)
            page.wait_for_timeout(1500)

            context.storage_state(path=state_path)
        finally:
            browser.close()

    logger.info("[%s] 세션 저장 완료 → %s", source, state_path)
    print(f"\n✅ 세션 저장: {state_path}")
    return True


def new_context_with_state(playwright_instance, source: str, account_name: str = "default", browser=None):
    """저장된 세션으로 brower context 생성 (sync). 크롤러가 호출."""
    state_path = get_state_path(source, account_name)
    if not os.path.exists(state_path):
        raise FileNotFoundError(
            f"[{source}/{account_name}] 저장된 세션 없음. "
            f"먼저 save_state_after_manual_login() 으로 1회 로그인 필요. "
            f"expected path: {state_path}"
        )

    if browser is None:
        browser = playwright_instance.chromium.launch(headless=True)

    context = browser.new_context(
        storage_state=state_path,
        user_agent=DEFAULT_HEADERS["User-Agent"],
        extra_http_headers={"Accept-Language": DEFAULT_HEADERS["Accept-Language"]},
    )
    return browser, context
