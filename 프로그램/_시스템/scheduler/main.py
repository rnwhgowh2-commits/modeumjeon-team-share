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

    # 상품관리 야간 훑기는 여기 두면 **프로덕션에서 안 돈다** —
    #   start_catalog_sync_scheduler() 로 옮겼다(create_app 에서 부른다).
    #   개발 실행(`python app.py`)에서도 돌게 여기서 한 번 더 부른다(중복 등록은
    #   get_job 검사가 막는다).
    start_catalog_sync_scheduler()

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


def start_catalog_sync_scheduler() -> BackgroundScheduler:
    """상품관리 — 마켓 상품 머리글 야간 훑기 등록·기동.

    ★ **create_app() 에서 부른다.** 예전엔 start_scheduler() 안에 있었는데,
      그 함수는 `__main__`(개발 실행)에서만 불려서 **프로덕션(gunicorn)에서는
      아예 안 돌았다** — 주문 수집이 2026-07-20 에 겪은 것과 같은 자리다.
      라이브 실측(2026-08-04): 마켓 상품 캐시가 3,291건에서 멈춰 있었다.
      롯데온 한 마켓만 실제 136,510건인데도.

    ★ 이 스레드는 gunicorn --preload 마스터에서 돈다 — 요청을 처리하지 않는
      프로세스라 30~60분짜리 훑기가 워커를 점유해 502 를 내지 않는다.

    ★ 기본 꺼짐. `MOUM_CATALOG_SYNC_HOUR=3` 이면 매일 새벽 3시.
      켜는 순간 6마켓 36계정에 약 2,700 호출이 나간다.
    """
    sched = get_scheduler()
    hour = _catalog_sync_hour()
    if hour is None:
        logger.info('scheduler: catalog_sync 꺼짐 (MOUM_CATALOG_SYNC_HOUR 미설정)')
        return sched
    if sched.get_job('catalog_sync') is None:
        from lemouton.catalog.sync import sync_all as _catalog_sync_all
        sched.add_job(
            _catalog_sync_all,
            'cron',
            hour=hour,
            minute=0,
            id='catalog_sync',
            max_instances=1,
            coalesce=True,
            misfire_grace_time=60 * 60,
        )
        logger.info('scheduler: catalog_sync job every day at %02d:00', hour)
    return sched


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
        from lemouton.markets.order_ingest import (refresh_settlement,
                                                   refresh_settlement_coupang,
                                                   refresh_settlement_eleven11,
                                                   refresh_settlement_lotteon,
                                                   refresh_settlement_smartstore)
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
        # 쿠팡 — 인식일 기준·(주문번호,옵션ID) 키라 ESM 과 함수가 다르다. 같은 틱에 얹는다:
        #  정산조회는 옥션·G마켓의 5초/1콜 버킷과 무관하고, 쿠팡은 창을 열 때만 실값을
        #  붙여서 5일 넘게 안 본 옛 주문이 추정으로 고착됐다(사장님 신고 원인 계열).
        if 'coupang' in sup:
            st = refresh_settlement_coupang()
            if st['updated'] or st['errors']:
                logger.info('order_settle_sweep[coupang]: 계정 %d · 정산 %d건 → 갱신 %d · 실패 %d',
                            st['accounts'], st['settle_rows'], st['updated'],
                            len(st['errors']))
            for e in st['errors'][:3]:
                logger.warning('order_settle_sweep[coupang] %s', e)
        # 스마트스토어 — 결제일 기준 하루씩 정산조회. 네이버는 병렬 429라 계정 내 순차라
        #  한 틱이 무거울 수 있어 창을 좁게(기본 45일) 두고, 옛 backlog 는 수동 넓은 스윕으로.
        if 'smartstore' in sup:
            st = refresh_settlement_smartstore()
            if st['updated'] or st['errors']:
                logger.info('order_settle_sweep[smartstore]: 계정 %d · 정산 %d건 → 갱신 %d · 실패 %d',
                            st['accounts'], st['settle_rows'], st['updated'],
                            len(st['errors']))
            for e in st['errors'][:3]:
                logger.warning('order_settle_sweep[smartstore] %s', e)
        # 롯데온 — 쿠팡과 같은 구매확정일(인식일) 기준·odNo 단일 키. 같은 틱에 얹는다:
        #  롯데온도 정산 스윕이 없어 적재틱(7~21일)이 닫힌 뒤 구매확정된 옛 주문의 실정산이
        #  추정으로 고착됐다(쿠팡·ESM 과 같은 계열). rate 버킷이 계정별이라 계정 병렬 안전.
        if 'lotteon' in sup:
            st = refresh_settlement_lotteon()
            if st['updated'] or st['errors']:
                logger.info('order_settle_sweep[lotteon]: 계정 %d · 정산 %d건 → 갱신 %d · 실패 %d',
                            st['accounts'], st['settle_rows'], st['updated'],
                            len(st['errors']))
            for e in st['errors'][:3]:
                logger.warning('order_settle_sweep[lotteon] %s', e)
        # 11번가 — 구매확정일 기준·(ordNo,ordPrdSeq) 라인 키. 같은 틱에 얹는다:
        #  11번가도 정산 스윕이 없어 적재틱(21일)이 닫힌 뒤 구매확정된 옛 주문의 실정산이
        #  추정(stlPlnAmt)으로 고착됐다. 🔴rate 가 IP 전역이라 계정 **순차**(병렬 시 429 전체 죽음).
        if 'eleven11' in sup:
            st = refresh_settlement_eleven11()
            if st['updated'] or st['errors']:
                logger.info('order_settle_sweep[eleven11]: 계정 %d · 정산 %d건 → 갱신 %d · 실패 %d',
                            st['accounts'], st['settle_rows'], st['updated'],
                            len(st['errors']))
            for e in st['errors'][:3]:
                logger.warning('order_settle_sweep[eleven11] %s', e)
        # ── 깊은 백필 — 하루 한 마켓씩 과거 180일 ─────────────────────────────
        #  🔴 위 스윕들은 최근 45~75일만 본다. 그 창이 닫힌 뒤 확정된 정산은 **영영 안 들어와**
        #    「이미 받았을 것(확인 불가)」로 쌓인다(2026-08-07 라이브 실측 **1억 5,242만원**).
        #    손으로 과거를 넓게 훑으니 1억 5,433만이 「확인」으로 넘어갔고, 덤으로 옥션 정산율
        #    거짓 경고(3.7% vs 15%)도 사라졌다(정산이 덜 채워져 과대로 보이던 것).
        #  ★ 한 틱에 전 마켓을 훑으면 무겁다(스스는 하루씩 조회라 180일=계정당 180콜)
        #    → 하루 한 마켓씩 순환. 6일에 한 바퀴면 과거 정산엔 충분하다.
        _deep_backfill_once(sup)
    except Exception:                                   # noqa: BLE001
        logger.exception('order settle sweep failed')


