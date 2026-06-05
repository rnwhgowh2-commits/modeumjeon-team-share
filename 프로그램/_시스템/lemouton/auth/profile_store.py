"""계정별 크롬 프로필 (Playwright user_data_dir) 관리 — 송장전송기 패턴 이식.

설계:
  · 각 (소싱처, 계정) 마다 독립 프로필 디렉터리
  · 위치: ``data/profiles/{source}_{account_key}/``
    (영문 키 사용 — Windows 한글 경로 인코딩 안전)
  · ``launch_persistent_context(user_data_dir=...)`` 한 번이면 쿠키 자동 저장
  · 한 번 로그인 후 계속 로그인 상태 유지 (브라우저가 재시작돼도)
  · 같은 프로필 사용 중인 Chrome 자동 종료 (SingletonLock 충돌 방지)

핵심 차이 (기존 storage_state.json 패턴 vs 이 패턴):
  · storage_state: 쿠키 + localStorage 만 JSON 저장, 매번 new_context 호출
  · persistent_context: Chrome 자체 프로필 디렉터리 → 쿠키 + 캐시 + IndexedDB + 모든 상태
    → "평생 재로그인 안 함" 효과 (송장전송기와 동일)
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _safe_key(value: str) -> str:
    """디렉터리명 안전 변환 — 한글/특수문자 제거, 영문/숫자/_/-만 허용."""
    if not value:
        return "default"
    # 영문/숫자/언더스코어/하이픈만 유지, 나머지는 _
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", value)
    return safe[:64] or "default"


# [2026-06-05] 송장자동화(sourcing_scrapers.py)와 100% 동일한 프로필 위치·네이밍.
#   사용자가 송장자동화로 이미 로그인해둔 프로필을 그대로 재사용 → 재로그인 불필요.
#   · 위치: %LOCALAPPDATA%/invoice_profiles/  (프로그램 밖 → 배포·재설치에도 영구)
#   · direct 로그인:  {site_name(한글)}_{safe(login_id)}      예) 무신사_rnwhgowh
#   · 외부(naver 등): {site_key}_{login_method}_{safe(login_id)}  예) ssg_naver_ditodalal
#   ※ account_key(영빈) 가 아니라 실제 login_id(rnwhgowh) 로 네이밍해야 매칭됨.
SITE_NAME_KR = {
    "musinsa": "무신사", "ssg": "SSG", "abc": "ABC마트", "grandstage": "그랜드스테이지",
    "gs": "GS샵", "folder": "폴더스타일", "ssf": "SSF샵", "lotteimall": "롯데아이몰",
    "lotteon": "롯데온", "nike": "나이키", "oliveyoung": "올리브영", "gmarket": "지마켓",
    "fashionplus": "패션플러스",
}


def invoice_profiles_root() -> Path:
    """송장자동화 프로필 루트 — %LOCALAPPDATA%/invoice_profiles/."""
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "invoice_profiles"


def _safe_id(login_id: str) -> str:
    """송장자동화 _profile_dir 와 동일 — [^\\w\\-] → _ (유니코드 word 유지)."""
    return re.sub(r"[^\w\-]", "_", login_id or "default")


def resolve_profile_dir(site_key: str, login_id: str,
                        login_method: str = "direct") -> Path:
    """송장자동화식 프로필 경로 (login_id·login_method 기반). 생성 안 함(경로만)."""
    sid = _safe_id(login_id)
    root = invoice_profiles_root()
    if login_method and login_method != "direct":
        return root / f"{site_key}_{login_method}_{sid}"
    return root / f"{SITE_NAME_KR.get(site_key, site_key)}_{sid}"


class ProfileStore:
    """계정별 user_data_dir 관리.

    Args:
        profiles_root: 프로필 루트 (기본: ``data/profiles/``)
    """

    def __init__(self, profiles_root: Path):
        self.profiles_root = Path(profiles_root)
        self.profiles_root.mkdir(parents=True, exist_ok=True)

    def profile_dir(self, source: str, account_key: str = "default") -> Path:
        """계정별 프로필 디렉터리 경로 — 없으면 생성."""
        safe_source = _safe_key(source)
        safe_key = _safe_key(account_key)
        path = self.profiles_root / f"{safe_source}_{safe_key}"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def has_profile(self, source: str, account_key: str = "default") -> bool:
        """프로필이 이미 존재하는지 (= 한 번이라도 로그인했는지)."""
        path = self.profile_dir(source, account_key)
        # Playwright/Chrome 이 만드는 핵심 파일 검사
        markers = ["Default", "Local State", "Cookies"]
        return any((path / m).exists() for m in markers)

    def list_profiles(self) -> list[dict]:
        """저장된 모든 프로필 목록 — UI 표시용."""
        out = []
        for d in self.profiles_root.iterdir():
            if not d.is_dir() or d.name.startswith("."):
                continue
            # 폴더명 파싱: {source}_{account_key}
            parts = d.name.split("_", 1)
            source = parts[0] if parts else d.name
            account_key = parts[1] if len(parts) > 1 else "default"

            # 마지막 사용 시각 = 폴더 mtime
            mtime = d.stat().st_mtime
            cookies_size = 0
            cookies_file = d / "Default" / "Cookies"
            if cookies_file.exists():
                cookies_size = cookies_file.stat().st_size

            out.append({
                "source": source,
                "account_key": account_key,
                "path": str(d),
                "last_used": mtime,
                "has_cookies": cookies_size > 0,
                "cookies_size_kb": round(cookies_size / 1024, 1),
            })
        return out

    def kill_chrome_using(self, profile_path: Path) -> None:
        """같은 프로필을 사용 중인 Chrome 강제 종료 — SingletonLock 충돌 방지.

        Windows: tasklist + wmic 로 찾아서 taskkill.
        실패해도 무시 (없을 수도 있음).
        """
        if os.name != "nt":
            return  # Linux/Mac 은 SingletonLock 만 제거하면 OK

        folder_name = profile_path.name
        try:
            # PowerShell 로 chrome.exe 중 user-data-dir 인자 매칭
            cmd = (
                "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
                "Where-Object { $_.CommandLine -like '*" + folder_name + "*' } | "
                "Select-Object -ExpandProperty ProcessId"
            )
            # CREATE_NO_WINDOW — powershell·taskkill cmd 창 깜빡임 방지
            _NO_WIN = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", cmd],
                capture_output=True, text=True, timeout=10,
                creationflags=_NO_WIN,
            )
            for pid_str in (result.stdout or "").splitlines():
                pid_str = pid_str.strip()
                if pid_str.isdigit():
                    pid = int(pid_str)
                    subprocess.run(
                        ["taskkill", "/F", "/PID", str(pid)],
                        capture_output=True, timeout=5,
                        creationflags=_NO_WIN,
                    )
                    logger.info("[profile_store] kill chrome PID %d (folder=%s)", pid, folder_name)
        except Exception as e:
            logger.debug("[profile_store] kill chrome 실패 (무시): %s", e)

    def cleanup_lock(self, profile_path: Path) -> None:
        """SingletonLock 파일 제거 — Chrome 비정상 종료 후 잔존 시."""
        for lock_name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
            lock = profile_path / lock_name
            if lock.exists():
                try:
                    lock.unlink()
                    logger.debug("[profile_store] removed %s", lock)
                except Exception:
                    pass

    def remove(self, source: str, account_key: str = "default") -> bool:
        """프로필 완전 삭제 (로그아웃 + 쿠키 모두 제거)."""
        path = self.profile_dir(source, account_key)
        self.kill_chrome_using(path)
        try:
            shutil.rmtree(path, ignore_errors=True)
            logger.info("[profile_store] removed %s/%s", source, account_key)
            return True
        except Exception as e:
            logger.warning("[profile_store] 삭제 실패: %s", e)
            return False


# 봇 탐지 우회 옵션 — 송장전송기와 동일 (sourcing_scrapers.py:353)
STEALTH_ARGS = [
    "--no-sandbox",
    "--disable-gpu",
    "--disable-gpu-sandbox",
    "--disable-dev-shm-usage",
    "--disable-blink-features=AutomationControlled",  # navigator.webdriver 숨김
    "--disable-infobars",
    "--disable-extensions",
    "--lang=ko-KR",
]

# 송장전송기 미니 창 (PC 사용 방해 최소화) — 우측 상단 500x150
MINI_WIDTH = 500
MINI_HEIGHT = 150


def get_mini_window_args() -> list[str]:
    """우측 상단 미니 창 위치·크기 — 송장전송기 sourcing_scrapers.py:103."""
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    try:
        screen_w = ctypes.windll.user32.GetSystemMetrics(0)
        screen_h = ctypes.windll.user32.GetSystemMetrics(1)
    except Exception:
        screen_w, screen_h = 1920, 1080
    x = max(screen_w - MINI_WIDTH, 0)
    y = 0
    return [f"--window-position={x},{y}", f"--window-size={MINI_WIDTH},{MINI_HEIGHT}"]


def set_window_bounds_cdp(page) -> None:
    """CDP 프로토콜로 창을 우측 상단 미니창으로 강제 — 송장전송기 sourcing_scrapers.py:134."""
    try:
        cdp = page.context.new_cdp_session(page)
        win_info = cdp.send("Browser.getWindowForTarget")
        window_id = win_info.get("windowId")
        if not window_id:
            return
        args = get_mini_window_args()
        pos = args[0].split("=")[1].split(",")
        size = args[1].split("=")[1].split(",")
        cdp.send("Browser.setWindowBounds", {
            "windowId": window_id,
            "bounds": {
                "windowState": "normal",
                "left": int(pos[0]),
                "top": int(pos[1]),
                "width": int(size[0]),
                "height": int(size[1]),
            }
        })
        cdp.detach()
    except Exception as e:
        logger.debug("[profile_store] CDP 창 크기 조정 실패 (무시): %s", e)


STEALTH_INIT_SCRIPT = """
    Object.defineProperty(navigator, 'webdriver', {get: () => false});
    Object.defineProperty(navigator, 'languages', {get: () => ['ko-KR', 'ko', 'en-US', 'en']});
    Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
"""


def default_store() -> ProfileStore:
    """기본 store — ``data/profiles/``."""
    project_root = Path(__file__).resolve().parents[2]
    return ProfileStore(project_root / "data" / "profiles")
