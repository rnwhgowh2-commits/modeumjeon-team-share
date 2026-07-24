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

    # 상품관리 — 마켓 상품 머리글 야간 훑기(약 28만 건 · 2,700 호출 · 30~60분).
    # env 로 켠다: MOUM_CATALOG_SYNC_HOUR=3 → 매일 새벽 3시.
    _cat_hour = _catalog_sync_hour()
    if _cat_hour is not None and sched.get_job('catalog_sync') is None:
        from lemouton.catalog.sync import sync_all as _catalog_sync_all
        sched.add_job(
            _catalog_sync_all,
            'cron',
            hour=_cat_hour,
            minute=0,
            id='catalog_sync',
            max_instances=1,
            coalesce=True,
            misfire_grace_time=60 * 60,
        )
        logger.info('scheduler: catalog_sync job every day at %02d:00', _cat_hour)

    return sched


def _catalog_sync_hour():
    """야간 상품 훑기 시각(0~23). 안 켜면 None.

    ★ 기본 꺼짐 — 켜는 순간 6마켓 36계정에 약 2,700 호출이 나간다(30~60분).
      마켓 호출 한도가 있으므로 사장님이 명시적으로 켤 때만 돈다.
    ★ 0 을 '꺼짐'으로 읽으면 자정 동기화가 조용히 안 돈다 — None 과 0 을 구분한다.
    """
    raw = (os.environ.get('MOUM_CATALOG_SYNC_HOUR') or '').strip()
    if not raw:
        return None
    try:
        h = int(raw)
    except ValueError:
        return None
    return h if 0 <= h <= 23 else None


#  ESM(옥션·G마켓)은 주문조회가 **5초에 1회**라 한 바퀴가 다른 마켓보다 훨씬 느리다.
#  한 틱에 6마켓을 줄세우면 뒤 순번이 배포·재시작에 계속 잘려 굶는다
#  (2026-07-24 실측: 옥션 3일 공백 · G마켓 2일 공백. 2026-07-21 에도 같은 사고).
#  → 전용 틱으로 떼어내 다른 마켓과 순번 경쟁을 없앤다.
_ESM_INGEST = ('auction', 'gmarket')

#  ── 최신화 창 = 3주 (2026-07-24 사장님 기준) ────────────────────────────
#  보통 3주 안에 구매확정·클레임으로 바뀐다 → 최근 21일의 **주문상태·송장번호**가
#  늘 최신이어야 분석(매출·마진)이 맞는다.
#  ★ 넓히는 값이 마켓마다 다르다 — 한 번에 물어볼 수 있는 기간이 달라서다.
#    쿠팡 30일 · G마켓 30일 · 옥션 180일 → 21일이 **한 창**에 들어간다(호출 그대로).
#    11번가 7일 → 3창.
#    스마트스토어·롯데온은 **1일**이라 21창이 된다 → 여기 넣지 않고,
#    '아직 안 끝난 주문이 있는 날짜만' 다시 보는 별도 틱으로 같은 최신성을
#    훨씬 적은 호출로 얻는다(_order_ingest_tick_open).
_WIDE_DAYS = 21
_WIDE_MARKETS = ('coupang', 'eleven11', 'auction', 'gmarket')
_OPEN_MARKETS = ('smartstore', 'lotteon')      # 1일 창 마켓 — 미확정 날짜만 재확인


def _order_ingest_tick(days: int) -> None:
    """주문 증분 수집 한 바퀴(**ESM 제외**). 실패한 마켓은 로그에 남기고 계속한다.

    쿠팡·11번가는 21일 창이 싸므로 넓게, 스스·롯데온은 기존 days 그대로 돈다.
    """
    try:
        from lemouton.markets.backfill_runner import _reset_pool_once
        _reset_pool_once()      # fork 로 상속된 DB 커넥션 폐기(마스터 스레드)
    except Exception:           # noqa: BLE001
        pass
    try:
        from lemouton.markets.order_export import supported_markets
        from lemouton.markets.order_ingest import ingest_recent
        markets = [m for m in supported_markets() if m not in _ESM_INGEST]
        wide = [m for m in markets if m in _WIDE_MARKETS]
        narrow = [m for m in markets if m not in _WIDE_MARKETS]
        results = []
        if wide:
            results += ingest_recent(wide, days=_WIDE_DAYS)
        if narrow:
            results += ingest_recent(narrow, days=days)
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


def _order_settle_sweep_tick() -> None:
    """옥션·G마켓 **정산만** 다시 훑는다 — 주문 조회 없음.

    🔴 왜 따로 도는가 — 정산은 **구매확정 뒤에** 확정되는데 주문 증분은 최근 21일만 본다.
      G마켓 실측(2026-07-25): 07-01 주문의 마지막 관측이 07-21(그땐 미정산), 창이 닫힌 뒤
      마켓에 실정산 69,530 이 들어왔지만 우리 저장분은 추정치로 고착(같은 지문 43건).

    ★ 주문 수집 틱(3시간)에 얹지 않고 **자주 돈다**. 한 바퀴가 가볍기 때문이다:
      · 정산조회는 한 번에 31일 → 60일이면 창 2개
      · 계정 3 × 마켓 2 × 창 2 = 약 12콜, 몇 초
      · **옥션·G마켓 5초/1콜 제한은 「주문조회」 전용**(RequestOrders·PreRequestOrders)이라
        정산조회는 그 버킷을 안 쓴다 → 주문 화면 조회를 느리게 만들지 않는다
      정산 자체는 하루 단위로 확정되므로 이보다 더 줄여도 얻는 게 없다.
    """
    try:
        from lemouton.markets.order_export import supported_markets
        from lemouton.markets.order_ingest import refresh_settlement
        sup = supported_markets()
        for m in _ESM_INGEST:
            if m not in sup:
                continue
            st = refresh_settlement(m)
            if st['updated'] or st['errors']:
                logger.info('order_settle_sweep[%s]: 계정 %d · 정산 %d건 → 갱신 %d · 실패 %d',
                            m, st['accounts'], st['settle_rows'], st['updated'],
                            len(st['errors']))
            for e in st['errors'][:3]:
                logger.warning('order_settle_sweep[%s] %s', m, e)
    except Exception:                                   # noqa: BLE001
        logger.exception('order settle sweep failed')


