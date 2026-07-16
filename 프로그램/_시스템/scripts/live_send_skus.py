# -*- coding: utf-8 -*-
"""스코프 원샷 실전송 도구 — 지정 SKU만 1회 전송(연속 스케줄러와 분리).

실전송 조건(3중): --live + --i-understand-live-send + 서버키 MOUM_LIVE_UPLOAD ON.
기본 드라이런. price_guard·DLQ·정직한 성공판정은 run_uploader 재사용으로 보존.
"""
from __future__ import annotations


def resolve_send_mode(*, want_live: bool, confirmed: bool, server_key_on: bool):
    """(use_real: bool, refusal_reason: str|None). real 은 3조건 모두 참일 때만."""
    if not want_live:
        return False, None
    if not confirmed:
        return False, "실전송하려면 --i-understand-live-send 확인 플래그가 필요합니다(드라이런으로 실행)."
    if not server_key_on:
        return False, "서버키 MOUM_LIVE_UPLOAD 가 꺼져 있습니다. 배포 env 설정·재배포(사용자) 후 재시도(드라이런으로 실행)."
    return True, None
