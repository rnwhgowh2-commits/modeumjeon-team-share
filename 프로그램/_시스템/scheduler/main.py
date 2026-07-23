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


#  ESM(옥션·G마켓)은 주문조회가 **5초에 1회**라 한 바퀴가 다른 마켓보다 훨씬 느리다.
#  한 틱에 6마켓을 줄세우면 뒤 순번이 배포·재시작에 계속 잘려 굶는다
#  (2026-07-24 실측: 옥션 3일 공백 · G마켓 2일 공백. 2026-07-21 에도 같은 사고).
#  → 전용 틱으로 떼어내 다른 마켓과 순번 경쟁을 없앤다.
_ESM_INGEST = ('auction', 'gmarket')


def _order_ingest_tick(days: int) -> None:
    """주문 증분 수집 한 바퀴(**ESM 제외**). 실패한 마켓은 로그에 남기고 계속한다."""
    try:
        from lemouton.markets.backfill_runner import _reset_pool_once
        _reset_pool_once()      # fork 로 상속된 DB 커넥션 폐기(마스터 스레드)
    except Exception:           # noqa: BLE001
        pass
    try:
        from lemouton.markets.order_export import supported_markets
        from lemouton.markets.order_ingest import ingest_recent
        markets = [m for m in supported_markets() if m not in _ESM_INGEST]
        results = ingest_recent(markets, days=days)
    except Exception:                                   # noqa: BLE001
        logger.exception('order_ingest tick failed')
        return
    for r in results:
        logger.info('order_ingest[%s]: 신규 %d · 갱신 %d · 클레임 %d/%d · 키없음 %d · 실패창 %d',
                    r['market'], r['orders_new'], r['orders_updated'],
                    r['claims_new'], r['claims_updated'],
                    r['skipped_no_uid'], len(r['errors']))
        for e in r['errors'][:3]:
            logger.warning('order_ingest[%s] %s', r['market'], e)


def _order_ingest_tick_esm(days: int) -> None:
    """옥션·G마켓 전용 증분 수집 — 다른 마켓과 순번을 나눠 굶지 않게.

    ★ 부팅 직후(90초 뒤) 먼저 돈다. 배포가 잦은 날에도 ESM 이 맨 앞이라
      다른 마켓 뒤에서 잘리지 않는다. 겹침은 max_instances=1 이 막는다.
    """
    try:
        from lemouton.markets.backfill_runner import _reset_pool_once
        _reset_pool_once()
    except Exception:           # noqa: BLE001
        pass
    try:
        from lemouton.markets.order_export import supported_markets
        from lemouton.markets.order_ingest import ingest_recent
        markets = [m for m in supported_markets() if m in _ESM_INGEST]
        if not markets:
            return
        results = ingest_recent(markets, days=days)
    except Exception:                                   # noqa: BLE001
        logger.exception('order_ingest esm tick failed')
        return
    for r in results:
        logger.info('order_ingest_esm[%s]: 신규 %d · 갱신 %d · 클레임 %d/%d · 실패창 %d',
                    r['market'], r['orders_new'], r['orders_updated'],
                    r['claims_new'], r['claims_updated'], len(r['errors']))
        for e in r['errors'][:3]:
            logger.warning('order_ingest_esm[%s] %s', r['market'], e)


