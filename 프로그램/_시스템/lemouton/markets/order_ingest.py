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
    "lotteon": 1,        # 실측 상한 1일 (2일부터 returnCode 2003)  ← 증분(209 배송지시)
    "eleven11": 7,       # 실측 상한 7일 — 초과 시 조용히 0건 🔴
    "coupang": 30,       # 실측 상한 31일
    "gmarket": 30,       # 실측 상한 31일
    "auction": 170,      # 실측 상한 180일 (181일부터 ResultCode 3000)
}
_DEFAULT_CHUNK = 7       # 모르는 마켓은 좁은 쪽 (넓게 잡아 조용히 잃느니 느린 게 낫다)

# 백필 전용 청크 — 과거 이력은 더 넓은 창을 주는 API 를 쓸 수 있다.
#  롯데온: 증분은 209(1일 창)지만, 과거는 정산 API SettleProduct 가 29일 창이라
#  1년치가 365회 → 13회로 준다(28배). 지도 fields 로 필드 확인 완료.
#  쿠팡: 상한은 31일이지만 과거 구간(주문 많음)은 30일 창이 300초를 넘겨 건너뛰어졌다.
#  창을 반으로 줄이면 호출 수는 2배지만 창당 시간이 줄어 타임아웃으로 통째 잃지 않는다.
# 쿠팡 과거 창은 데이터가 많아 14일이면 워커 step(gunicorn 60초)을 넘겨 스킵된다
#  (2026-07-20 실측: 과거 14일 창 >45초). 7일로 줄이면 각 창이 빨라져 담긴다(창 수는 2배).
#  옥션 180일·G마켓 31일(마켓 상한). 워커 step 은 창 타임아웃 45초라, 큰 창이면
#  스킵될 수 있어 auction 은 90일로 절반(step budget 안). gmarket 은 31일 그대로.
BACKFILL_CHUNK_DAYS = {"lotteon": 29, "coupang": 7, "auction": 90, "gmarket": 31}
#  그 마켓의 백필 전용 수집기(없으면 평소 경로 사용)
BACKFILL_FETCHERS = {"lotteon": "lotteon_settle", "coupang": "coupang_orders_only",
                     "smartstore": "smartstore_orders_only",
                     "auction": "esm_orders_only", "gmarket": "esm_orders_only"}


def backfill_chunk_days(market: str) -> int:
    return BACKFILL_CHUNK_DAYS.get(market, chunk_days(market))


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


def _fetch(market: str, start, end, *, include_settlement: bool = True,
           backfill: bool = False, prefix: str = None, alias: str = None):
    """한 창 조회. backfill 경로는 prefix(계정)를 존중하고 alias 를 행에 새긴다.

    ★ 예전엔 백필 fetcher 가 전부 대표계정(_account_client(market))만 조회해
    나머지 계정의 과거가 통째 빠졌다(2026-07-22 샵마인 대사: 누락 605건 최대 원인).
    """
    rows = _fetch_inner(market, start, end, include_settlement=include_settlement,
                        backfill=backfill, prefix=prefix)
    if alias:
        for r in rows:
            r["쇼핑몰별칭"] = alias
    return rows


def _acct_client(market: str, prefix: str = None):
    from lemouton.markets.order_export import _account_client
    return _account_client(market, prefix) if prefix else _account_client(market)


def _fetch_inner(market: str, start, end, *, include_settlement: bool = True,
                 backfill: bool = False, prefix: str = None):
    if backfill and BACKFILL_FETCHERS.get(market) == "smartstore_orders_only":
        # 과거 주문만 빠르게 — 변경일 조회를 '지금'까지 확장하지 않는다(창 안만).
        #  주문일 트리밍도 안 한다(직접 호출) → 변경일이 이 창에 속한 주문을 그대로 적재.
        #  호출부가 1년 전 창까지 훑으므로 union 으로 전체가 빠짐없이 모인다.
        from lemouton.markets.order_export import (_account_client, _finalize_rows,
                                                   smartstore_order_rows)
        from lemouton.markets import line_uid as _luid
        raw = smartstore_order_rows(start, end, client=_acct_client(market, prefix),
                                    include_settlement=False, changed_to_now=False)
        _luid.stamp(market, raw)
        return _finalize_rows(raw)
    if backfill and BACKFILL_FETCHERS.get(market) == "coupang_orders_only":
        # 과거 주문만 빠르게(클레임을 '지금'까지 확장하지 않음 → 창 하나가 50초 안).
        from lemouton.markets.order_export import (_account_client, _finalize_rows,
                                                   coupang_order_rows)
        from lemouton.markets import line_uid as _luid
        raw = coupang_order_rows(start, end, client=_acct_client(market, prefix),
                                 include_settlement=False, claim_to_now=False)
        _luid.stamp(market, raw)
        return _finalize_rows(raw)
    if backfill and BACKFILL_FETCHERS.get(market) == "lotteon_settle":
        # 과거 이력은 정산 API 로(29일 창). 수령자·주소·송장은 없지만 그건 발송용이지
        # 이력 조회용이 아니다 — 없는 값은 비워 둔다(지어내지 않는다).
        from lemouton.markets.order_export import _account_client
        from shared.platforms.lotteon import settle_orders as _so
        rows = _so.order_rows(start, end, client=_acct_client(market, prefix))
        from lemouton.markets import line_uid as _luid
        return _luid.stamp(market, rows)
    if backfill and BACKFILL_FETCHERS.get(market) == "esm_orders_only":
        # 과거 주문만(클레임을 '지금'까지 확장하지 않음 → 창이 커도 창 안만 스캔).
        #  옥션·G마켓은 주문일(requestDateType=1) 기준이라 창 안 조회가 곧 그 기간 주문.
        from lemouton.markets.order_export import _account_client, _finalize_rows, esm_order_rows
        from lemouton.markets import line_uid as _luid
        raw = esm_order_rows(market, start, end, client=_acct_client(market, prefix),
                             include_settlement=False, orders_only=True)
        _luid.stamp(market, raw)
        return _finalize_rows(raw)
    from lemouton.markets.order_export import combined_order_rows
    return combined_order_rows([market], since=start, until=end, warnings=[],
                               include_settlement=include_settlement)


