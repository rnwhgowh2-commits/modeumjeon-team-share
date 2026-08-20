# -*- coding: utf-8 -*-
"""배포를 견디는 상태 파일 경로.

**왜 필요한가**
    라이브(AWS Lightsail)는 배포마다 앱 컨테이너를 통째로 새로 만든다. 컨테이너 안
    ``data/`` 에 쓴 파일은 **배포 즉시 사라진다**. 호스트에서 마운트되는 경로는
    ``/data/secrets`` (``-v /home/ubuntu/ui_secrets:/data/secrets``) 하나뿐이고,
    그 위치를 앱은 ``MOUM_SECRETS_ENV`` 로 알고 있다.

    여기에 안 두면 이런 일이 난다:
      · 카카오 갱신 토큰 소실 → 배포할 때마다 사장님이 다시 로그인
      · 어제 스냅샷 소실 → 배포한 날은 "첫 실행"으로 오인돼 그날 보고가 안 나감

    ``MOUM_STATE_DIR`` 로 강제 지정할 수 있고, 아무것도 없으면 로컬 ``data/`` 로
    떨어진다(개발 환경).
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_LOCAL_FALLBACK = Path(__file__).resolve().parent.parent / "data"


def state_dir() -> Path:
    """배포에도 살아남는 상태 폴더. 없으면 만든다."""
    explicit = os.environ.get("MOUM_STATE_DIR")
    if explicit:
        d = Path(explicit)
    else:
        secrets_env = os.environ.get("MOUM_SECRETS_ENV")
        # MOUM_SECRETS_ENV 는 파일 경로(.../.env) — 그 부모가 마운트된 폴더다.
        d = Path(secrets_env).parent if secrets_env else _LOCAL_FALLBACK
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        logger.exception("상태 폴더 생성 실패(%s) — 로컬 data/ 로 폴백", d)
        d = _LOCAL_FALLBACK
        d.mkdir(parents=True, exist_ok=True)
    return d


def state_path(filename: str) -> str:
    """상태 파일 하나의 전체 경로."""
    return str(state_dir() / filename)


def is_ephemeral() -> bool:
    """지금 쓰는 폴더가 배포 때 날아가는 자리인지.

    화면에 경고를 띄우기 위한 것 — 라이브에서 True 면 설정이 잘못된 것이다.
    """
    return not (os.environ.get("MOUM_STATE_DIR") or os.environ.get("MOUM_SECRETS_ENV"))
