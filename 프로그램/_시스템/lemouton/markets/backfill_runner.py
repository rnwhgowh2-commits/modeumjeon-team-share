"""백필 실행기 — 요청은 웹이 남기고, 실행은 스케줄러 프로세스가 한다.

## 왜 이렇게 나눴나

백필을 gunicorn **워커 안**에서 돌렸다가 라이브를 두 번 망가뜨렸다(2026-07-20):
  · 워커가 긴 작업에 점유돼 다른 요청이 줄서다 **앱이 502**
  · 워커는 `--timeout 60` · `--max-requests 1000` 으로 재활용되는데, 그때 작업
    스레드가 통째로 죽는다 → 백필이 75/796 창에서 조용히 멈췄다

그래서 웹은 **요청 플래그만** 남기고(`order_ingest_runs.requested`), 실제 실행은
gunicorn `--preload` 마스터에서 도는 스케줄러 스레드가 가져간다. 마스터는 요청을
처리하지 않으므로 요청 타임아웃·워커 재활용에 죽지 않는다.

## 중단돼도 이어서 한다

한 창을 끝낼 때마다 진행 위치(`cursor`)를 DB 에 적는다. 프로세스가 죽어도 다음 틱이
그 지점부터 잇는다. 백필은 업서트라 겹쳐 돌아도 데이터가 망가지지 않는다.

## 매달림 방지

창 하나에 시간 상한을 둔다. 마켓 호출이 타임아웃 없이 매달리면 백필 전체가 멈추므로,
상한을 넘기면 그 창을 실패로 적고 다음으로 간다(그 창은 나중에 다시 시도하면 된다).
"""
from __future__ import annotations

import datetime as _dt
import logging
import time as _time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as _Timeout
from datetime import datetime, timezone

from lemouton.markets.order_ingest import (KST, backfill_chunk_days,
                                          ingest_window, windows)

logger = logging.getLogger(__name__)

ROW_ID = "current"
WINDOW_TIMEOUT_SEC = 90         # 창 하나가 90초를 넘으면 포기하고 다음으로
                                #  (실측: 스스 1~8초 · 롯데온 3초 · 11번가 16초 · 쿠팡 75초)
PACE_SEC = {"smartstore": 1.0, "eleven11": 1.0}   # 창 사이 간격 — 429 폭주 방지
_DEFAULT_PACE = 0.0
TICK_BUDGET_SEC = 600           # 한 틱에 최대 10분 — 다음 틱이 이어받는다
MAX_TIMEOUTS = 5                # 연속 타임아웃이 이만큼이면 중단(마켓이 죽은 것)


_pool_reset_done = False


def _reset_pool_once() -> None:
    """이 프로세스에서 처음 쓸 때 DB 커넥션 풀을 새로 만든다.

    🔴 gunicorn `--preload` 는 `create_app()`(=`init_db()`)을 **마스터에서** 먼저 돌린
    뒤 워커를 fork 한다. 그때 열려 있던 TCP 커넥션이 마스터와 워커에 **동시에 상속**돼
    같은 소켓을 두 프로세스가 나눠 쓰게 된다 → 응답이 섞이거나 그냥 매달린다.
    실제로 같은 창이 워커(웹 라우트)에서는 1~8초인데 마스터(스케줄러)에서는 90초
    타임아웃에 걸렸다(2026-07-20).
    `dispose()` 로 상속된 커넥션을 버리면 이 프로세스가 자기 커넥션을 새로 연다.
    """
    global _pool_reset_done
    if _pool_reset_done:
        return
    _pool_reset_done = True
    try:
        from shared.db import engine
        engine.dispose()
        logger.info("backfill: DB 커넥션 풀 재생성(fork 상속분 폐기)")
    except Exception:                                # noqa: BLE001
        logger.exception("커넥션 풀 재생성 실패 — 계속 진행")


def _session():
    from shared.db import SessionLocal
    return SessionLocal()


def _get(s):
    from lemouton.markets.models_orders import OrderIngestRun
    row = s.get(OrderIngestRun, ROW_ID)
    if row is None:
        row = OrderIngestRun(id=ROW_ID, running="0", requested="0")
        s.add(row)
        s.commit()
    return row


def request_backfill(markets: list[str], days: int) -> dict:
    """웹이 부른다 — 요청만 남기고 즉시 돌아온다(긴 작업을 워커에서 하지 않는다)."""
    from lemouton.markets.order_ingest import estimate

    est = estimate(markets, days)
    s = _session()
    try:
        row = _get(s)
        row.requested = "1"
        row.markets = ",".join(markets)
        row.days = str(days)
        row.done, row.total = "0", str(est["total_windows"])
        row.cursor = ""
        row.error, row.result = "", []
        row.started_at, row.finished_at = datetime.now(timezone.utc), None
        s.commit()
    finally:
        s.close()
    return est


def _plan(markets: list[str], days: int) -> list[tuple]:
    """돌아야 할 (마켓, 시작, 끝) 전체 목록. 마켓 순차 · 각 마켓은 최신→과거."""
    until = _dt.datetime.now(KST)
    since = until - _dt.timedelta(days=days)
    plan = []
    for m in markets:
        for start, end in windows(since, until, backfill_chunk_days(m)):
            plan.append((m, start, end))
    return plan


