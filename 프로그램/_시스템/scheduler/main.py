"""[E] T11 — APScheduler 부트스트랩.

Flask 프로세스 안에서 BackgroundScheduler를 띄운다 (단일 사용자 로컬 운영).

연속 모드 (MOUM_CYCLE_MODE=continuous, default):
    이전 사이클이 끝나면 ``MOUM_CONTINUOUS_GAP_SEC`` (default 60s) 대기 후
    다음 사이클 자동 reschedule. 사이트 부하 보호 위한 최소 간격만 둠.

레거시 인터벌 모드 (MOUM_CYCLE_MODE=interval):
    ``MOUM_CYCLE_HOURS`` (default 6) 간격으로 정시 실행.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler

from scheduler.jobs import full_cycle
from scheduler.sets_collect import collect_and_snapshot_all

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

    사이클 사이 최소 ``MOUM_CONTINUOUS_GAP_SEC`` 초 간격 보장 (사이트 부하 보호).
    """
    try:
        return full_cycle(dry_run=dry_run)
    finally:
        try:
            sched = get_scheduler()
            gap_sec = int(os.environ.get('MOUM_CONTINUOUS_GAP_SEC', '60'))
            next_at = datetime.now(timezone.utc) + timedelta(seconds=gap_sec)
            sched.reschedule_job('full_cycle', trigger='date', run_date=next_at)
        except Exception:
            logger.exception('continuous reschedule failed')


def start_scheduler() -> BackgroundScheduler:
    """앱 부팅 시 호출. 모드에 따라 full_cycle job 등록 후 시작.

    - continuous (default): 사이클 종료 후 60초 후 즉시 다음 — 무제한 연속
    - interval (legacy): MOUM_CYCLE_HOURS 간격
    """
    sched = get_scheduler()
    if sched.running:
        return sched

    mode = (os.environ.get('MOUM_CYCLE_MODE') or 'continuous').lower()
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
        gap_sec = int(os.environ.get('MOUM_CONTINUOUS_GAP_SEC', '60'))
        logger.info('scheduler started — continuous mode (gap %ds between cycles)', gap_sec)
    else:
        interval_hours = int(os.environ.get('MOUM_CYCLE_HOURS', '6'))
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

    # 연동 구성 주기 수집(판매처 현재값 + 소싱 변동 스냅샷). env 가드(0=비활성, 기본 12h).
    # collect 는 마켓 read-only(쓰기 0). 운영 부하는 MOUM_SETS_COLLECT_HOURS 로 통제.
    try:
        sets_hours = int(os.environ.get('MOUM_SETS_COLLECT_HOURS', '12'))
    except ValueError:
        sets_hours = 12
    if sets_hours > 0 and sched.get_job('sets_collect') is None:
        sched.add_job(
            collect_and_snapshot_all,
            'interval',
            hours=sets_hours,
            id='sets_collect',
            max_instances=1,
            coalesce=True,
            misfire_grace_time=60 * 30,
        )
        logger.info('scheduler: sets_collect job every %dh', sets_hours)
    return sched


def _auto_confirm_tick():
    """자동전환 스케줄러 틱 — 자동 실행 켜져 있고 간격 지났으면 한 바퀴."""
    try:
        from shared.db import SessionLocal
        from lemouton.orders import auto_confirm as ac
        s = SessionLocal()
        try:
            ac.tick(s)
        finally:
            s.close()
    except Exception:   # noqa: BLE001 — 틱 실패가 스케줄러를 죽이지 않게
        logger.exception("auto-confirm tick failed")


def start_auto_confirm_scheduler() -> BackgroundScheduler:
    """자동전환 틱(1분) 등록·기동. ★서버크롤 스케줄러(DISABLE_SCHEDULER)와 무관하게 항상.

    발주확인은 마켓 API(크롤 부하와 별개)라 크롤 차단과 독립적으로 돌아야 한다.
    자동 실행 OFF 면 틱이 곧바로 no-op 이라 부하 없음.
    """
    sched = get_scheduler()
    if sched.get_job('auto_confirm_tick') is None:
        sched.add_job(_auto_confirm_tick, 'interval', minutes=1,
                      id='auto_confirm_tick', max_instances=1, coalesce=True,
                      misfire_grace_time=120)
        logger.info('scheduler: auto_confirm_tick job every 1min')
    if not sched.running:
        sched.start()
    return sched


def auto_confirm_job_info() -> dict:
    """자동전환 틱 잡 상태(운영 확인용) — 스케줄러가 실제로 도는지."""
    try:
        sched = get_scheduler()
        job = sched.get_job('auto_confirm_tick') if sched else None
        return {"scheduler_running": bool(sched and sched.running),
                "tick_registered": job is not None,
                "tick_next": job.next_run_time.isoformat()
                             if (job and job.next_run_time) else None}
    except Exception:   # noqa: BLE001
        return {"scheduler_running": False, "tick_registered": False, "tick_next": None}


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
