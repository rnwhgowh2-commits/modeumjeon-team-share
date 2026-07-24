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
        from lemouton.markets.order_export import _account_client, _finalize_rows
        from shared.platforms.lotteon import settle_orders as _so
        rows = _so.order_rows(start, end, client=_acct_client(market, prefix))
        from lemouton.markets import line_uid as _luid
        _luid.stamp(market, rows)
        # ★ 이 경로만 _finalize_rows 를 안 태워서, 저장된 행에 파생열(상품금액·총주문금액·
        #   `정산예정금(배송비포함)`·수수료율)이 **통째로 없었다**(2026-07-24 실측: 롯데온
        #   빈 행 187건의 키 목록이 209 경로 행과 아예 다름). 다른 백필 분기는 전부 태운다.
        return _finalize_rows(rows)
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


def refresh_open_orders(market: str, *, days: int = 21, limit: int = 6,
                        session=None) -> dict:
    """**아직 안 끝난 주문이 있는 날짜만** 골라 다시 조회한다(상태·송장 최신화).

    왜 — 사장님 기준: 보통 3주 안에 구매확정·클레임으로 바뀌므로 최근 21일의
    주문상태·송장번호가 늘 최신이어야 한다. 그런데 스마트스토어·롯데온은
    **하루씩만** 조회할 수 있어(마켓 제한) 21일을 통째로 훑으면 창이 21개다.
    이미 끝난 주문은 값이 더 안 바뀌므로, 안 끝난 건이 남은 날짜만 다시 본다.

    한 틱에 limit 일까지만 처리한다 — 오래 안 본 날짜부터 가져가므로 다음 틱이
    나머지를 이어받아 자연히 돌아간다(특정 날짜가 굶지 않는다).
    """
    until = _dt.datetime.now(KST)
    since = until - _dt.timedelta(days=days)
    dates = _store.open_order_dates(
        market, since=since.strftime("%Y-%m-%d"), until=until.strftime("%Y-%m-%d"),
        limit=limit, session=session)
    total = {"orders_new": 0, "orders_updated": 0, "claims_new": 0,
             "claims_updated": 0, "skipped_no_uid": 0}
    errors: list[str] = []
    for d in dates:
        day = _dt.datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=KST)
        try:
            st = ingest_window(market, day, day + _dt.timedelta(days=1),
                               session=session)
            for k in total:
                total[k] += st.get(k, 0)
        except Exception as e:                       # noqa: BLE001
            msg = f"[{market}] {d} 미확정 재확인 실패: {type(e).__name__}: {e}"
            logger.warning(msg)
            errors.append(msg)
    return {"market": market, "dates": dates, **total, "errors": errors}


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
            _store.dedupe_short_uid_ghosts(session=session)
            _store.backfill_claim_dates_from_lines(session=session)
        else:
            from shared import db as _db
            if not getattr(_db, "_is_sqlite", False):
                _store.sync_status_from_claims()
                _store.dedupe_undated_claim_ghosts()
                _store.dedupe_short_uid_ghosts()
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