def _order_ingest_tick_fast() -> None:
    """고속 증분 수집 — 취소요청 단계에서 낚아채기(2026-07-22 사장님 확정 방향).

    취소요청까지는 마켓 API 가 구매자·주소·실결제를 전부 준다(라이브 실측 2/2).
    취소완료되면 사라진다 — 요청→완료가 6시간 틱 사이에 끝나는 초고속 취소가
    공란 17건의 원인이었다. 1일 창·비ESM 만이라 한 바퀴가 가볍다.
    ESM(옥션·G마켓)은 5초/1콜 제한이라 제외 — 취소 금액은 정산 실값으로 복원된다.
    """
    try:
        from lemouton.markets.order_export import supported_markets
        from lemouton.markets.order_ingest import ingest_recent
        markets = [m for m in supported_markets() if m not in ("auction", "gmarket")]
        if not markets:
            return
        results = ingest_recent(markets, days=1)
    except Exception:                                   # noqa: BLE001
        logger.exception('order_ingest fast tick failed')
        return
    for r in results:
        if r.get('orders_new') or r.get('claims_new') or r.get('errors'):
            logger.info('order_ingest_fast[%s]: 신규 %d · 클레임신규 %d · 실패창 %d',
                        r['market'], r['orders_new'], r['claims_new'],
                        len(r['errors']))
    # 초고속 취소 복구 — 주문→취소완료가 틱 사이에 끝나면 주문 라인 스냅샷이 없어
    # 주문일이 비고 주문일 탭에서 통째 빠진다(2026-07-23 실측 5건) → by-no 단건 복구.
    try:
        from lemouton.markets.order_ingest import restore_eleven11_claim_gaps
        st = restore_eleven11_claim_gaps()
        if st.get('targets'):
            logger.info('order_ingest_fast[eleven11]: 초고속취소 복구 %s', st)
    except Exception:                                   # noqa: BLE001
        logger.exception('eleven11 claim-gap restore failed')
    # 낡은 정산 스냅샷 갱신 — 배송 후에도 11번가가 stlPlnAmt 를 갱신(T-쿠폰 등)하는데
    # 배송완료·구매확정 목록은 stlPlnAmt 미제공이라 저장분이 낡으면 그대로 틀린다
    # (샵마인 대조 실측 ±610~1,347원) → 오래 안 본 순 8건/틱 단건 재조회.
    try:
        from lemouton.markets.order_ingest import refresh_eleven11_stale_settles
        st = refresh_eleven11_stale_settles()
        if st.get('targets'):
            logger.info('order_ingest_fast[eleven11]: 정산 스냅샷 갱신 %s', st)
    except Exception:                                   # noqa: BLE001
        logger.exception('eleven11 stale-settle refresh failed')
    # 상품명·단가 공란 채움 — 11번가 배송중 목록은 송장·주문번호만 준다(상품명·단가·
    # 정산 없음). 결제완료 스냅샷이 없던 주문은 통째로 빈 채 남아, 마진계산기에서
    # 판매가 0·마진율 0.0% 로 보인다(2026-07-24 실측 2건) → 주문번호 단건조회로 채운다.
    #  롯데온도 같은 병 — 정산 API 백필로만 들어온 라인은 상품명·단가·주문상태까지
    #  통째로 비어 있다(저장분 187건). 209 는 odNo 단건 조회를 받는다.
    #  계정이 많아(롯데온 다계정) 한 틱 상한을 11번가보다 낮게 잡는다.
    for _mk, _lim in (('eleven11', 8), ('lotteon', 4)):
        try:
            from lemouton.markets.order_ingest import restore_blank_orders
            st = restore_blank_orders(_mk, limit=_lim)
            if st.get('targets'):
                logger.info('order_ingest_fast[%s]: 공란 채움 %s', _mk, st)
        except Exception:                               # noqa: BLE001
            logger.exception('%s blank-order fill failed', _mk)


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


