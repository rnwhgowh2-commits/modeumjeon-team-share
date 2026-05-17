"""[E] T11 — APScheduler 부트스트랩.

Flask 프로세스 안에서 BackgroundScheduler를 띄운다 (단일 사용자 로컬 운영).

연속 모드 (LEMOUTON_CYCLE_MODE=continuous, default):
    이전 사이클이 끝나면 ``LEMOUTON_CONTINUOUS_GAP_SEC`` (default 60s) 대기 후
    다음 사이클 자동 reschedule. 사이트 부하 보호 위한 최소 간격만 둠.

레거시 인터벌 모드 (LEMOUTON_CYCLE_MODE=interval):
    ``LEMOUTON_CYCLE_HOURS`` (default 6) 간격으로 정시 실행.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler

from scheduler.jobs import full_cycle

logger = logging.getLogger(__name__)

_scheduler: Optional[BackgroundScheduler] = None


def get_scheduler() -> BackgroundScheduler:
    """싱글턴 BackgroundScheduler 반환. 없으면 생성."""
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler(daemon=True, timezone='Asia/Seoul')
    return _scheduler


def _continuous_full_cycle(*, dry_run: bool = False) -> dict:
    """full_cycle 1회 실행 후 다음 실행을 즉시 reschedule (연속 모드).

    사이클 사이 최소 ``LEMOUTON_CONTINUOUS_GAP_SEC`` 초 간격 보장 (사이트 부하 보호).
    """
    try:
        return full_cycle(dry_run=dry_run)
    finally:
        try:
            sched = get_scheduler()
            gap_sec = int(os.environ.get('LEMOUTON_CONTINUOUS_GAP_SEC', '60'))
            next_at = datetime.now(timezone.utc) + timedelta(seconds=gap_sec)
            sched.reschedule_job('full_cycle', trigger='date', run_date=next_at)
        except Exception:
            logger.exception('continuous reschedule failed')


def start_scheduler() -> BackgroundScheduler:
    """앱 부팅 시 호출. 모드에 따라 full_cycle job 등록 후 시작.

    - continuous (default): 사이클 종료 후 60초 후 즉시 다음 — 무제한 연속
    - interval (legacy): LEMOUTON_CYCLE_HOURS 간격
    """
    sched = get_scheduler()
    if sched.running:
        return sched

    mode = (os.environ.get('LEMOUTON_CYCLE_MODE') or 'continuous').lower()
    if mode == 'continuous':
        sched.add_job(
            _continuous_full_cycle,
            'date',
            run_date=datetime.now(timezone.utc),
            id='full_cycle',
            max_instances=1,
            coalesce=True,
            misfire_grace_time=60 * 30,
        )
        sched.start()
        gap_sec = int(os.environ.get('LEMOUTON_CONTINUOUS_GAP_SEC', '60'))
        logger.info('scheduler started — continuous mode (gap %ds between cycles)', gap_sec)
    else:
        interval_hours = int(os.environ.get('LEMOUTON_CYCLE_HOURS', '6'))
        sched.add_job(
            full_cycle,
            'interval',
            hours=interval_hours,
            id='full_cycle',
            max_instances=1,
            coalesce=True,
            misfire_grace_time=60 * 30,
            next_run_time=datetime.now(timezone.utc),
        )
        sched.start()
        logger.info('scheduler started — interval mode (every %dh)', interval_hours)
    return sched


def shutdown_scheduler():
    sched = get_scheduler()
    if sched.running:
        sched.shutdown(wait=False)


def get_next_run_info() -> dict:
    sched = get_scheduler()
    job = sched.get_job('full_cycle') if sched else None
    if job is None or job.next_run_time is None:
        return {'next_at': None, 'countdown': None}
    next_at = job.next_run_time
    countdown = (next_at - datetime.now(next_at.tzinfo)).total_seconds()
    return {'next_at': next_at.isoformat(), 'countdown_sec': max(0, int(countdown))}