def ingest_coupang_dates_by_order_ids(ord_ids, *, session=None) -> dict:
    """쿠팡 취소주문 실주문일 채움 — 발주서 단건(orderId) 조회로 orderedAt 확보.

    쿠팡 클레임 응답엔 실주문일이 없어(builder 명시) 취소주문(클레임행만 존재)의
    주문일이 공란이다(2026-07-23 샵마인 전열 대조 537건). 계정을 순회하며 조회하고,
    빈 칸만 채운다(set_order_dates — 실값 보존·멱등). 못 찾은 id 는 그대로 돌려준다.
    """
    from lemouton.markets.order_export import _account_client, _active_accounts
    from shared.platforms.coupang.orders import fetch_ordersheets_by_order_id

    def _kst_str(iso: str) -> str:
        try:
            d = _dt.datetime.fromisoformat(str(iso))
            if d.tzinfo is not None:
                d = d.astimezone(KST)
            return d.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            return ""

    accounts = _active_accounts("coupang") or [(None, None)]
    remaining = [str(n).strip() for n in (ord_ids or []) if str(n).strip()]
    dates: dict = {}
    err_samples: list = []                # 진단용 — 전부 못 찾으면 원인을 보여야 한다
    for prefix, name in accounts:
        if not remaining:
            break
        cli = _account_client("coupang", prefix)
        if cli is None:
            continue
        for oid in list(remaining):
            try:
                resp = fetch_ordersheets_by_order_id(oid, client=cli)
            except Exception as e:                       # noqa: BLE001 — 이 계정에 없음
                if len(err_samples) < 3:
                    err_samples.append(f"{name}/{oid}: {type(e).__name__}: {str(e)[:160]}")
                continue
            data = resp.get("data") or []
            if isinstance(data, dict):
                data = [data]
            ordered = next((b.get("orderedAt") for b in data
                            if isinstance(b, dict) and b.get("orderedAt")), "")
            val = _kst_str(ordered) if ordered else ""
            if val:
                dates[oid] = val
                remaining.remove(oid)
            elif len(err_samples) < 3:
                err_samples.append(f"{name}/{oid}: 응답에 orderedAt 없음 "
                                   f"code={resp.get('code')} data={str(data)[:80]}")
    st = _store.set_order_dates("coupang", dates, session=session)
    return {"found": len(dates), "not_found": remaining,
            "err_samples": err_samples, **st}


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


def restore_eleven11_claim_gaps(days: int = 2, limit: int = 8, *,
                                session=None) -> dict:
    """주문 라인이 없는 최근 11번가 클레임의 원주문을 by-no 로 자동 복구.

    주문→취소완료가 고속 틱(20분) 사이에 끝나는 초고속 취소는 클레임 이벤트만 남고
    주문 라인 스냅샷이 없다 → 클레임 행의 주문일이 비어 「주문일 탭」에서 통째 빠진다
    (2026-07-23 샵마인 대조 실측 5건). 최근 days일 클레임 중 주문일 있는 라인이 없는
    주문번호를 골라 단건 조회로 원주문을 적재한다(호출 상한 limit — 계정×2회/주문).
    """
    own = False
    if session is None:
        from shared import db as _db
        if getattr(_db, "_is_sqlite", False):     # 폴백 SQLite = 테스트 잔재 오염 방지
            return {"targets": 0, "restored": 0}
        session = _db.SessionLocal()
        own = True
    try:
        from lemouton.markets.models_orders import MarketClaimEvent, MarketOrderLine
        cutoff = _dt.datetime.utcnow() - _dt.timedelta(days=days)
        onos = sorted({c.order_no for c in
                       session.query(MarketClaimEvent.order_no)
                       .filter(MarketClaimEvent.market == "eleven11",
                               MarketClaimEvent.first_seen_at >= cutoff).all()
                       if c.order_no})
        gaps = []
        for no in onos:
            has_line = (session.query(MarketOrderLine.line_uid)
                        .filter(MarketOrderLine.market == "eleven11",
                                MarketOrderLine.order_no == no,
                                MarketOrderLine.order_date != "").first())
            if has_line is None:
                gaps.append(no)
            if len(gaps) >= limit:
                break
        if not gaps:
            return {"targets": 0, "restored": 0}
        st = ingest_eleven11_orders_by_no(gaps, session=session)
        return {"targets": len(gaps),
                "restored": (st.get("orders_new", 0) + st.get("orders_updated", 0))}
    finally:
        if own:
            session.close()


_BLANKFILL_STAMP = "_blankfill_tried_at"      # 재시도 간격 표식(row JSON 안)