def start_order_ingest_scheduler() -> BackgroundScheduler:
    """주문 수집(증분) + 백필 처리 등록·기동.

    ★ create_app() 에서 부른다. start_scheduler() 는 `__main__` 블록(개발 실행) 에서만
    불려서, 거기에 등록하면 **프로덕션(gunicorn)에서는 아예 돌지 않는다**
    (2026-07-20에 그렇게 만들어 놓고 못 돌고 있었다).

    ★ 이 스케줄러 스레드는 gunicorn --preload 마스터에서 돈다. 요청을 처리하지 않는
    프로세스라 60초 요청 타임아웃·워커 재활용에 죽지 않는다 — 긴 작업이 있을 곳이다.
    """
    sched = get_scheduler()
    try:
        ingest_hours = int(os.environ.get('MOUM_ORDER_INGEST_HOURS', '6'))
        ingest_days = int(os.environ.get('MOUM_ORDER_INGEST_DAYS', '7'))
    except ValueError:
        ingest_hours, ingest_days = 6, 7
    if ingest_hours > 0 and sched.get_job('order_ingest') is None:
        import datetime as _dtm
        sched.add_job(lambda: _order_ingest_tick(ingest_days), 'interval',
                      hours=ingest_hours, id='order_ingest', max_instances=1,
                      coalesce=True, misfire_grace_time=60 * 30,
                      # ★ 첫 실행 = 부팅 3분 뒤. interval 기본(부팅+6시간)으로 두면
                      #   배포가 잦은 날 매 배포가 타이머를 리셋해 증분이 거의 안 돈다
                      #   (2026-07-21 실측: 옥션 8일 공백·G마켓 최근 12건 누락).
                      next_run_time=_dtm.datetime.now() + _dtm.timedelta(minutes=3))
        logger.info('scheduler: order_ingest job every %dh (recent %dd, 첫 실행 3분 뒤, ESM 제외)',
                    ingest_hours, ingest_days)
    # ESM 전용 틱 — 옥션·G마켓만. 다른 마켓보다 **먼저**(부팅 90초 뒤) 돌아
    #  배포가 잦아도 뒤에서 잘리지 않는다. 0 이면 끔.
    try:
        esm_hours = int(os.environ.get('MOUM_ORDER_INGEST_ESM_HOURS', '3'))
        esm_days = int(os.environ.get('MOUM_ORDER_INGEST_ESM_DAYS', '3'))
    except ValueError:
        esm_hours, esm_days = 3, 3
    if esm_hours > 0 and sched.get_job('order_ingest_esm') is None:
        import datetime as _dtm3
        sched.add_job(lambda: _order_ingest_tick_esm(esm_days), 'interval',
                      hours=esm_hours, id='order_ingest_esm', max_instances=1,
                      coalesce=True, misfire_grace_time=60 * 30,
                      next_run_time=_dtm3.datetime.now() + _dtm3.timedelta(seconds=90))
        logger.info('scheduler: order_ingest_esm job every %dh (recent %dd, 첫 실행 90초 뒤)',
                    esm_hours, esm_days)
    # 고속 틱 — 취소요청 단계 포착용(1일 창·비ESM). 0 이면 끔.
    try:
        fast_min = int(os.environ.get('MOUM_ORDER_INGEST_FAST_MINUTES', '20'))
    except ValueError:
        fast_min = 20
    if fast_min > 0 and sched.get_job('order_ingest_fast') is None:
        import datetime as _dtm2
        sched.add_job(_order_ingest_tick_fast, 'interval',
                      minutes=fast_min, id='order_ingest_fast', max_instances=1,
                      coalesce=True, misfire_grace_time=60 * 10,
                      next_run_time=_dtm2.datetime.now() + _dtm2.timedelta(minutes=6))
        logger.info('scheduler: order_ingest_fast job every %dmin (recent 1d, 비ESM)',
                    fast_min)
    # 🔴 백필 틱은 마스터 스케줄러에서 끈다(2026-07-20). gunicorn --preload fork
    #  환경에서 마스터의 Supabase 연결이 몇 창 돌다 굳었다(done 이 5 에서 안 움직임).
    #  워커 경로(/api/orders-ingest/step)는 안정적이라 백필은 그쪽으로 민다.
    #  MOUM_BACKFILL_MASTER_TICK=1 이면 예전 방식으로 되살릴 수 있다(폴백).
    if (os.environ.get('MOUM_BACKFILL_MASTER_TICK') == '1'
            and sched.get_job('order_backfill') is None):
        sched.add_job(_order_backfill_tick, 'interval', minutes=1,
                      id='order_backfill', max_instances=1, coalesce=True,
                      misfire_grace_time=300)
        logger.info('scheduler: order_backfill watcher every 1min (레거시)')
    if not sched.running:
        sched.start()
    return sched


def _order_backfill_tick() -> None:
    """백필 요청이 있으면 실행. 없으면 즉시 no-op."""
    try:
        from lemouton.markets import backfill_runner
        backfill_runner.run_if_requested()
    except Exception:                                   # noqa: BLE001
        logger.exception('order_backfill tick failed')


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
