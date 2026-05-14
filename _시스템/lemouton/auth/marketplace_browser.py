"""판매처 영구 로그인 브라우저 — detached subprocess 스폰 유틸.

Flask 요청은 즉시 응답하고, Playwright 브라우저는 별도 프로세스 트리에서
사용자가 창을 닫을 때까지 살아있게 한다.

송장전송기 패턴 / lemouton.auth.login_wizard 와 같은 user_data_dir 사용.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def _script_path() -> Path:
    project_root = Path(__file__).resolve().parents[2]
    return project_root / "scripts" / "open_marketplace_browser.py"


def spawn_native_chrome(*, profile_path, url: str) -> int:
    """Playwright 우회 — 일반 Chrome 으로 user_data_dir 띄우기.

    Naver 등이 Playwright/automation 환경을 봇으로 탐지해 로그인 거부할 때 우회.
    실제 사용자 브라우저로 인식되어 정상 로그인 → 쿠키 user_data_dir 에 영구 저장.
    그 후 ``spawn(...)`` (Playwright) 가 같은 user_data_dir 사용 시 자동 로그인 상태로 진입.
    """
    chrome_paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    chrome_exe = next((p for p in chrome_paths if os.path.exists(p)), None)
    if not chrome_exe:
        raise RuntimeError(
            "Chrome 설치 경로 못 찾음 — Google Chrome 설치 필요 (Edge/Brave 불가)"
        )

    cmd = [
        chrome_exe,
        f"--user-data-dir={profile_path}",
        "--no-first-run",
        "--no-default-browser-check",
        # Windows Hello / Credential Manager 통합 차단 → PIN 본인확인 프롬프트 안 뜸
        "--password-store=basic",
        "--disable-features="
        "BiometricAuthBeforeFilling,"
        "BiometricAuthIdentityCheck,"
        "WindowsHelloAuthForChrome,"
        "PasswordManagerOnboarding",
        url,
    ]
    creationflags = 0
    if os.name == "nt":
        # CREATE_NO_WINDOW — chrome.exe 는 GUI 앱이지만 일관성 + 자식 console 차단
        creationflags = (
            subprocess.DETACHED_PROCESS
            | subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.CREATE_NO_WINDOW
        )
    proc = subprocess.Popen(
        cmd,
        creationflags=creationflags,
        close_fds=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
    )
    logger.info("[marketplace_browser] native chrome spawn pid=%d url=%s", proc.pid, url)
    return proc.pid


def spawn(*, source: str, account_key: str, url: str,
          auto_click_first_product: bool = False) -> int:
    """Detached 프로세스로 Playwright 창 띄우기.

    Args:
        source: "smartstore" | "coupang" | ...
        account_key: env_prefix 권장 (e.g., "SMARTSTORE_MAIN") — 디렉터리 안전 키
        url: 이동할 URL
        auto_click_first_product: 페이지 로드 후 첫 상품 행 자동 클릭 (편집 페이지 직행용)

    Returns:
        스폰된 PID. 부팅 자체 실패 시 ``RuntimeError``.
    """
    script = _script_path()
    if not script.exists():
        raise RuntimeError(f"launcher 스크립트 없음: {script}")

    cmd = [
        sys.executable, str(script),
        "--source", source,
        "--account-key", account_key,
        "--url", url,
    ]
    if auto_click_first_product:
        cmd.append("--auto-click-first-product")

    creationflags = 0
    if os.name == "nt":
        # Windows: python.exe (콘솔 앱) 실행 시 cmd 창 깜빡임 방지
        # DETACHED + NEW_PROCESS_GROUP — Flask 종료해도 살아남음
        # CREATE_NO_WINDOW — python.exe 콘솔 창 차단 (★ cmd 창 깜빡임 핵심)
        creationflags = (
            subprocess.DETACHED_PROCESS
            | subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.CREATE_NO_WINDOW
        )

    proc = subprocess.Popen(
        cmd,
        creationflags=creationflags,
        close_fds=True,
        cwd=str(script.parent.parent),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
    )
    logger.info(
        "[marketplace_browser] spawn pid=%d source=%s account=%s url=%s",
        proc.pid, source, account_key, url,
    )
    return proc.pid