def _line_is_blank(row: dict) -> bool:
    """주문 라인이 '덜 채워졌나' — 상품명 또는 단가가 비었으면 True.

    0·'0' 도 빈 값으로 본다: 0원 주문·이름 없는 상품은 실재하지 않는다.
    (있는 그대로 0 을 믿으면 마진계산기가 판매가 0 → 마진율 0% 로 조용히 표시한다.)
    """
    for key in ("상품명", "단가"):
        v = str(row.get(key) or "").strip()
        if not v or v in ("0", "0.0", "0원"):
            return True
    return False


def ingest_lotteon_orders_by_no(od_nos, *, session=None) -> dict:
    """롯데온 주문번호 **단건 정밀 복구** — 계정을 순회하며 각 주문을 찾아 적재.

    209(출고/회수지시)는 「기간 또는 odNo」를 받는다. 정산 API 백필로만 들어온 주문은
    상품명·단가·주문상태가 통째로 빈 채 남는데(2026-07-24 실측 187건), 그 행들의
    유일한 복구 통로다. 못 찾은 주문번호는 숨기지 않고 돌려준다(조용한 실패 금지). 멱등.
    """
    import time as _time

    from lemouton.markets import line_uid as _luid
    from lemouton.markets.order_export import (_account_client, _active_accounts,
                                               _finalize_rows, lotteon_order_rows)
    now = _dt.datetime.now(KST)
    accounts = _active_accounts("lotteon") or [(None, None)]
    remaining = [str(n).strip() for n in (od_nos or []) if str(n).strip()]
    found: dict = {}
    stat_sum = {"orders_new": 0, "orders_updated": 0, "claims_new": 0,
                "claims_updated": 0, "skipped_no_uid": 0}
    for prefix, name in accounts:
        if not remaining:
            break
        cli = _account_client("lotteon", prefix) if prefix else _account_client("lotteon")
        if cli is None:
            continue
        hit_rows = []
        for no in list(remaining):
            try:
                # 창은 넓게(1년) — odNo 조회라 창이 넓어도 스캔이 아니라 단건이다.
                raw = lotteon_order_rows(now - _dt.timedelta(days=365), now, client=cli,
                                         include_settlement=False, orders_to_now=False,
                                         od_no=no)
            except Exception:                        # noqa: BLE001 — 이 계정 키로는 조회불가
                raw = []
            if not raw:
                continue
            _luid.stamp("lotteon", raw)
            rows = _finalize_rows(raw)
            for r in rows:
                r["쇼핑몰별칭"] = name or ""
            hit_rows += rows
            found[no] = name or ""
            remaining.remove(no)
            _time.sleep(0.3)                         # 롯데온 연타 금지
        if hit_rows:
            st = _store.save(hit_rows, session=session)
            for k in stat_sum:
                stat_sum[k] += st.get(k, 0)
    return {"found": found, "not_found": remaining, **stat_sum}


# 마켓 → 주문번호 단건 복구 함수 **이름**. 이름으로 두는 이유: 테스트가 모듈 속성을
#  monkeypatch 할 때 함수 객체를 미리 잡아두면 패치가 안 먹는다.
_BY_NO_INGEST = {
    "eleven11": "ingest_eleven11_orders_by_no",
    "lotteon": "ingest_lotteon_orders_by_no",
}