def ingest_window(market: str, start, end, *, session=None,
                  include_settlement: bool = True, backfill: bool = False,
                  prefix: str = None, alias: str = None) -> dict:
    """한 구간을 가져와 적재. 조회 실패는 예외를 올린다(호출부가 청크 단위로 잡는다)."""
    rows = _fetch(market, start, end, include_settlement=include_settlement,
                  backfill=backfill, prefix=prefix, alias=alias)
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
    results = [_run(m, since, until, session=session, on_progress=on_progress)
               for m in markets]
    # 클레임→주문상태 자가치유(멱등·가벼움) — 백필 순서 역전·과거분(2026-07-21 이전)
    # 보정. 폴백 SQLite(테스트·.env 없는 개발기)는 건너뛴다: 다른 테스트 잔재를 읽어
    # 비결정 오염이 될 수 있다(fill_claim_blanks_from_history 와 같은 가드).
    try:
        if session is not None:
            _store.sync_status_from_claims(session=session)
            _store.dedupe_undated_claim_ghosts(session=session)
            _store.backfill_claim_dates_from_lines(session=session)
        else:
            from shared import db as _db
            if not getattr(_db, "_is_sqlite", False):
                _store.sync_status_from_claims()
                _store.dedupe_undated_claim_ghosts()
                _store.backfill_claim_dates_from_lines()
    except Exception:                                   # noqa: BLE001
        logger.exception("클레임→주문상태 보정 실패(수집 결과는 유효)")
    return results


def ingest_lotteon_claims_window(start, end, *, prefix: str = None,
                                 alias: str = None, session=None) -> dict:
    """롯데온 **과거 클레임** 한 창 적재 — 클레임 접수일 축, 창 안만.

    확정 전 취소는 정산API(구매확정건만)에 안 나와 과거 취소가 통째 빠졌다
    (2026-07-22 샵마인 대사: 취소완료 계열 233건). 209 없이 클레임 3종만 걷는다.
    업서트라 멱등. alias 를 새겨 계정 귀속을 남긴다.
    """
    from lemouton.markets import line_uid as _luid
    from lemouton.markets.order_export import _finalize_rows, lotteon_order_rows
    cli = _acct_client("lotteon", prefix)
    if cli is None:
        raise RuntimeError(f"[lotteon] API 키 미등록(prefix={prefix})")
    raw = lotteon_order_rows(start, end, client=cli, include_settlement=False,
                             claims_only=True, claim_to_now=False)
    _luid.stamp("lotteon", raw)
    rows = _finalize_rows(raw)
    if alias:
        for r in rows:
            r["쇼핑몰별칭"] = alias
    st = _store.save(rows, session=session)
    st["fetched"] = len(rows)
    return st


def ingest_lotteon_orders_window(start, end, *, prefix: str = None,
                                 alias: str = None, session=None) -> dict:
    """롯데온 **과거 209(출고/회수지시)** 한 창 적재 — 지시생성일 축, 창 안만.

    정산 API 백필(lotteon_settle)은 수령자·주소·전화·송장이 없다 — 그 필드는 209 가
    정본(2026-07-22 샵마인 전열 대조: 구매자 정보 공란 792). orders_to_now=False 로
    창 안만 걷고, 호출부가 (계정 × 창)을 이어 붙여 전체를 덮는다. 업서트 멱등이며
    _merge_row 가 빈 값으로 기존 채움을 지우지 않는다.
    """
    from lemouton.markets import line_uid as _luid
    from lemouton.markets.order_export import _finalize_rows, lotteon_order_rows
    cli = _acct_client("lotteon", prefix)
    if cli is None:
        raise RuntimeError(f"[lotteon] API 키 미등록(prefix={prefix})")
    raw = lotteon_order_rows(start, end, client=cli, include_settlement=False,
                             claims_only=False, claim_to_now=False,
                             orders_to_now=False)
    _luid.stamp("lotteon", raw)
    rows = _finalize_rows(raw)
    if alias:
        for r in rows:
            r["쇼핑몰별칭"] = alias
    st = _store.save(rows, session=session)
    st["fetched"] = len(rows)
    return st