def _deep_backfill_once(sup) -> None:
    """오늘 몫 한 마켓만 과거 180일로 훑는다(하루 1회·순환). 실패해도 다음 마켓으로 넘어간다."""
    from datetime import date as _date

    from lemouton.markets import settle_backfill as _bf
    from lemouton.markets.order_ingest import (refresh_settlement,
                                               refresh_settlement_coupang,
                                               refresh_settlement_eleven11,
                                               refresh_settlement_lotteon,
                                               refresh_settlement_smartstore)
    today = _date.today()
    mk = _bf.due_market(today=today, supported=set(sup))
    if not mk:
        return
    since, until = _bf.window(today=today)
    fn = {'coupang': refresh_settlement_coupang,
          'smartstore': refresh_settlement_smartstore,
          'lotteon': refresh_settlement_lotteon,
          'eleven11': refresh_settlement_eleven11}.get(mk)
    st = None
    try:
        st = fn(since=since, until=until) if fn else refresh_settlement(
            mk, since=since, until=until)
        logger.info('settle_deep_backfill[%s]: %s~%s · 정산 %d건 → 갱신 %d · 실패 %d',
                    mk, since.date(), until.date(), st.get('settle_rows', 0),
                    st.get('updated', 0), len(st.get('errors') or []))
        for e in (st.get('errors') or [])[:3]:
            logger.warning('settle_deep_backfill[%s] %s', mk, e)
    except Exception as e:                              # noqa: BLE001
        # 조용히 넘기지 않는다 — 어느 마켓이 왜 막혔는지 로그와 기록에 남긴다.
        logger.exception('settle_deep_backfill[%s] 실패', mk)
        st = {'errors': [f'{type(e).__name__}: {str(e)[:200]}']}
    finally:
        _bf.mark_done(mk, today=today, stat=st or {})