def _order_ingest_tick_open(limit: int) -> None:
    """스마트스토어·롯데온 — **아직 안 끝난 주문이 있는 날짜만** 다시 조회.

    이 둘은 하루씩만 조회할 수 있어(마켓 제한) 3주를 통째로 훑으면 창이 21개다.
    끝난 주문(구매확정·취소완료·반품완료…)은 값이 더 안 바뀌므로 건너뛰고,
    안 끝난 건이 남은 날짜만 골라 그 하루를 다시 본다.
    한 틱에 limit 일까지 — 오래 안 본 날짜부터라 다음 틱이 나머지를 이어받는다.
    """
    try:
        from lemouton.markets.backfill_runner import _reset_pool_once
        _reset_pool_once()
    except Exception:           # noqa: BLE001
        pass
    try:
        from lemouton.markets.order_export import supported_markets
        from lemouton.markets.order_ingest import refresh_open_orders
        sup = supported_markets()
        for m in _OPEN_MARKETS:
            if m not in sup:
                continue
            r = refresh_open_orders(m, days=_WIDE_DAYS, limit=limit)
            if r['dates']:
                logger.info('order_ingest_open[%s]: %d일 재확인 %s · 갱신 %d · 실패 %d',
                            m, len(r['dates']), r['dates'], r['orders_updated'],
                            len(r['errors']))
            for e in r['errors'][:3]:
                logger.warning('order_ingest_open[%s] %s', m, e)
    except Exception:                                   # noqa: BLE001
        logger.exception('order_ingest open tick failed')


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
        # 21일이 옥션(180일)·G마켓(30일) 모두 **한 창**에 들어가 호출이 안 늘어난다.
        esm_days = int(os.environ.get('MOUM_ORDER_INGEST_ESM_DAYS', str(_WIDE_DAYS)))
    except ValueError:
        esm_hours, esm_days = 3, _WIDE_DAYS
    if esm_hours > 0 and sched.get_job('order_ingest_esm') is None:
        import datetime as _dtm3
        sched.add_job(lambda: _order_ingest_tick_esm(esm_days), 'interval',
                      hours=esm_hours, id='order_ingest_esm', max_instances=1,
                      coalesce=True, misfire_grace_time=60 * 30,
                      next_run_time=_dtm3.datetime.now() + _dtm3.timedelta(seconds=90))
        logger.info('scheduler: order_ingest_esm job every %dh (recent %dd, 첫 실행 90초 뒤)',
                    esm_hours, esm_days)
    # 정산 스윕 — 옥션·G마켓 정산만 다시 훑는다(주문 조회 없음). 0 이면 끔.
    #  주문 틱(3시간)과 분리해 자주 돈다: 정산조회는 31일 창이라 60일이 창 2개,
    #  계정 3 × 마켓 2 = 약 12콜이고 **주문조회 5초 제한 버킷을 안 쓴다**(별개 API).
    try:
        settle_min = int(os.environ.get('MOUM_ESM_SETTLE_SWEEP_MINUTES', '30'))
    except ValueError:
        settle_min = 30
    if settle_min > 0 and sched.get_job('order_settle_sweep') is None:
        import datetime as _dtm5
        sched.add_job(_order_settle_sweep_tick, 'interval', minutes=settle_min,
                      id='order_settle_sweep', max_instances=1, coalesce=True,
                      misfire_grace_time=60 * 10,
                      next_run_time=_dtm5.datetime.now() + _dtm5.timedelta(minutes=2))
        logger.info('scheduler: order_settle_sweep job every %dm (옥션·G마켓 정산만, 첫 실행 2분 뒤)',
                    settle_min)
    # 미확정 재확인 틱 — 스마트스토어·롯데온만. 하루씩만 조회되는 마켓이라
    #  3주 전체 대신 '아직 안 끝난 건이 남은 날짜'만 골라 돈다. 0 이면 끔.
    try:
        open_min = int(os.environ.get('MOUM_ORDER_INGEST_OPEN_MINUTES', '40'))
        open_limit = int(os.environ.get('MOUM_ORDER_INGEST_OPEN_LIMIT', '6'))
    except ValueError:
        open_min, open_limit = 40, 6
    if open_min > 0 and sched.get_job('order_ingest_open') is None:
        import datetime as _dtm4
        sched.add_job(lambda: _order_ingest_tick_open(open_limit), 'interval',
                      minutes=open_min, id='order_ingest_open', max_instances=1,
                      coalesce=True, misfire_grace_time=60 * 20,
                      next_run_time=_dtm4.datetime.now() + _dtm4.timedelta(minutes=4))
        logger.info('scheduler: order_ingest_open job every %dmin (최근 %d일 중 미확정 날짜 %d개씩)',
                    open_min, _WIDE_DAYS, open_limit)
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