def restore_blank_orders(market: str, days: int = 45, limit: int = 8,
                         retry_hours: int = 24, *, session=None) -> dict:
    """상품명·단가가 빈 주문 라인을 주문번호 **단건 조회**로 채운다(마켓 공통).

    ■ 왜 마켓마다 빈 행이 생기나 (2026-07-24 실측)
      · 11번가 — 「배송중」 목록이 송장·주문번호만 준다(상품명·단가·수령자·정산 없음).
        결제완료 시절 스냅샷이 저장분에 있으면 채워지지만, 주문→발송이 수집 틱 사이에
        끝난 주문은 빈 채로 남는다. 마진계산기에서 매입 36,490원이 판매가 0·마진율
        0.0% 로 떴다(실제는 역마진).
      · 롯데온 — 정산 API 백필(`lotteon_settle`)로만 들어온 라인이 상품명·단가·주문상태
        까지 통째로 비어 있다(저장분 187건). 키 목록이 209 경로 행과 아예 다르다.

    ■ 단건 조회는 전부 준다
      11번가 110 = ordDt·prdNm·selPrc·stlPlnAmt / 롯데온 209(odNo) = 상품·금액·수령자.

    ★ 「오래 안 본 순」 자가치유(refresh_eleven11_stale_settles)가 이걸 못 잡는다 —
      이 행들은 매 틱 목록에 다시 잡혀 last_seen_at 이 늘 최신이다. **비어 있음** 자체를
      기준으로 골라야 한다.
    ★ 굶김 방지: 단건 조회로도 못 채우는 주문(계정 키 없음·삭제 등)이 앞자리를 계속
      차지하면 뒤 주문은 영영 안 본다. 시도한 라인에 시각을 새기고 retry_hours 안에는
      건너뛴다(성공하면 채워져서 애초에 대상에서 빠진다).
    """
    fn_name = _BY_NO_INGEST.get(market)
    if not fn_name:
        raise ValueError(f"단건 복구를 지원하지 않는 마켓: {market} "
                         f"({'|'.join(sorted(_BY_NO_INGEST))})")
    own = False
    if session is None:
        from shared import db as _db
        if getattr(_db, "_is_sqlite", False):     # 폴백 SQLite = 테스트 잔재 오염 방지
            return {"targets": 0, "filled_lines": 0}
        session = _db.SessionLocal()
        own = True
    try:
        from sqlalchemy.orm.attributes import flag_modified

        from lemouton.markets.models_orders import MarketOrderLine
        date_lo = (_dt.datetime.now(KST) - _dt.timedelta(days=days)).strftime("%Y-%m-%d")
        retry_cut = _dt.datetime.utcnow() - _dt.timedelta(hours=retry_hours)
        rows = (session.query(MarketOrderLine)
                .filter(MarketOrderLine.market == market,
                        MarketOrderLine.order_date >= date_lo)
                .order_by(MarketOrderLine.order_date.desc()).all())
        onos, targets = [], []
        for o in rows:
            if not o.order_no or o.order_no in onos:
                continue
            row = o.row or {}
            if not _line_is_blank(row):
                continue
            tried = str(row.get(_BLANKFILL_STAMP) or "")
            if tried:
                try:
                    if _dt.datetime.fromisoformat(tried) > retry_cut:
                        continue              # 최근에 시도함 — 다음 주문에 자리를 준다
                except ValueError:
                    pass                      # 표식이 깨졌으면 그냥 시도한다
            onos.append(o.order_no)
            targets.append(o)
            if len(onos) >= limit:
                break
        if not onos:
            return {"targets": 0, "filled_lines": 0}
        stamp = _dt.datetime.utcnow().isoformat(timespec="seconds")
        for o in targets:
            o.row = {**(o.row or {}), _BLANKFILL_STAMP: stamp}
            flag_modified(o, "row")
        session.commit()
        target_uids = {o.line_uid for o in targets}
        st = globals()[fn_name](onos, session=session)
        # 실제로 채워졌는지 다시 읽어 센다 — '조회했다'와 '채워졌다'는 다르다.
        # ★ **겨눈 그 라인**만 센다. 예전엔 주문번호로 아무 라인이나 세서, 복구분이
        #   다른 키로 새 행이 되어 빈 껍데기가 그대로 남아도 '채웠다'고 보고했다
        #   (2026-07-24 롯데온 실측: 204줄 '채움'인데 공란 187건 그대로·행 +158).
        after = (session.query(MarketOrderLine)
                 .filter(MarketOrderLine.market == market,
                         MarketOrderLine.order_no.in_(onos)).all())
        by_uid = {o.line_uid: o for o in after}
        filled = sum(1 for u in target_uids
                     if u in by_uid and not _line_is_blank(by_uid[u].row or {}))
        # 복구분이 **더 긴 키**로 들어온 경우(롯데온 sitmNo 등) — 겨눈 껍데기는 그대로
        # 빈 채 남고 실데이터는 형제 행에 있다. 정리는 dedupe_short_uid_ghosts 가 한다.
        superseded = sum(1 for u in target_uids
                         if u in by_uid and _line_is_blank(by_uid[u].row or {})
                         and any(o.line_uid.startswith(u + "|") for o in after))
        return {"targets": len(onos), "filled_lines": filled,
                "superseded": superseded,
                "not_found": st.get("not_found") or []}
    finally:
        if own:
            session.close()