def _order_invoice_sweep_tick() -> None:
    """옥션·G마켓·11번가 **송장번호·택배사만** 다시 훑는다 — 주문 재적재 없음.

    🔴 왜 따로 도는가(2026-07-30 실측) — 저장분 송장 보유율이 G마켓 34/190 · 옥션 25/47 ·
      11번가 109/743 로 저조한데, 같은 G마켓을 **라이브**로 20일 조회하면 23/23(100%)다.
      마켓은 정상으로 주는데 **창고에 안 담긴 것**이고 원인은 둘:
        ① ESM 증분은 **주문일 기준 21일 창**(_WIDE_DAYS)만 본다 → 주문 후 21일 지나
           발송하면(까대기 특성상 흔함) 그 송장을 영영 못 받는다.
        ② 11번가는 배송중·배송완료만 invcNo 를 주고 **구매확정은 안 준다** → 21일 안에
           구매확정으로 넘어가면 송장 없이 굳는다.
      정산 스윕과 같은 처방: 과거분을 넓게(120일) 다시 훑어 **빈 칸만** 채운다.

    ★ 쿠팡·스스·롯데온은 제외 — 주문조회가 송장을 늘 줘서 이미 99%+ 다(실측).
    ★ 마켓이 안 주면 그대로 둔다(날조 금지).
    """
    try:
        from lemouton.markets.order_export import supported_markets
        from lemouton.markets.order_ingest import refresh_invoices
        sup = supported_markets()
        for m in ('auction', 'gmarket', 'eleven11'):
            if m not in sup:
                continue
            st = refresh_invoices(m)
            if st['updated'] or st['errors']:
                logger.info('order_invoice_sweep[%s]: 계정 %d · 마켓송장 %d건 → 갱신 %d · 실패 %d',
                            m, st['accounts'], st['fetched'], st['updated'],
                            len(st['errors']))
            for e in st['errors'][:3]:
                logger.warning('order_invoice_sweep[%s] %s', m, e)
    except Exception:                                   # noqa: BLE001
        logger.exception('order invoice sweep failed')


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
                # 옛 차선(창 밖에서 굳은 미확정)을 따로 찍는다 — 이게 안 돌면 옛
                # 주문이 조용히 '주문' 상태로 굳는다(2026-08-02 롯데온 554건 실측).
                logger.info('order_ingest_open[%s]: %d일 재확인 %s · 옛것 %s · 갱신 %d · 실패 %d',
                            m, len(r['dates']), r['dates'], r.get('stale_dates') or [],
                            r['orders_updated'], len(r['errors']))
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
    # (정답지 대조 실측 ±610~1,347원) → 오래 안 본 순 8건/틱 단건 재조회.
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
    # 🚨 「배송완료 굳음 되살리기」 자동 실행은 **끈다**(2026-08-12 라이브 실측으로 철회).
    #   의도 — 최근 21일 창을 지나 구매확정된 주문이 배송완료로 굳는 걸 되조회로 풀기.
    #   실제 — 진단 창구로 30건을 돌려 보니 **30건 전부 상태가 뒤로 갔다**:
    #            배송완료→출고지시 24 · 배송완료→회수지시 6
    #   원인 — 롯데온 단건 조회는 같은 상품라인을 **단계별 여러 행**으로 준다. 나중에
    #          처리된 행이 상태를 덮어써 시간이 거꾸로 흐른다. 이 사실은 이미
    #          `sell_source._one_row_per_line` 주석에 실측으로 적혀 있었다
    #          (「출고지시 37,599 + 배송완료 38,505」) — 내가 그걸 안 읽고 배선했다.
    #   ★ 다행히 한 번도 안 돌았다(진단: 이미시도한건수 0). 돌았다면 882건이 망가졌다.
    #   ★ 되살리기 함수·진단 창구는 남긴다 — 손으로 원인을 재는 데는 여전히 쓸모 있다.
    #   ★ 올바른 길은 상태 되조회가 아니라 **정산 사실로 판정**하는 것이다
    #     (롯데온 지급내역 seCmptDt 조인 — `lemouton/margin/lotteon_paid.py`).


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
    # 정산 스윕 — 옥션·G마켓·쿠팡·롯데온 정산만 다시 훑는다(주문 조회 없음). 0 이면 끔.
    #  주문 틱(3시간)과 분리해 자주 돈다: 정산조회는 31일 창이라 60일이 창 2개,
    #  계정 × 마켓 몇 콜이고 **주문조회 5초 제한 버킷을 안 쓴다**(별개 API).
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
        logger.info('scheduler: order_settle_sweep job every %dm (옥션·G마켓·쿠팡·스마트스토어·롯데온·11번가 정산, 첫 실행 2분 뒤)',
                    settle_min)
    # 송장 스윕 — ESM 21일 창·11번가 구매확정이 놓친 송장·택배사를 채운다. 0 이면 끔.
    #  ESM 은 5초/1콜 제한이라 한 바퀴가 길다 → 정산 스윕(30분)보다 드물게 돈다.
    try:
        inv_min = int(os.environ.get('MOUM_INVOICE_SWEEP_MINUTES', '180'))
    except ValueError:
        inv_min = 180
    if inv_min > 0 and sched.get_job('order_invoice_sweep') is None:
        import datetime as _dtm6
        sched.add_job(_order_invoice_sweep_tick, 'interval', minutes=inv_min,
                      id='order_invoice_sweep', max_instances=1, coalesce=True,
                      misfire_grace_time=60 * 20,
                      next_run_time=_dtm6.datetime.now() + _dtm6.timedelta(minutes=5))
        logger.info('scheduler: order_invoice_sweep job every %dm (옥션·G마켓·11번가 송장·택배사, 첫 실행 5분 뒤)',
                    inv_min)
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
    # ── 쿠팡 쿠폰: 대기열 처리 + 자동연장 (2026-08-13 사장님 확정) ──────────
    #  🔴 「대기열에 넣었다」 ≠ 「처리된다」 — 이 틱이 **처리기**다. 없으면 단추가
    #    거짓말이 된다(라이브에서 실제로 겪은 사고).
    #  쿠폰 한 번 걸기는 만들기·확인·붙이기·확인이고, 거부되면 300원까지 최대 21번
    #  되풀이한다 — 몇 분이 걸려 화면이 못 기다린다. 그래서 여기서 돈다.
    #  요청도 연장 대상도 없으면 조회 두 번에 끝난다.
    if (os.environ.get('MOUM_COUPANG_COUPON_TICK', '1') == '1'
            and sched.get_job('coupang_coupon') is None):
        sched.add_job(_coupang_coupon_tick, 'interval', minutes=1,
                      id='coupang_coupon', max_instances=1, coalesce=True,
                      misfire_grace_time=300)
        logger.info('scheduler: coupang_coupon queue+renew every 1min')
    # ── 메모리 심박 로그 (2026-08-26 라이브 OOM 조사) ───────────────────────
    #  🔴 OOM-kill 은 SIGKILL 이라 죽는 순간 파이썬 코드가 한 줄도 못 돈다 — "몇 시에
    #    죽었다"는 커널 로그로 알아도 "그때 뭘 하고 있었는지"는 알 방법이 없었다.
    #    5분마다 RSS 를 남겨두면, 다음에 또 죽었을 때 죽기 직전 수치와 그 앞뒤에 찍힌
    #    다른 작업 로그(auto-confirm tick 시작/종료 등)를 맞춰봐서 범인을 좁힐 수 있다.
    #    컨테이너 램 상한(900MB)과 바로 비교되게 MiB 로 남긴다.
    if (os.environ.get('MOUM_MEM_HEARTBEAT', '1') == '1'
            and sched.get_job('mem_heartbeat') is None):
        sched.add_job(_mem_heartbeat_tick, 'interval', minutes=5,
                      id='mem_heartbeat', max_instances=1, coalesce=True,
                      misfire_grace_time=300)
        logger.info('scheduler: mem_heartbeat RSS 로그 every 5min')
    if not sched.running:
        sched.start()
    return sched


