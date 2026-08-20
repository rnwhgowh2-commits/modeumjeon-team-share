# -*- coding: utf-8 -*-
"""카카오 OAuth 토큰 수명 관리 — 액세스 토큰 자동 갱신.

**왜 이 모듈이 따로 있나**
    `shared/notifier.py` 의 KakaoChannel 은 `KAKAO_ACCESS_TOKEN` 환경변수를 그대로
    Bearer 로 썼다. 카카오 액세스 토큰은 **6시간**이면 만료되므로, 하루 1회 도는
    작업에서는 사실상 **항상 만료된 토큰**을 보내게 된다(= 401).
    갱신 토큰(refresh_token, 2개월)으로 액세스 토큰을 다시 받아오는 층이 필요하다.

**영구 유지되는 이유**
    갱신 토큰의 잔여 수명이 1개월 미만이면 카카오가 갱신 응답에 **새 refresh_token 을
    함께 내려준다**. 매일 도는 한 그 값을 계속 이어받으므로 재로그인이 필요 없다.
    2개월 넘게 한 번도 안 돌면 그때만 사장님이 다시 로그인해야 한다.

**저장 위치**
    `shared.state_store` 가 정하는 **배포를 견디는 폴더**의 `kakao_token.json`.
    라이브(AWS Lightsail)는 배포마다 컨테이너를 새로 만들기 때문에 앱 안 `data/` 에
    두면 **배포할 때마다 갱신 토큰이 사라져 재로그인**을 해야 한다.
    최초 1회 값은 환경변수 `KAKAO_REFRESH_TOKEN` 에서 읽어 파일로 승격시킨다.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_AUTH_HOST = "https://kauth.kakao.com"
_TOKEN_URL = f"{_AUTH_HOST}/oauth/token"
_AUTHORIZE_URL = f"{_AUTH_HOST}/oauth/authorize"

# 액세스 토큰을 만료 몇 초 전에 미리 갱신할지. 작업 도중 만료되는 일을 막는다.
_REFRESH_MARGIN_SEC = 600

# 테스트에서만 덮어쓴다. 평소엔 None → state_store 가 정하는 영속 경로.
_TOKEN_PATH: Optional[str] = None


def _token_path() -> str:
    if _TOKEN_PATH:
        return _TOKEN_PATH
    from shared.state_store import state_path

    return state_path("kakao_token.json")


# 같은 프로세스 안 동시 갱신 방지(스케줄러 스레드 + 요청 스레드가 겹칠 수 있다).
_lock = threading.Lock()


class KakaoTokenError(RuntimeError):
    """토큰 발급·갱신 실패. 호출자는 발송을 건너뛰고 로그만 남기면 된다."""


def _refresh_shared_env() -> None:
    """UI 로 저장한 키를 이 프로세스도 보게 한다.

    UI 저장은 .env 파일 + 저장을 처리한 워커 1개의 os.environ 만 갱신한다.
    스케줄러(마스터)와 나머지 워커는 읽기 직전 공유 .env 를 다시 로드해야 한다.
    """
    try:
        from lemouton.auth.secrets import refresh_env

        refresh_env()
    except Exception:   # noqa: BLE001 — 재로드 실패가 발송을 막지 않게
        logger.debug("shared .env 재로드 실패(무시)", exc_info=True)


def _rest_key() -> str:
    key = (os.environ.get("KAKAO_REST_KEY") or "").strip()
    if not key:
        _refresh_shared_env()
        key = (os.environ.get("KAKAO_REST_KEY") or "").strip()
    return key


def _client_secret() -> str:
    val = (os.environ.get("KAKAO_CLIENT_SECRET") or "").strip()
    if not val:
        _refresh_shared_env()
        val = (os.environ.get("KAKAO_CLIENT_SECRET") or "").strip()
    return val


def _redirect_uri() -> str:
    return (
        os.environ.get("KAKAO_REDIRECT_URI")
        or "https://mou-m.com/oauth/kakao"
    ).strip()


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ──────────────────────────────────────────────────────────────
# 저장소
# ──────────────────────────────────────────────────────────────
def _load() -> dict:
    """저장된 토큰 묶음. 파일이 없으면 환경변수의 갱신 토큰만 담아 반환."""
    try:
        with open(_token_path(), encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and data.get("refresh_token"):
            return data
    except FileNotFoundError:
        pass
    except Exception:  # noqa: BLE001 — 손상 파일이 발송을 영구 차단하지 않게
        logger.exception("kakao_token.json 읽기 실패 — 환경변수로 폴백")

    env_refresh = (os.environ.get("KAKAO_REFRESH_TOKEN") or "").strip()
    return {"refresh_token": env_refresh} if env_refresh else {}


def _save(data: dict) -> None:
    """원자적 교체로 저장. 쓰기 도중 죽어도 반쪽 파일이 남지 않는다."""
    path = _token_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


def _store_response(payload: dict, *, prev: Optional[dict] = None) -> dict:
    """카카오 토큰 응답을 저장 형식으로 바꿔 기록.

    갱신 응답에는 refresh_token 이 **없을 수도 있다**(잔여 1개월 이상). 그때는
    기존 갱신 토큰을 유지해야 한다 — 덮어쓰면 다음 갱신이 통째로 불가능해진다.
    """
    prev = prev or {}
    expires_in = int(payload.get("expires_in") or 0)
    data = {
        "access_token": payload.get("access_token") or "",
        "refresh_token": payload.get("refresh_token") or prev.get("refresh_token") or "",
        "expires_at": (_now() + timedelta(seconds=expires_in)).isoformat(),
        "updated_at": _now().isoformat(),
    }
    refresh_expires_in = payload.get("refresh_token_expires_in")
    if refresh_expires_in:
        data["refresh_expires_at"] = (
            _now() + timedelta(seconds=int(refresh_expires_in))
        ).isoformat()
    elif prev.get("refresh_expires_at"):
        data["refresh_expires_at"] = prev["refresh_expires_at"]
    _save(data)
    return data


# ──────────────────────────────────────────────────────────────
# 최초 1회 — 인가 코드 → 토큰
# ──────────────────────────────────────────────────────────────
def authorize_url() -> str:
    """사장님이 브라우저로 1번 열어야 하는 카카오 로그인 주소."""
    key = _rest_key()
    if not key:
        raise KakaoTokenError("KAKAO_REST_KEY 환경변수가 비어 있음")
    from urllib.parse import urlencode

    q = urlencode(
        {
            "client_id": key,
            "redirect_uri": _redirect_uri(),
            "response_type": "code",
            "scope": "talk_message",
        }
    )
    return f"{_AUTHORIZE_URL}?{q}"


def exchange_code(code: str) -> dict:
    """인가 코드를 액세스·갱신 토큰으로 교환하고 저장. 최초 1회만 쓴다."""
    key = _rest_key()
    if not key:
        raise KakaoTokenError("KAKAO_REST_KEY 환경변수가 비어 있음")
    body = {
        "grant_type": "authorization_code",
        "client_id": key,
        "redirect_uri": _redirect_uri(),
        "code": code,
    }
    if _client_secret():
        body["client_secret"] = _client_secret()
    resp = requests.post(_TOKEN_URL, data=body, timeout=10)
    if resp.status_code != 200:
        raise KakaoTokenError(f"인가 코드 교환 실패 {resp.status_code}: {resp.text[:200]}")
    payload = resp.json()
    if not payload.get("refresh_token"):
        raise KakaoTokenError("응답에 refresh_token 이 없음 — 동의항목 talk_message 확인 필요")
    with _lock:
        return _store_response(payload, prev=_load())


# ──────────────────────────────────────────────────────────────
# 상시 — 액세스 토큰 획득
# ──────────────────────────────────────────────────────────────
def _refresh(stored: dict) -> dict:
    key = _rest_key()
    if not key:
        raise KakaoTokenError("KAKAO_REST_KEY 환경변수가 비어 있음")
    refresh_token = (stored.get("refresh_token") or "").strip()
    if not refresh_token:
        raise KakaoTokenError("갱신 토큰 없음 — 최초 카카오 로그인이 아직 안 됨")
    body = {
        "grant_type": "refresh_token",
        "client_id": key,
        "refresh_token": refresh_token,
    }
    if _client_secret():
        body["client_secret"] = _client_secret()
    resp = requests.post(_TOKEN_URL, data=body, timeout=10)
    if resp.status_code != 200:
        raise KakaoTokenError(f"토큰 갱신 실패 {resp.status_code}: {resp.text[:200]}")
    return _store_response(resp.json(), prev=stored)


def get_access_token(*, force_refresh: bool = False) -> str:
    """유효한 액세스 토큰. 만료 임박이면 갱신해서 돌려준다.

    Raises:
        KakaoTokenError — 키 없음 / 최초 로그인 안 됨 / 갱신 실패
    """
    with _lock:
        stored = _load()
        if not force_refresh:
            token = stored.get("access_token")
            expires_at = stored.get("expires_at")
            if token and expires_at:
                try:
                    remain = datetime.fromisoformat(expires_at) - _now()
                    if remain.total_seconds() > _REFRESH_MARGIN_SEC:
                        return token
                except ValueError:
                    logger.warning("expires_at 파싱 실패 — 강제 갱신")
        return _refresh(stored).get("access_token") or ""


def status() -> dict:
    """설정 상태 요약. 화면에서 「무엇이 아직 안 됐는지」 보여주기 위한 것."""
    stored = _load()
    return {
        "rest_key_set": bool(_rest_key()),
        "client_secret_set": bool(_client_secret()),
        "refresh_token_set": bool(stored.get("refresh_token")),
        "access_token_cached": bool(stored.get("access_token")),
        "expires_at": stored.get("expires_at"),
        "refresh_expires_at": stored.get("refresh_expires_at"),
        "redirect_uri": _redirect_uri(),
    }