def restore_eleven11_blank_orders(days: int = 45, limit: int = 8,
                                  retry_hours: int = 24, *,
                                  session=None) -> dict:
    """상품명·단가가 빈 11번가 주문 라인을 by-no 단건 조회로 채운다.

    11번가 **배송중 목록은 송장·주문번호만 준다** — 상품명·단가·수령자·정산이 통째로
    없다(`shared/platforms/eleven11/orders.py` iter_shipping 실측 주석). 결제완료 시절
    스냅샷이 저장분에 있으면 `fill_claim_blanks_from_history` 가 채우지만, 주문→발송이
    수집 틱 사이에 끝나 스냅샷이 없던 주문은 **빈 채로 남는다**.
      2026-07-24 라이브 실측 2건 — 마진계산기에서 매입 36,490·61,945원짜리가 판매가 0·
      마진율 0.0% 로 떴다(실제는 역마진인데 손실 배지도, 블랙스팟도 안 붙었다).
    단건 조회(eleven11.110)는 ordDt·prdNm·selPrc·stlPlnAmt 를 다 준다 — 같은 2건을
    수동 복구했더니 단가 48,700/정산 44,025 · 단가 71,500/정산 65,778 로 전부 채워졌다.

    ★ `refresh_eleven11_stale_settles` 가 이걸 못 잡는 이유: 그건 「오래 안 본 순」인데
      이 행들은 매 틱 배송중 목록에 다시 잡혀 last_seen_at 이 늘 최신이다. 그래서
      **비어 있음** 자체를 기준으로 따로 골라야 한다.

    ★ 굶김 방지: 단건 조회로도 못 채우는 주문(계정 키 없음·삭제 등)이 앞자리를 계속
      차지하면 뒤 주문은 영영 안 본다. 시도한 라인에 시각을 새기고 retry_hours 안에는
      건너뛴다(성공하면 채워져서 애초에 대상에서 빠진다).

    (본체는 마켓 공통 `restore_blank_orders` — 이 이름은 호출부·테스트 호환용 얇은 껍질.)
    """
    return restore_blank_orders("eleven11", days=days, limit=limit,
                                retry_hours=retry_hours, session=session)