def _mem_heartbeat_tick() -> None:
    """현재 프로세스 RSS(MiB) 로그 — /proc/self/status 읽기(리눅스 전용, 의존성 추가 없음).

    리눅스가 아니면(윈도우 개발 PC 등) 조용히 스킵 — 이 로그는 라이브 진단용이라
    로컬 개발에는 의미 없고, 실패해도 스케줄러 자체가 죽으면 안 된다.
    """
    try:
        with open('/proc/self/status', 'r', encoding='utf-8') as f:
            for line in f:
                if line.startswith('VmRSS:'):
                    kb = int(line.split()[1])
                    logger.info('[mem] RSS=%.1fMiB', kb / 1024)
                    return
    except (FileNotFoundError, OSError, ValueError):
        pass   # /proc 없음(윈도우 등) — 조용히 스킵


def _coupang_coupon_tick() -> None:
    """쿠폰 걸기 요청과 만료 임박 쿠폰을 처리한다. 할 일이 없으면 즉시 끝.

    🔴 한 틱에 처리할 수를 묶는다 — 쿠폰 하나가 최대 21번 왕복이라, 안 묶으면 한 틱이
      몇십 분을 붙잡고 다음 틱과 겹친다(max_instances=1 이라 조용히 밀린다).
    """
    try:
        from lemouton.policy import coupon_service as CS
        from lemouton.sets.set_link_service import _resolve_env_prefix
        from lemouton.uploader import market_fetch as MF
        from shared.db import SessionLocal

        s = SessionLocal()
        try:
            if not CS.pending_requests(s) and not CS.due_renewals(s):
                return

            def _client(ch):
                # 🔴 그 상품이 등록된 **그 계정**의 열쇠로 걸어야 한다 — 기본 계정으로
                #   걸면 다른 계정엔 그 옵션이 없어 전부 거부된다.
                return MF._coupang_client(
                    _resolve_env_prefix(s, ch.market, ch.account_key))

            stat = CS.run_pending(s, client_for=_client, limit=3)
            if any(stat.values()):
                logger.info('coupang_coupon tick: %s', stat)
        finally:
            s.close()
    except Exception:                                   # noqa: BLE001
        logger.exception('coupang_coupon tick failed')


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


