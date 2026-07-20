"""주문·클레임 수집 — 마켓에서 가져와 적재한다(증분 + 1년치 백필).

## 두 가지 모드

- **증분(`ingest_recent`)**: 최근 N일만 훑는다. 스케줄러가 주기적으로 돌린다.
  이미 있는 행은 갱신되고 새 행만 늘어난다(업서트).
- **백필(`backfill`)**: 과거를 거슬러 훑는다. 최초 1회 1년치를 채울 때 쓴다.
  마켓별 조회 창 제약이 다르므로(스마트스토어 1일 · 롯데온 1일 · 11번가 7일 ·
  쿠팡 31일 · 옥션 180일 · G마켓 31일) **뒤에서 앞으로 청크를 끊어** 돌린다.

## 왜 뒤에서 앞으로인가

중간에 끊겨도 「어디까지 됐나」가 명확하고, 오래된 구간부터 사라지는 마켓
(롯데온 클레임 = 1년 하드컷)을 먼저 건지기 때문이다.

## 정직성

- 실패한 청크는 삼키지 않고 `errors` 에 담아 돌려준다. 부분 성공을 성공이라 하지 않는다.
- 마켓이 상한을 **에러가 아니라 빈 응답**으로 알리는 경우가 있어(11번가 실측:
  7일 15건 → 8일 0건) 청크 크기는 실측 상한보다 작게 잡는다. 절대 늘리지 말 것.
"""
from __future__ import annotations

import datetime as _dt
import logging
from typing import Iterable, Optional

from lemouton.markets import order_store as _store

logger = logging.getLogger(__name__)

KST = _dt.timezone(_dt.timedelta(hours=9))

# 마켓별 백필 청크 크기(일). 2026-07-20 라이브 실측 상한에서 안전마진을 뺀 값.
#  ⚠️ 11번가는 상한 초과를 에러가 아니라 **빈 응답**으로 알린다 — 늘리면 주문이
#     에러 없이 사라진다. 실측 상한 7일이므로 7을 넘기지 말 것.
CHUNK_DAYS = {
    "smartstore": 1,     # 실측 상한 24시간 (2일부터 400 104140)
    "lotteon": 1,        # 실측 상한 1일 (2일부터 returnCode 2003)
    "eleven11": 7,       # 실측 상한 7일 — 초과 시 조용히 0건 🔴
    "coupang": 30,       # 실측 상한 31일
    "gmarket": 30,       # 실측 상한 31일
    "auction": 170,      # 실측 상한 180일 (181일부터 ResultCode 3000)
}
_DEFAULT_CHUNK = 7       # 모르는 마켓은 좁은 쪽 (넓게 잡아 조용히 잃느니 느린 게 낫다)


def chunk_days(market: str) -> int:
    return CHUNK_DAYS.get(market, _DEFAULT_CHUNK)


def windows(since: _dt.datetime, until: _dt.datetime, days: int):
    """[since, until] 을 days 크기로 끊어 **최신부터 과거 순으로** 돌려준다."""
    if days <= 0:
        days = 1
    end = until
    while end > since:
        start = max(since, end - _dt.timedelta(days=days))
        yield start, end
        end = start


def _fetch(market: str, start, end, *, include_settlement: bool = True):
    from lemouton.markets.order_export import combined_order_rows
    return combined_order_rows([market], since=start, until=end, warnings=[],
                               include_settlement=include_settlement)


def ingest_window(market: str, start, end, *, session=None,
                  include_settlement: bool = True) -> dict:
    """한 구간을 가져와 적재. 조회 실패는 예외를 올린다(호출부가 청크 단위로 잡는다)."""
    rows = _fetch(market, start, end, include_settlement=include_settlement)
    stat = _store.save(rows, session=session)
    stat["fetched"] = len(rows)
    return stat


def _run(market: str, since, until, *, session=None, on_progress=None,
         include_settlement: bool = True) -> dict:
    total = {"fetched": 0, "orders_new": 0, "orders_updated": 0,
             "claims_new": 0, "claims_updated": 0, "skipped_no_uid": 0}
    errors: list[str] = []
    wins = list(windows(since, until, chunk_days(market)))
    for i, (start, end) in enumerate(wins, 1):
        try:
            st = ingest_window(market, start, end, session=session,
                               include_settlement=include_settlement)
            for k in total:
                total[k] += st.get(k, 0)
        except Exception as e:                       # noqa: BLE001
            msg = (f"[{market}] {start:%Y-%m-%d}~{end:%Y-%m-%d} 수집 실패: "
                   f"{type(e).__name__}: {e}")
            logger.warning(msg)
            errors.append(msg)
        if on_progress:
            on_progress(i, len(wins), market)
    return {"market": market, "windows": len(wins), **total, "errors": errors}


def ingest_recent(markets: Iterable[str], *, days: int = 3,
                  session=None, on_progress=None) -> list[dict]:
    """증분 수집 — 최근 days 일. 스케줄러가 주기적으로 부른다."""
    until = _dt.datetime.now(KST)
    since = until - _dt.timedelta(days=days)
    return [_run(m, since, until, session=session, on_progress=on_progress)
            for m in markets]


def backfill(markets: Iterable[str], *, days: int = 365, session=None,
             on_progress=None, include_settlement: bool = False) -> list[dict]:
    """백필 — 과거 days 일을 채운다. 최초 1회 1년치용.

    ⚠️ **마켓 병렬은 되돌렸다(2026-07-20 라이브 장애).** 4개 마켓을 동시에 돌렸더니
    웹 프로세스의 DB 커넥션·스레드를 다 먹어 **앱이 502** 로 죽었다. 백필은 웹 요청과
    같은 프로세스에서 도는데, 백필을 빨리 하자고 서비스를 멈출 수는 없다.
    속도가 필요하면 병렬이 아니라 **스케줄러 프로세스로 옮기는 것**이 옳다.

    `include_settlement` 는 백필에서 **기본 꺼짐**. 정산 조회가 창마다 따로 붙어 가장
    느린데, 과거 주문의 정산은 나중에 따로 채울 수 있다. 속도를 위해 뺀다.
    (증분 수집은 켠 채로 둔다 — 최근 주문은 정산까지 최신이어야 한다.)

    ⚠️ 마켓 API 를 많이 두드린다(1년치 4마켓 ≈ 800회). 배경 실행 권장.
    """
    until = _dt.datetime.now(KST)
    since = until - _dt.timedelta(days=days)
    mk = list(markets)
    logger.info("주문 백필 시작: markets=%s days=%s settlement=%s", mk, days, include_settlement)
    return [_run(m, since, until, session=session, on_progress=on_progress,
                 include_settlement=include_settlement) for m in mk]


def estimate(markets: Iterable[str], days: int = 365) -> dict:
    """백필이 몇 번 호출될지 미리 알려준다(돌리기 전에 규모를 알 수 있게)."""
    per = {m: -(-days // chunk_days(m)) for m in markets}   # 올림
    return {"per_market": per, "total_windows": sum(per.values()), "days": days}