def _run_window(market, start, end) -> dict:
    """창 하나를 시간 상한 안에서 실행. 넘기면 _Timeout 을 올린다.

    🔴 `with ThreadPoolExecutor(...)` 를 쓰면 안 된다. with 를 빠져나갈 때
    `shutdown(wait=True)` 가 불려 **매달린 작업이 끝날 때까지 블록**된다 —
    타임아웃을 걸어놓고도 무한정 기다리게 된다(2026-07-20 라이브: 백필이
    15/796 에서 running=True 인 채로 멈췄다. 개별 창은 1~8초인데도).
    → 컨텍스트 매니저 없이 만들고, 타임아웃이면 기다리지 않고 버린다.

    ⚠️ 버려진 스레드는 죽일 수 없다(파이썬 한계). 그래서 연속 타임아웃이 이어지면
    아예 중단한다 — 버려진 스레드가 쌓이면 그게 또 자원을 먹는다.
    """
    ex = ThreadPoolExecutor(max_workers=1)
    try:
        fut = ex.submit(ingest_window, market, start, end,
                        include_settlement=False, backfill=True)
        try:
            return fut.result(timeout=WINDOW_TIMEOUT_SEC)
        except _Timeout:
            ex.shutdown(wait=False)      # 기다리지 않고 버린다
            raise
    finally:
        # 정상 종료면 이미 끝났으므로 대기 없이 정리(타임아웃 경로는 위에서 처리).
        ex.shutdown(wait=False)


def run_if_requested() -> None:
    """스케줄러가 1분마다 부른다. 요청이 있으면 예산만큼 돌고 진행을 저장한다."""
    _reset_pool_once()
    s = _session()
    try:
        row = _get(s)
        if row.requested != "1":
            return
        markets = [m for m in (row.markets or "").split(",") if m]
        days = int(row.days or 365)
        cursor = int(row.cursor or 0)
        row.running = "1"
        s.commit()
    finally:
        s.close()

    plan = _plan(markets, days)
    started = _dt.datetime.now(_dt.timezone.utc)
    errors: list[str] = []
    consecutive_timeouts = 0
    done = cursor
    stop_reason = ""
    slowest = (0.0, "")

    for idx in range(cursor, len(plan)):
        if (_dt.datetime.now(_dt.timezone.utc) - started).total_seconds() > TICK_BUDGET_SEC:
            stop_reason = "예산 소진 — 다음 틱이 이어받음"
            break
        market, start, end = plan[idx]
        # 429 는 한 번 걸리면 클라이언트가 호출 간격을 늘려(halve) 뒤로 갈수록 느려진다.
        #  창 사이에 조금 쉬어 폭주를 예방한다(연속 조회가 아니라 백필이라 여유 있다).
        pace = PACE_SEC.get(market, _DEFAULT_PACE)
        if pace and idx > cursor:
            _time.sleep(pace)
        w0 = _dt.datetime.now(_dt.timezone.utc)
        try:
            _run_window(market, start, end)
            consecutive_timeouts = 0
            secs = (_dt.datetime.now(_dt.timezone.utc) - w0).total_seconds()
            if secs > slowest[0]:
                slowest = (secs, f"{market} {start:%Y-%m-%d}")
        except _Timeout:
            consecutive_timeouts += 1
            msg = (f"[{market}] {start:%Y-%m-%d}~{end:%Y-%m-%d} "
                   f"{WINDOW_TIMEOUT_SEC}초 초과 — 건너뜀")
            logger.warning(msg)
            errors.append(msg)
            if consecutive_timeouts >= MAX_TIMEOUTS:
                stop_reason = f"연속 타임아웃 {consecutive_timeouts}회 — 중단"
                done = idx + 1
                break
        except Exception as e:                       # noqa: BLE001
            consecutive_timeouts = 0
            msg = (f"[{market}] {start:%Y-%m-%d}~{end:%Y-%m-%d} 실패: "
                   f"{type(e).__name__}: {e}")
            logger.warning(msg)
            errors.append(msg)
        done = idx + 1
        if done % 5 == 0:
            _save(done=done, cursor=done, market=market, errors=errors)

    finished = done >= len(plan) or stop_reason.startswith("연속")
    _save(done=done, cursor=done, market=plan[min(done, len(plan) - 1)][0] if plan else "",
          errors=errors, finished=finished, stop_reason=stop_reason)
    logger.info("order_backfill: %d/%d 창 (%s) 최장 %.1fs %s",
                done, len(plan), stop_reason or "계속", slowest[0], slowest[1])


def _save(*, done: int, cursor: int, market: str, errors: list,
          finished: bool = False, stop_reason: str = "") -> None:
    s = _session()
    try:
        row = _get(s)
        row.done, row.cursor, row.market = str(done), str(cursor), market
        prev = row.result if isinstance(row.result, list) else []
        # 에러는 계속 쌓이므로 최근 30건만 (진단엔 충분하고 행이 비대해지지 않는다)
        row.result = (prev + errors)[-30:] if errors else prev
        if stop_reason:
            row.error = stop_reason[:500]
        if finished:
            row.requested, row.running = "0", "0"
            row.finished_at = datetime.now(timezone.utc)
        else:
            row.running = "0"        # 틱이 끝나면 running 은 내린다(다음 틱이 이어받음)
        s.commit()
    except Exception:                                # noqa: BLE001
        logger.exception("backfill 진행 저장 실패")
    finally:
        s.close()


def status() -> dict:
    s = _session()
    try:
        row = _get(s)
        return {"requested": row.requested == "1", "running": row.running == "1",
                "markets": row.markets or "", "days": row.days or "",
                "done": int(row.done or 0), "total": int(row.total or 0),
                "cursor": int(row.cursor or 0), "market": row.market or "",
                "error": row.error or "", "recent_errors": row.result or [],
                "started_at": row.started_at.isoformat() if row.started_at else None,
                "finished_at": row.finished_at.isoformat() if row.finished_at else None}
    finally:
        s.close()


def cancel() -> None:
    s = _session()
    try:
        row = _get(s)
        row.requested, row.running = "0", "0"
        row.error = "사용자가 중단함"
        row.finished_at = datetime.now(timezone.utc)
        s.commit()
    finally:
        s.close()