def _notion_todo_report_tick() -> None:
    """등록된 발송 시각이 되었으면 노션 투두 요약을 카카오톡으로 보낸다.

    1분마다 돌면서 **지금 시각이 시각표에 있는지** 본다. 시각을 화면에서 바꿔도
    스케줄러를 다시 등록할 필요가 없다(cron 잡을 시각마다 만들면 설정 변경 때마다
    등록·해제를 맞춰야 하고, 어긋나면 조용히 안 나간다).

    놓친 회차 보정: 서버가 그 분에 재기동 중이었으면 **뒤이은 몇 분 안에** 따라잡는다.
    """
    try:
        from datetime import datetime as _dt, timedelta as _td, timezone as _tz

        from lemouton.reports import report_schedule
        from lemouton.reports.notion_todo import run_slot_report

        try:
            from zoneinfo import ZoneInfo
            now = _dt.now(ZoneInfo('Asia/Seoul'))
        except Exception:   # noqa: BLE001 — tzdata 없는 환경 폴백
            now = _dt.now(_tz(_td(hours=9)))

        day = now.date().isoformat()
        # 정각에 정확히 못 돌아도 GRACE 분 안이면 그 회차로 인정.
        grace = int(os.environ.get('MOUM_NOTION_REPORT_GRACE_MIN', '20'))
        due = []
        for slot in report_schedule.times():
            hh, mm = (int(x) for x in slot.split(':'))
            slot_at = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            delta = (now - slot_at).total_seconds() / 60.0
            if 0 <= delta <= grace and not report_schedule.already_sent(slot, day):
                due.append(slot)

        for slot in due:
            res = run_slot_report(slot)
            logger.info('notion_todo report %s: %s', slot,
                        {k: v for k, v in res.items()
                         if k not in ('todos', 'today', 'changes')})
    except Exception:   # noqa: BLE001 — 보고 실패가 스케줄러를 죽이지 않게
        logger.exception("notion_todo report tick failed")


def start_notion_report_scheduler() -> BackgroundScheduler:
    """매일 정해진 시각(기본 09:30 KST) 노션 투두 보고 등록·기동.

    ★ create_app() 에서 부른다 — gunicorn(--preload) 마스터 스레드라 워커 3개에
      중복 등록되지 않는다. 그래도 배포 재기동 시 misfire 보정으로 한 번 더 뛸 수
      있어, 실제 중복 발송은 run_daily_report() 의 `sent_date` 게이트가 막는다.

    MOUM_NOTION_REPORT_AT="" 이면 끔. 형식은 "HH:MM".
    """
    sched = get_scheduler()
    if os.environ.get('MOUM_NOTION_REPORT_OFF') == '1':
        logger.info('scheduler: notion_todo_report 비활성(MOUM_NOTION_REPORT_OFF=1)')
        return sched
    if sched.get_job('notion_todo_report') is None:
        # 1분 틱 — 발송 시각은 화면에서 언제든 바뀌므로 잡을 시각에 묶지 않는다.
        #   틱 본체는 시각표에 걸리는 게 없으면 즉시 no-op 이라 부하가 없다.
        sched.add_job(_notion_todo_report_tick, 'interval', minutes=1,
                      id='notion_todo_report', max_instances=1, coalesce=True,
                      misfire_grace_time=60 * 5)
        logger.info('scheduler: notion_todo_report tick every 1min '
                    '(발송 시각은 화면 설정을 따름)')
    if not sched.running:
        sched.start()
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