def ingest_eleven11_orders_by_no(ord_nos, *, session=None) -> dict:
    """11번가 주문번호 **단건 정밀 복구** — 계정을 순회하며 각 주문을 찾아 적재.

    상태별 창 조회 9경로가 구조적으로 못 주는 주문(반품완료·구매확정 옛 건 —
    2026-07-22 샵마인 대사 잔여 26건)의 마지막 통로. 찾은 계정의 별칭을 새기고,
    못 찾은 주문번호는 숨기지 않고 돌려준다(조용한 실패 금지). 멱등.
    """
    import time as _time

    from lemouton.markets import line_uid as _luid
    from lemouton.markets.order_export import (_account_client, _active_accounts,
                                               _finalize_rows, eleven11_order_rows)
    now = _dt.datetime.now(KST)
    accounts = _active_accounts("eleven11") or [(None, None)]
    remaining = [str(n).strip() for n in (ord_nos or []) if str(n).strip()]
    found: dict = {}
    stat_sum = {"orders_new": 0, "orders_updated": 0, "claims_new": 0,
                "claims_updated": 0, "skipped_no_uid": 0}
    for prefix, name in accounts:
        if not remaining:
            break
        cli = _account_client("eleven11", prefix) if prefix else _account_client("eleven11")
        if cli is None:
            continue
        hit_rows = []
        for no in list(remaining):
            try:
                raw = eleven11_order_rows(now - _dt.timedelta(days=7), now, client=cli,
                                          include_settlement=False, order_nos=[no])
            except Exception:                        # noqa: BLE001 — 이 계정 키로는 조회불가
                raw = []
            if not raw:
                continue
            _luid.stamp("eleven11", raw)
            rows = _finalize_rows(raw)
            for r in rows:
                r["쇼핑몰별칭"] = name or ""
            hit_rows += rows
            found[no] = name or ""
            remaining.remove(no)
            _time.sleep(0.3)                         # 11번가 병렬·연타 금지
        if hit_rows:
            st = _store.save(hit_rows, session=session)
            for k in stat_sum:
                stat_sum[k] += st.get(k, 0)
    return {"found": found, "not_found": remaining, **stat_sum}


_ESM_MARKETS = {"auction", "gmarket"}


def ingest_esm_claims_window(market: str, start, end, *, prefix: str = None,
                             alias: str = None, session=None) -> dict:
    """옥션·G마켓 **과거 클레임** 한 창 적재 — 클레임 신청·완료일 축, 창 안만.

    1년 백필이 orders_only(속도) 라 과거 클레임이 0건이었다(2026-07-21 검수).
    주문조회(5초/1회 스로틀)는 안 돌고 클레임 4종만 걷는다. 업서트라 멱등.
    정산 조인은 켠다 — ESM 클레임 응답엔 단가·수량이 없어 정산이 유일한 실값이다.
    """
    if market not in _ESM_MARKETS:
        raise ValueError(f"ESM 마켓 아님: {market} (auction|gmarket)")
    from lemouton.markets import line_uid as _luid
    from lemouton.markets.order_export import (_account_client, _finalize_rows,
                                               esm_order_rows)
    cli = _account_client(market, prefix) if prefix else _account_client(market)
    if cli is None:
        raise RuntimeError(f"[{market}] API 키 미등록(prefix={prefix})")
    raw = esm_order_rows(market, start, end, client=cli, include_settlement=True,
                         claims_only=True, claim_to_now=False)
    _luid.stamp(market, raw)
    rows = _finalize_rows(raw)
    if alias:
        for r in rows:
            r["쇼핑몰별칭"] = alias
    st = _store.save(rows, session=session)
    st["fetched"] = len(rows)
    return st


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


def estimate(markets: Iterable[str], days: int = 365, *, backfill: bool = True) -> dict:
    """백필이 몇 번 호출될지 미리 알려준다(돌리기 전에 규모를 알 수 있게).

    ★ 기본이 backfill=True 다 — 이 함수의 호출자는 전부 백필이고, 증분 청크로 세면
    실제 계획(backfill_chunk_days)과 총 창수가 어긋나 진행률이 영영 100%가 안 된다
    (롯데온 365 vs 실제 13).
    """
    fn = backfill_chunk_days if backfill else chunk_days
    per = {m: -(-days // fn(m)) for m in markets}   # 올림
    return {"per_market": per, "total_windows": sum(per.values()), "days": days}
