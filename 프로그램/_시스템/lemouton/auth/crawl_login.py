# -*- coding: utf-8 -*-
"""크롤 자동로그인용 판매자센터 자격증명 — Fernet 암호화 저장/조회.

방식 A(완전자동, 사용자 결정 2026-07-16): 롯데온 등 판매자센터 아이디/비밀번호를 저장해
크롤러(확장)가 스스로 로그인 → 세션 Bearer 토큰 확보 → soapi 정산 수집(미정산 오차0).

보안 설계:
  · 비밀번호는 **평문 저장 금지** — Fernet 대칭 암호화 후 저장(자동로그인엔 복호화 필요하므로
    해시 아닌 가역 암호). 아이디는 민감도 낮아 평문.
  · 저장 단일출처 = 기존 시크릿 ``.env``(secrets.secrets_env_path()) — DB 이중저장 금지
    (secrets.py 설계원칙 유지). 형식:
        {env_prefix}_CRAWL_LOGIN_ID      = 평문 아이디
        {env_prefix}_CRAWL_LOGIN_PW_ENC  = Fernet 암호문
  · 암호화 키는 **시크릿 .env 와 분리된 별도 파일/환경변수**에 둔다. 시크릿 .env(암호문)만
    유출돼도 키가 없으면 비번 복원 불가 → 최소한의 at-rest 보호.
        키 우선순위: env ``MOUM_CRAWL_LOGIN_KEY`` > 키파일(``MOUM_CRAWL_LOGIN_KEY_FILE`` 또는
        시크릿 .env 폴더의 ``.crawl_login_key``). 둘 다 없으면 최초 1회 생성해 키파일에 저장(0600).

⚠️ 자동로그인 특성상 서버가 비번을 복호화해 확장에 전달하므로, 서버·키 동시 유출 시 비번도
   노출된다(방식 A 고지된 트레이드오프). 키를 호스트 환경변수로 옮기면 .env 백업 유출에는 안전.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet

from lemouton.auth import secrets as _S
from lemouton.auth.env_writer import update_env_keys

logger = logging.getLogger(__name__)

_ID_SUFFIX = "CRAWL_LOGIN_ID"
_PW_SUFFIX = "CRAWL_LOGIN_PW_ENC"

_fernet: Optional[Fernet] = None


def key_path() -> Path:
    """암호화 키 파일 경로 — 시크릿 .env 와 분리.

    ``MOUM_CRAWL_LOGIN_KEY_FILE`` 가 있으면 그 경로, 없으면 시크릿 .env 폴더의
    ``.crawl_login_key`` (파일은 .env 와 별개라 .env 유출만으론 키 미획득).
    """
    p = os.environ.get("MOUM_CRAWL_LOGIN_KEY_FILE")
    if p:
        return Path(p)
    return _S.secrets_env_path().parent / ".crawl_login_key"


def _load_key() -> bytes:
    """Fernet 키 로드(env > 키파일 > 최초 생성)."""
    env_key = os.environ.get("MOUM_CRAWL_LOGIN_KEY")
    if env_key:
        return env_key.encode() if isinstance(env_key, str) else env_key
    kp = key_path()
    if kp.exists():
        return kp.read_bytes().strip()
    # 최초 1회 생성 + 별도 파일 저장(권한 축소)
    key = Fernet.generate_key()
    kp.parent.mkdir(parents=True, exist_ok=True)
    kp.write_bytes(key)
    try:
        os.chmod(kp, 0o600)   # POSIX. Windows 에선 무시됨(예외 삼킴)
    except OSError:
        pass
    logger.warning(
        "crawl_login: 암호화 키가 없어 새로 생성해 %s 에 저장했습니다. 더 강한 at-rest "
        "보호를 원하면 이 키를 호스트 환경변수 MOUM_CRAWL_LOGIN_KEY 로 옮기세요.", kp)
    return key


def _f() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = Fernet(_load_key())
    return _fernet


def encrypt_pw(plain: str) -> str:
    """비밀번호 평문 → Fernet 암호문(str)."""
    return _f().encrypt((plain or "").encode("utf-8")).decode("ascii")


def decrypt_pw(token: str) -> str:
    """Fernet 암호문 → 비밀번호 평문."""
    if not token:
        return ""
    return _f().decrypt(token.encode("ascii")).decode("utf-8")


def save_login(env_prefix: str, login_id: str, password: str) -> None:
    """아이디(평문)+비밀번호(암호화)를 시크릿 .env 에 저장하고 os.environ 반영."""
    enc = encrypt_pw(password)
    update_env_keys(_S.secrets_env_path(), {
        f"{env_prefix}_{_ID_SUFFIX}": login_id,
        f"{env_prefix}_{_PW_SUFFIX}": enc,
    }, require_non_empty=True)
    _S.refresh_env()


def _get(env_prefix: str, suffix: str) -> Optional[str]:
    _S.refresh_env()
    return os.environ.get(f"{env_prefix}_{suffix}")


def login_status(env_prefix: str) -> dict:
    """저장 상태 — {saved, login_id}. saved = 아이디+암호문 둘 다 존재."""
    lid = _get(env_prefix, _ID_SUFFIX)
    enc = _get(env_prefix, _PW_SUFFIX)
    return {"saved": bool(lid and enc), "login_id": lid or None}


def get_password(env_prefix: str) -> Optional[str]:
    """저장된 비밀번호 복호화(확장 자동로그인 엔드포인트용). 없으면 None."""
    enc = _get(env_prefix, _PW_SUFFIX)
    if not enc:
        return None
    try:
        return decrypt_pw(enc)
    except Exception:   # noqa: BLE001 — 키 불일치/손상 시 복호 실패는 '없음'으로(추측 금지)
        logger.warning("crawl_login: %s 비밀번호 복호화 실패(키 불일치/손상)", env_prefix)
        return None
