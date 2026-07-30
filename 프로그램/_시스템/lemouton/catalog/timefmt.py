# -*- coding: utf-8 -*-
"""시각을 화면에 내보낼 때 쓰는 한 곳.

★ [2026-07-24 라이브에서 발견한 사고] 시간대 표시 없이 `2026-07-24T10:45:25` 를 주면
  브라우저가 그걸 **자기 시간대(한국)** 로 읽는다. 우리는 UTC 로 저장하므로 9시간이
  어긋나, 방금 동기화한 것이 「11시간 전」으로 떴다.
  → 사장님이 최신 숫자를 낡았다고 오해한다. 「마지막 확인」이 신뢰의 근거인데 그게 거짓말이 된다.

  DB 컬럼이 시간대를 안 담는 타입이라 읽을 때 시간대가 떨어져 나온다. 그래서
  **내보낼 때 UTC 라고 명시**한다. 시각을 JSON 으로 내보내는 곳은 전부 이 함수를 쓴다.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional


def iso_utc(dt: Optional[datetime]) -> Optional[str]:
    """시각 → `2026-07-24T10:45:25+00:00`. 없으면 None.

    시간대가 안 붙어 있으면 UTC 로 본다(우리는 UTC 로만 저장한다).
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()