def refresh_eleven11_stale_settles(days: int = 10, limit: int = 8,
                                   min_age_hours: int = 12, *,
                                   session=None) -> dict:
    """배송중·배송완료·구매확정 최근 주문의 낡은 정산 스냅샷을 by-no 재조회로 갱신.

    11번가는 배송 후에도 stlPlnAmt(정산예정금)를 갱신한다(T-쿠폰 등 — 2026-07-23
    샵마인 대조 실측 ±610~1,347원). 배송완료·구매확정 목록 조회는 stlPlnAmt 를 안 줘
    저장분 스냅샷이 정본인데, 스냅샷이 결제완료 시점이면 낡은 값이 남는다.
    최근 days일 주문 중 min_age_hours 이상 안 본 순으로 limit 개씩 단건 재조회.
    (배송준비중·결제완료는 목록 조회가 매 틱 갱신하므로 제외.)
    """
    own = False
    if session is None:
        from shared import db as _db
        if getattr(_db, "_is_sqlite", False):     # 폴백 SQLite = 테스트 잔재 오염 방지
            return {"targets": 0, "refreshed": 0}
        session = _db.SessionLocal()
        own = True
    try:
        from lemouton.markets.models_orders import MarketOrderLine
        seen_cut = _dt.datetime.utcnow() - _dt.timedelta(hours=min_age_hours)
        date_lo = (_dt.datetime.now(KST) - _dt.timedelta(days=days)).strftime("%Y-%m-%d")
        rows = (session.query(MarketOrderLine)
                .filter(MarketOrderLine.market == "eleven11",
                        MarketOrderLine.order_date >= date_lo,
                        MarketOrderLine.status.in_(("배송중", "배송완료", "구매확정")),
                        MarketOrderLine.last_seen_at < seen_cut)
                .order_by(MarketOrderLine.last_seen_at.asc())
                .limit(limit * 3).all())          # 다품 라인 여유(주문번호로 접음)
        onos = []
        for o in rows:
            if o.order_no and o.order_no not in onos:
                onos.append(o.order_no)
            if len(onos) >= limit:
                break
        if not onos:
            return {"targets": 0, "refreshed": 0}
        st = ingest_eleven11_orders_by_no(onos, session=session)
        return {"targets": len(onos),
                "refreshed": (st.get("orders_new", 0) + st.get("orders_updated", 0))}
    finally:
        if own:
            session.close()


# ── 정산만 다시 훑기(옥션·G마켓) ──────────────────────────────────────────────
#
# 🔴 왜 필요한가 — **정산은 구매확정 뒤에 확정되는데, 우리는 끝난 주문을 다시 안 본다.**
#   ESM 증분 수집은 최근 21일(_WIDE_DAYS)만 훑는다. G마켓 실측(2026-07-25):
#     주문 2026-07-01 → 07-21 마지막 관측(그때는 아직 미정산) → 21일 창이 닫힘
#     → 07-25 현재 마켓엔 실정산 69,530 이 들어와 있는데 우리 저장분은 추정치로 고착.
#   같은 지문 43건(2026-04~07). 지금은 추정이 실값과 우연히 같았지만(상품별 실효
#   수수료율을 쓰므로), 계약율이 바뀌는 상품에선 조용히 어긋난다.
#
# ★ **주문은 다시 안 부른다** — 정산조회 API 만 훑는다(주문조회 대비 호출 1/N).
#   정산조회 응답이 이미 주문번호(ContrNo)별 정산액을 주므로 그것만 저장분에 얹는다.
# ★ **계정별로 물어야 한다** — 2026-07-25 실측: 대표 계정으로 07-01~07-05 를 물으면
#   2건뿐이고 찾는 주문이 없다. 같은 창을 「브랜드위시」로 물으면 4건 전부 나온다.
#   계정을 안 나누면 「마켓에 정산이 없다」는 잘못된 결론에 도달한다.
ESM_SETTLE_SWEEP_DAYS = 60      # 이만큼 과거까지 훑는다(정산 확정 지연 여유)
ESM_SETTLE_SWEEP_SKIP_DAYS = 7  # 최근 이 기간은 증분 수집이 이미 덮으므로 건너뛴다


def _esm_settlement_clients(market: str) -> list:
    """[(계정명, client)] — 등록된 활성 계정 전부. 같은 셀러 중복은 접는다.

    `order_export.order_rows` 의 계정 열거와 같은 규약(키 미등록 건너뜀·동일 자격증명
    1회). 대표 계정만 물으면 다른 계정 주문의 정산을 통째로 못 본다(위 주석 실측).
    """
    from lemouton.markets.order_export import (_account_client, _active_accounts,
                                               _client_identity)
    built, seen = [], {}
    for prefix, name in _active_accounts(market):
        cli = _account_client(market, prefix)
        if cli is None:
            continue                              # 키 미등록 — 대표계정 폴백 금지(중복 계상)
        ident = _client_identity(market, cli)
        if ident is not None and ident in seen:
            continue                              # 같은 셀러가 두 번 등록됨
        if ident is not None:
            seen[ident] = name
        built.append((name, cli))
    if not built:
        cli = _account_client(market)
        if cli is not None:
            built.append(("", cli))
    return built


