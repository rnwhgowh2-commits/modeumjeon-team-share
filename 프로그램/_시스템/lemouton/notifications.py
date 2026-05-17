"""[E] T13 — 알림 라우팅 (vendored notifier 사용).

이벤트별 디스패치 함수. 채널 설정은 환경변수 / 알림 페이지에서 주입된 라우팅 사전에 따른다.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def _safe_dispatch(channel: str, text: str) -> None:
    """vendored notifier가 사용 가능하면 호출, 아니면 로그만."""
    try:
        from shared.notifier import dispatch  # vendored
        dispatch(channel=channel, text=text)
    except Exception:
        logger.exception('notifier dispatch failed (channel=%s)', channel)


def alert_dryrun_held(summary: str) -> None:
    _safe_dispatch('telegram', f'⚠ 사이클 보류 — {summary}')


def alert_api_failure(market: str, error: str, attempts: int) -> None:
    _safe_dispatch('telegram',
                   f'❌ {market} API 실패 ({attempts}회) — {error[:200]}')


def alert_guardrail_breach(canonical_sku: str, price: int,
                           lower: int, upper: int) -> None:
    _safe_dispatch('telegram',
                   f'🚨 가드레일 위반 — {canonical_sku} 가격 {price:,}원 '
                   f'(허용 {lower:,}~{upper:,}원)')


def alert_winner_change(canonical_sku: str, before: Optional[int],
                        after: Optional[int]) -> None:
    b = f'{before:,}원' if before else '—'
    a = f'{after:,}원' if after else '—'
    _safe_dispatch('telegram',
                   f'🏷 위너매칭 변경 — {canonical_sku}: {b} → {a}')


def alert_cycle_done(result: dict) -> None:
    """사이클 완료 요약. 실패한 phase가 있으면 강조."""
    failed = [
        name for name, p in (result.get('phases') or {}).items()
        if not p.get('ok', True)
    ]
    if failed:
        text = f'⚠ 사이클 부분 실패 — {", ".join(failed)} (자세한 건 DLQ 확인)'
    else:
        duration = result.get('duration_sec', 0)
        text = f'✅ 사이클 완료 — {duration:.0f}초'
    _safe_dispatch('telegram', text)
