"""세션 사전 검증 — Chrome 부팅 전에 쿠키 유효성 빠르게 확인.

송장전송기 cookie_checker.py 패턴 — 만료된 세션을 미리 걸러서 불필요한 부팅 회피.

검증 방법:
  · user_data_dir/Default/Cookies SQLite 파일 존재 + 핵심 쿠키 존재 확인
  · OR 가벼운 HTTP HEAD 요청으로 로그인 상태 페이지 응답 검사 (선택)

호출 흐름:
  · login_wizard.execute() 가 _launch_browser_and_wait 전에 quick_check 호출
  · 쿠키 무효 → 그냥 부팅 (어차피 로그인 시도)
  · 쿠키 유효 → 부팅 후 빠른 already_logged_in 감지
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# 사이트별 핵심 쿠키 (있으면 로그인 상태) — 송장전송기 cookie_checker 매핑
# 2026-05 업데이트: 실제 디스크 쿠키 검사 결과 반영
# ※ 무신사 (2026-05-05): 마법사 직후 디스크 진단으로 확정된 로그인 토큰
#   - app_atk: auth token
#   - app_rtk: refresh token
#   - mss_last_login: 마지막 로그인 표시
#   기존 ["MMP","PCID","msr.session.id","_ga"] 는 부정확 — _ga 는 비로그인 시도 항상 존재 (false positive)
SOURCE_KEY_COOKIES = {
    "musinsa": ["app_atk", "app_rtk", "mss_last_login"],
    "ssf": ["MBRNO", "PC_JSESSIONID", "PCID", "e_mbr"],
    "ssg": ["JSESSIONID", "SSG_DI", "ssgDeviceId", "_ssg_session"],
    "abc": ["JSESSIONID", "ART_AUTH", "memberLoginId"],
    "abcGs": ["JSESSIONID", "ART_AUTH", "memberLoginId"],
    "grandstage": ["JSESSIONID", "ART_AUTH", "memberLoginId"],
    "gs": ["JSESSIONID", "WMONID", "GS_LOGIN"],
    "folder": ["PHPSESSID", "delivery_address_index", "skin_no"],
    "lotteimall": ["JSESSIONID", "LMC_TOKEN", "LM_LOGIN"],
    # 2026-05-05 디스크 진단: lotteon 의 실 로그인 토큰은 fo_ac_tkn/fo_sso_tkn/fo_mno (모두 session 만료)
    #   기존 ["JSESSIONID","LCKR_SESSION","LO_LOGIN"] 은 lotteon 도메인에 존재하지 않음 → 항상 false negative
    "lotteon": ["fo_ac_tkn", "fo_sso_tkn", "fo_mno"],
    "lemouton": ["JSESSIONID", "lemouton_session"],
}


def quick_check(profile_path: Path, source: str) -> dict:
    """프로필 디렉터리의 Cookies 파일 검사 — 빠른 사전 검증.

    Returns:
        {
            "exists": bool,         # Cookies 파일 존재
            "size_kb": float,
            "has_key_cookies": bool,  # 사이트별 핵심 쿠키 1개 이상 존재
            "matched_keys": list[str],  # 발견된 쿠키명
        }
    """
    profile_path = Path(profile_path)
    # Chrome 96+ : Default/Network/Cookies (신규 위치)
    # Chrome 95- : Default/Cookies (구 위치 — fallback)
    cookies_db_new = profile_path / "Default" / "Network" / "Cookies"
    cookies_db_old = profile_path / "Default" / "Cookies"
    cookies_db = cookies_db_new if cookies_db_new.exists() else cookies_db_old

    out = {
        "exists": False,
        "size_kb": 0.0,
        "has_key_cookies": False,
        "matched_keys": [],
    }

    if not cookies_db.exists():
        return out

    out["exists"] = True
    out["size_kb"] = round(cookies_db.stat().st_size / 1024, 1)

    if out["size_kb"] < 1.0:
        return out  # 너무 작음 — 빈 DB

    # SQLite 직접 쿼리 — 송장전송기 패턴
    expected = SOURCE_KEY_COOKIES.get(source, [])
    if not expected:
        return out

    try:
        # Chrome 이 잠금 잡고 있을 수 있어 read-only 모드 + URI 사용
        conn = sqlite3.connect(f"file:{cookies_db}?mode=ro", uri=True, timeout=2)
        cur = conn.cursor()
        # cookies 테이블 스키마: name, value, host_key, expires_utc 등
        placeholders = ",".join("?" * len(expected))
        cur.execute(
            f"SELECT name FROM cookies WHERE name IN ({placeholders})",
            expected,
        )
        rows = cur.fetchall()
        conn.close()
        matched = [r[0] for r in rows]
        out["matched_keys"] = matched
        out["has_key_cookies"] = bool(matched)
    except sqlite3.OperationalError as e:
        logger.debug("[cookie_checker] %s SQLite 잠김 (Chrome 사용 중일 수 있음): %s",
                     source, e)
    except Exception as e:
        logger.warning("[cookie_checker] %s 검증 실패: %s", source, e)

    return out


def is_likely_logged_in(profile_path: Path, source: str) -> bool:
    """간편 헬퍼 — 로그인 가능성 높음 판단."""
    result = quick_check(profile_path, source)
    return result["has_key_cookies"]