def refresh_settlement(market: str, *, since=None, until=None,
                       days: int = ESM_SETTLE_SWEEP_DAYS,
                       skip_days: int = ESM_SETTLE_SWEEP_SKIP_DAYS,
                       session=None) -> dict:
    """옥션·G마켓 저장분의 **정산액만** 마켓 실값으로 갱신한다(주문 조회 없음).

    · 대상 = 아직 실정산(`_settle_source='real'`)이 아닌 주문 행. 클레임 행은 제외
      (취소·반품 정산은 zero_cancel·실정산 조인이 담당 — 여기서 건드리면 날조).
    · 값이 같으면 아무것도 안 한다(무의미한 쓰기·last_seen_at 갱신 방지).
    · 정산조회에 없는 주문은 **그대로 둔다** — 없는 값을 0 으로 채우지 않는다.
    Returns 집계 dict(숨기지 않는다).
    """
    if market not in ("auction", "gmarket"):
        raise ValueError(f"옥션·G마켓 전용이에요: {market}")
    now = _dt.datetime.now(KST)
    if until is None:
        until = now - _dt.timedelta(days=max(0, skip_days))
    if since is None:
        since = now - _dt.timedelta(days=max(1, days))
    stat = {"market": market, "accounts": 0, "settle_rows": 0,
            "targets": 0, "updated": 0, "errors": []}

    from shared.platforms.esm.settlements import settle_detail_map
    smap: dict = {}
    for name, cli in _esm_settlement_clients(market):
        stat["accounts"] += 1
        srch = (getattr(cli, "_cfg", {}) or {}).get("settle_srch_type", "D1")
        try:
            got = settle_detail_map(market, since, until, client=cli, srch_type=srch)
        except Exception as e:   # noqa: BLE001 — 한 계정이 막혀도 나머지는 진행
            msg = f"[{market}·{name or '대표'}] 정산조회 실패: {type(e).__name__}: {e}"
            logger.warning(msg)
            stat["errors"].append(msg)
            continue
        for k, v in got.items():
            if v.get("정산예정금액") is not None:
                smap.setdefault(k, v)
    stat["settle_rows"] = len(smap)
    if not smap:
        return stat

    own = False
    if session is None:
        from shared import db as _db
        if getattr(_db, "_is_sqlite", False):     # 폴백 SQLite = 테스트 잔재 오염 방지
            return stat
        session = _db.SessionLocal()
        own = True
    try:
        from lemouton.markets.models_orders import MarketOrderLine
        from lemouton.markets.order_export import _finalize_rows
        lo, hi = since.strftime("%Y-%m-%d"), until.strftime("%Y-%m-%d") + " 99"
        lines = (session.query(MarketOrderLine)
                 .filter(MarketOrderLine.market == market,
                         MarketOrderLine.order_date >= lo,
                         MarketOrderLine.order_date <= hi).all())
        for o in lines:
            row = dict(o.row or {})
            if str(row.get("_kind") or "") == "change":
                continue                          # 클레임 정산은 여기서 손대지 않는다
            if str(row.get("_settle_source") or "") == "real":
                continue                          # 이미 실정산
            ent = smap.get(str(row.get("오픈마켓주문번호") or "").strip())
            if not ent:
                continue                          # 정산조회에 없음 = 아직 미정산(그대로 둠)
            amt = ent.get("정산예정금액")
            stat["targets"] += 1
            row["정산예정금액"] = amt
            row["_settle_source"] = "real"
            _finalize_rows([row])
            o.row = row                           # 새 dict 대입 — JSON 컬럼 변경 감지
            o.last_seen_at = _store._now()
            stat["updated"] += 1
        session.commit()
    finally:
        if own:
            session.close()
    return stat
