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
    나머지 계정의 과거가 통째 빠졌다(2026-07-22 정답지 대사: 누락 605건 최대 원인).
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


# ── 「창 밖에서 굳은 미확정 주문」 되찾기 ────────────────────────────────
#  🔴 2026-08-02 라이브 실측으로 드러난 것: 롯데온 저장분에 **'주문'(=결제 직후)
#     상태로 굳은 554건**이 있었고, 주문일이 **전부 2026-03(483)·04(71)월**이었다.
#     5~7월은 0건 — 즉 최근 것은 잘 따라잡는데 옛것만 통째로 멈춰 있었다.
#     원인: 아래 재확인이 **최근 21일만** 본다. 3~4월분은 과거 백필로 들어온 뒤
#     21일 창을 이미 지나 있어서 다시 볼 기회가 영영 없었다. 에러는 안 난다 —
#     실패가 아니라 「안 본 것」이라 로그도 경보도 남지 않는다(정산 스윕 #481 과 같은 부류).
#  ★고치는 방식 = 창을 넓히는 게 아니라 **차선을 하나 더 두는 것**.
#     창만 넓히면 '오래 안 본 순' 정렬 때문에 옛 날짜가 매 틱을 차지해 최근 21일이
#     굶는다. 게다가 영영 안 끝나는 주문(마켓이 더는 안 주는 유령)이 하나라도 있으면
#     그 날짜가 영구히 앞자리를 잡는다. 그래서 옛 구간은 **틱당 stale_limit 개만**
#     가져간다 — 최근 차선은 그대로 두고, 밀린 것은 여러 틱에 걸쳐 천천히 녹는다.
#  🔴🔴 2026-09-06 재발 — STALE_OPEN_DAYS=180 이 **고정 절벽**이었다. 08-02 수정
#     직후엔 3~4월분(그때 21~180일 구간)이 이 차선으로 실제로 다 해소됐지만, 시간이
#     지나 2월 주문이 180일을 넘기며(215일) 21일 차선에도 180일 차선에도 안 걸리는
#     "차선 밖"으로 새로 떨어졌다(마진계산기 기타 카드 116건 실사로 발견). 즉 이
#     상한이 있는 한 매달 그만큼 오래된 주문이 계속 새로 굳는다 — 절벽이 밀려올
#     뿐 없어지지 않는다. `open_order_dates` 는 "아직 안 끝난 주문이 있는 날짜"만
#     쿼리 한 번으로 골라내므로(범위를 넓혀도 실제 열린 날짜 수만큼만 비용이 든다),
#     상한을 사실상 무제한으로 늘려도 안전하다 — stale_limit 이 틱당 비용을 계속
#     막아준다. 그래서 창을 넓히지 않는 대신 **상한 자체를 치운다**(10년 = 사실상
#     무제한). 이제 아무리 오래된 주문도 언젠가는(stale_limit 속도로) 재확인된다.
STALE_OPEN_DAYS = 3650       # 옛 차선이 훑는 범위(주문일 기준) — 사실상 무제한(10년)
STALE_OPEN_LIMIT = 3         # 틱당 옛 날짜 처리 개수 — 최근 차선을 밀어내지 않을 만큼만


def refresh_open_orders(market: str, *, days: int = 21, limit: int = 6,
                        stale_days: int = STALE_OPEN_DAYS,
                        stale_limit: int = STALE_OPEN_LIMIT,
                        session=None) -> dict:
    """**아직 안 끝난 주문이 있는 날짜만** 골라 다시 조회한다(상태·송장 최신화).

    왜 — 사장님 기준: 보통 3주 안에 구매확정·클레임으로 바뀌므로 최근 21일의
    주문상태·송장번호가 늘 최신이어야 한다. 그런데 스마트스토어·롯데온은
    **하루씩만** 조회할 수 있어(마켓 제한) 21일을 통째로 훑으면 창이 21개다.
    이미 끝난 주문은 값이 더 안 바뀌므로, 안 끝난 건이 남은 날짜만 다시 본다.

    한 틱에 limit 일까지만 처리한다 — 오래 안 본 날짜부터 가져가므로 다음 틱이
    나머지를 이어받아 자연히 돌아간다(특정 날짜가 굶지 않는다).

    차선 둘(위 STALE_OPEN_DAYS 주석 참조):
      · 최근 = 최근 days 일 중 미확정 날짜 limit 개
      · 옛것 = days~stale_days 구간 미확정 날짜 stale_limit 개(틱당 소량)
    `stale_limit=0` 이면 옛 차선을 끈다(테스트·수동 호출용).
    """
    until = _dt.datetime.now(KST)
    since = until - _dt.timedelta(days=days)
    u_s = until.strftime("%Y-%m-%d")
    dates = _store.open_order_dates(
        market, since=since.strftime("%Y-%m-%d"), until=u_s,
        limit=limit, session=session)
    stale_dates: list[str] = []
    if stale_limit > 0 and stale_days > days:
        # 옛 구간의 끝 = 최근 구간의 시작 하루 전(겹쳐서 같은 날을 두 번 조회하지 않게).
        s_since = (until - _dt.timedelta(days=stale_days)).strftime("%Y-%m-%d")
        s_until = (since - _dt.timedelta(days=1)).strftime("%Y-%m-%d")
        if s_since <= s_until:
            stale_dates = _store.open_order_dates(
                market, since=s_since, until=s_until,
                limit=stale_limit, session=session)
        dates = list(dates) + stale_dates
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
    return {"market": market, "dates": dates, "stale_dates": stale_dates,
            **total, "errors": errors}


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
    (2026-07-22 정답지 대사: 취소완료 계열 233건). 209 없이 클레임 3종만 걷는다.
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
    정본(2026-07-22 정답지 전열 대조: 구매자 정보 공란 792). orders_to_now=False 로
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
    주문일이 공란이다(2026-07-23 정답지 전열 대조 537건). 계정을 순회하며 조회하고,
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
    2026-07-22 정답지 대사 잔여 26건)의 마지막 통로. 찾은 계정의 별칭을 새기고,
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
    (2026-07-23 정답지 대조 실측 5건). 최근 days일 클레임 중 주문일 있는 라인이 없는
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


_STALESTAT_STAMP = "_stalestat_tried_at"       # 굳은 상태 재조회 간격 표식(row JSON 안)
# 「이 상태로 오래 있으면 이상하다」 — 배송이 끝났으면 대개 8일 안에 자동 구매확정된다.
_STALE_STATUSES = ("배송완료", "배송중", "배송준비중")


def _ship_settle_plan(lines, deliv: dict, oid_of) -> dict:
    """[2026-08-13] 스윕용 — 배송건별 **담당 줄**을 정해 `{id(행): 실을 값}` 을 만든다.

    🔴 왜 스윕이 따로 정해야 하나 — 스윕은 행을 **한 줄씩** `_finalize_rows([row])` 에
      넣는다. `_shipkey`(배송건 열쇠)는 저장할 때 이미 pop 돼 행에 없으므로,
      `_finalize_rows` 의 「배송건당 1회」 중복 제거가 **한 번도 안 걸린다**.
      스윕이 담당을 안 정해 주면 다품 주문에서 배송비 정산이 줄 수만큼 곱해진다.

    담당 = **이미 고객배송비를 지고 있는 줄**. 저장할 때 `_finalize_rows` 가 배송비와
      `_ship_settle` 을 같은 줄(`sk` 가 처음 나온 줄)에 몰아 뒀으므로, 그 줄이 곧
      예전 담당이다 — 담당이 옮겨 다니지 않아야 저장분 병합에서 두 번 세어지지 않는다.
      아무도 안 지고 있으면(무료배송) 이미 `_ship_settle` 을 가진 줄, 그것도 없으면
      안정 정렬(line_uid) 첫 줄. **정렬 없이 DB 순서에 맡기면 조회마다 담당이 바뀐다.**

    🔴 나머지 줄엔 `0` — pop 이 아니라 **명시 대입**한다. `order_store._merge_row` 는
      새 payload 에 없는 키를 못 지워, pop 하면 저장분에 옛 값이 살아남는다
      (2026-08-12 에 인라인 경로에서 실제로 잡힌 함정 · `2e2cc8a7`).
    """
    from lemouton.markets import line_uid as _L
    from lemouton.markets.order_export import _to_int
    by_oid: dict = {}
    for o in lines:
        row = o.row or {}
        if str(row.get("_kind") or "") == "change":
            continue                          # 클레임 정산은 딴 경로 — 손대지 않는다
        oid = oid_of(row)
        if not oid or oid not in deliv:
            continue
        by_oid.setdefault(oid, []).append(o)
    plan: dict = {}
    for oid, group in by_oid.items():
        group.sort(key=lambda g: str((g.row or {}).get(_L.FIELD) or ""))
        owner = next((g for g in group
                      if (_to_int((g.row or {}).get("배송비"), 0) or 0) > 0), None)
        if owner is None:
            owner = next((g for g in group
                          if (_to_int((g.row or {}).get("_ship_settle"), 0) or 0) > 0),
                         group[0])
        for g in group:
            plan[id(g)] = deliv[oid] if g is owner else 0
    return plan


def refresh_stale_delivered(market: str, min_age_days: int = 30,
                            max_age_days: int = 180, limit: int = 30,
                            retry_hours: int = 72, *, session=None) -> dict:
    """오래도록 「배송완료」에 굳어 있는 주문을 **주문번호 단건 조회**로 되살린다.

    🚨🚨 [2026-08-12 철회] **자동 실행 금지.** 진단·수동 확인 전용으로만 남긴다.
      라이브 30건을 돌려 보니 **30건 전부 상태가 뒤로 갔다**:
        배송완료→출고지시 24 · 배송완료→회수지시 6
      롯데온 단건 조회는 같은 상품라인을 **단계별 여러 행**으로 주고, 나중에 처리된
      행이 상태를 덮어써 시간이 거꾸로 흐른다. 이 사실은 이미 실측으로 적혀 있었다
      (`margin/sell_source.py:_one_row_per_line` — 「출고지시 37,599 + 배송완료 38,505」).
      **나는 그 주석을 안 읽고 배선했다.** 다행히 스케줄러가 한 번도 안 돌아
      882건이 온전했다(진단: 이미시도한건수 0).
      ★ 「낡은 상태」는 상태 되조회로 못 고친다 — **정산 사실로 판정**해야 한다
        (롯데온 지급내역 seCmptDt 조인 = `lemouton/margin/lotteon_paid.py`).


    🔴🔴 왜(2026-08-08 라이브) — 롯데온 3,941만원의 정체가 이것이었다. 3~6월 결제인데
      아직 「배송완료」로 남은 622건. 「입금 확인 창구가 없다」가 아니라 **주문 상태가
      낡은 것**이었다. 배송이 끝났으면 보통 8일 안에 자동 구매확정되므로, 30일이 지나도
      배송완료면 마켓에선 이미 구매확정·정산이 끝났는데 우리만 못 따라간 것이다.

    ■ 왜 목록 조회로는 영영 안 잡히나
      우리 주문 갱신은 **최근 21일 창**만 본다. 그 창을 지나 상태가 바뀐 주문은 목록에
      다시 안 나오고, 우리 저장분은 마지막으로 본 상태 그대로 굳는다. 아무도 에러를
      내지 않으므로 **조용히** 틀린다(정산예정 총액이 계속 「받을 돈」에 남는다).

    ■ 왜 「비어 있음」 자가치유(restore_blank_orders)가 이걸 못 잡나
      이 행들은 상품명·단가가 **멀쩡히 차 있다**. 비어 있는 게 아니라 **낡았다**.
      그래서 고르는 기준이 다르다 — 상태 + 나이.

    ★ 굶김 방지: 되조회해도 안 바뀌는 주문(마켓이 정말 배송완료로 두는 경우)이 앞자리를
      계속 차지하지 않도록 시도 시각을 새기고 retry_hours 안에는 건너뛴다.
    ★ max_age_days 로 상한을 둔다 — 마켓 단건 조회도 무한 과거를 주지는 않는다.
    """
    fn_name = _BY_NO_INGEST.get(market)
    if not fn_name:
        raise ValueError(f"단건 조회를 지원하지 않는 마켓: {market} "
                         f"({'|'.join(sorted(_BY_NO_INGEST))})")
    own = False
    if session is None:
        from shared import db as _db
        if getattr(_db, "_is_sqlite", False):     # 폴백 SQLite = 테스트 잔재 오염 방지
            return {"targets": 0, "changed": 0}
        session = _db.SessionLocal()
        own = True
    try:
        from sqlalchemy.orm.attributes import flag_modified

        from lemouton.markets.models_orders import MarketOrderLine
        now = _dt.datetime.now(KST)
        newest = (now - _dt.timedelta(days=min_age_days)).strftime("%Y-%m-%d")
        oldest = (now - _dt.timedelta(days=max_age_days)).strftime("%Y-%m-%d")
        retry_cut = _dt.datetime.utcnow() - _dt.timedelta(hours=retry_hours)
        rows = (session.query(MarketOrderLine)
                .filter(MarketOrderLine.market == market,
                        MarketOrderLine.status.in_(_STALE_STATUSES),
                        MarketOrderLine.order_date >= oldest,
                        MarketOrderLine.order_date <= newest)
                .order_by(MarketOrderLine.order_date.asc()).all())   # 오래된 것부터
        onos, targets, before = [], [], {}
        for o in rows:
            if not o.order_no or o.order_no in onos:
                continue
            row = o.row or {}
            tried = str(row.get(_STALESTAT_STAMP) or "")
            if tried:
                try:
                    if _dt.datetime.fromisoformat(tried) > retry_cut:
                        continue
                except ValueError:
                    pass
            onos.append(o.order_no)
            targets.append(o)
            before[o.line_uid] = o.status or ""
            if len(onos) >= limit:
                break
        if not onos:
            return {"targets": 0, "changed": 0}
        stamp = _dt.datetime.utcnow().isoformat(timespec="seconds")
        for o in targets:
            o.row = {**(o.row or {}), _STALESTAT_STAMP: stamp}
            flag_modified(o, "row")
        session.commit()
        st = globals()[fn_name](onos, session=session)
        # 「조회했다」와 「바뀌었다」는 다르다 — 다시 읽어 상태 변화만 센다.
        after = (session.query(MarketOrderLine)
                 .filter(MarketOrderLine.market == market,
                         MarketOrderLine.order_no.in_(onos)).all())
        moved = {}
        for o in after:
            was = before.get(o.line_uid)
            if was is not None and (o.status or "") != was:
                moved[f"{was}→{o.status or '(공란)'}"] = \
                    moved.get(f"{was}→{o.status or '(공란)'}", 0) + 1
        return {"targets": len(onos), "changed": sum(moved.values()),
                "moves": moved, "not_found": st.get("not_found") or []}
    finally:
        if own:
            session.close()


def refresh_eleven11_stale_settles(days: int = 10, limit: int = 8,
                                   min_age_hours: int = 12, *,
                                   session=None) -> dict:
    """배송중·배송완료·구매확정 최근 주문의 낡은 정산 스냅샷을 by-no 재조회로 갱신.

    11번가는 배송 후에도 stlPlnAmt(정산예정금)를 갱신한다(T-쿠폰 등 — 2026-07-23
    정답지 대조 실측 ±610~1,347원). 배송완료·구매확정 목록 조회는 stlPlnAmt 를 안 줘
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

    # ── 정산조회: 계정 단위로 **병렬** (rate 버킷 = seller 계정별) ───────────────
    #  🔴 최대속도 전략 — ESM 5초/1콜 제한은 주문조회 전용이고, 걸리더라도 seller
    #     계정별이다. 서로 다른 계정은 완전 독립 버킷이라 **계정 수만큼 동시**가 이론상
    #     최대치다(같은 계정 안을 더 쪼개 병렬해 봤자 같은 버킷 → 3000 만 유발, 무의미).
    #     365일·6계정 직렬 = 약 72초(72콜×1초)라 Cloudflare 100초에 아슬아슬했는데,
    #     계정 병렬이면 워커당 12창 = 약 12초. 창(31일)은 워커 안에서 직렬 유지 —
    #     서버측 계정 한도(있다면)를 존중하고, 3000 은 settlements 가 백오프로 흡수한다.
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from shared.platforms.esm.settlements import settle_detail_map
    clients = _esm_settlement_clients(market)
    stat["accounts"] = len(clients)
    smap: dict = {}

    def _fetch_one(name, cli):
        srch = (getattr(cli, "_cfg", {}) or {}).get("settle_srch_type", "D1")
        return name, settle_detail_map(market, since, until, client=cli, srch_type=srch)

    if clients:
        with ThreadPoolExecutor(max_workers=min(len(clients), 8)) as ex:
            futs = {ex.submit(_fetch_one, name, cli): name for name, cli in clients}
            for fut in as_completed(futs):
                try:
                    _name, got = fut.result()
                except Exception as e:   # noqa: BLE001 — 한 계정이 막혀도 나머지는 진행
                    msg = (f"[{market}·{futs[fut] or '대표'}] 정산조회 실패: "
                           f"{type(e).__name__}: {e}")
                    logger.warning(msg)
                    stat["errors"].append(msg)
                    continue
                for k, v in got.items():
                    # 금액이 없어도 날짜(송금일=지급확인·정산예정일)는 유효 정보다 —
                    # 정산예정금액 탭이 지급 여부·기간 배치에 쓴다.
                    if (v.get("정산예정금액") is not None or v.get("정산예정일")
                            or v.get("송금일")):
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
            ent = smap.get(str(row.get("오픈마켓주문번호") or "").strip())
            if not ent:
                continue                          # 정산조회에 없음 = 아직 미정산(그대로 둠)
            changed = False
            # ── 날짜는 real 여부와 무관하게 채운다(백필 겸용) — 금액 규약은 불변 ──
            #  정산예정일 = 지급예정일 실값 / 송금일 = 실지급 확인(_settle_paid_date).
            #  이미 real 인 행도 날짜가 새로 오면 얹는다(2026-08-06 정산예정금액 탭).
            for src_k, dst_k in (("정산예정일", "정산예정일"),
                                 ("송금일", "_settle_paid_date")):
                v = ent.get(src_k)
                if v and row.get(dst_k) != v:
                    row[dst_k] = v
                    changed = True
            if str(row.get("_settle_source") or "") != "real":
                amt = ent.get("정산예정금액")
                if amt is not None:
                    stat["targets"] += 1
                    row["정산예정금액"] = amt
                    row["_settle_source"] = "real"
                    changed = True
            if not changed:
                continue                          # 값이 같으면 안 쓴다(무의미한 쓰기 방지)
            _finalize_rows([row])
            o.row = row                           # 새 dict 대입 — JSON 컬럼 변경 감지
            o.last_seen_at = _store._now()
            stat["updated"] += 1
        session.commit()
    finally:
        if own:
            session.close()
    return stat


# 롯데온 정산 스윕 — 쿠팡과 같은 인식일(구매확정일) 규칙, 조인 키만 odNo 단일.
LOTTEON_SETTLE_SWEEP_DAYS = 75      # 구매확정일 기준으로 이만큼 과거까지 훑는다
LOTTEON_SETTLE_SWEEP_SKIP_DAYS = 3  # 최근 이 기간은 적재틱이 이미 실값을 붙인다


def refresh_settlement_lotteon(*, since=None, until=None,
                               days: int = LOTTEON_SETTLE_SWEEP_DAYS,
                               skip_days: int = LOTTEON_SETTLE_SWEEP_SKIP_DAYS,
                               session=None) -> dict:
    """롯데온 저장분의 **정산액만** 마켓 실값으로 갱신한다(주문 조회 없음).

    🔴 왜 롯데온도 스윕이 필요한가 — 정산은 구매확정 뒤에 인식되는데(SettleItmdSales,
      정산기준일=구매확정일), 적재틱(7~21일)이 닫힌 뒤 구매확정된 옛 주문의 실정산이
      영영 안 들어와 추정치로 고착됐다(옥션·G마켓·쿠팡이 이미 닫은 그 갭).

    ★ 조인 키 = odNo 단일(인라인 조인 order_export 와 동형: itmd[odNo]['pymtAmt']를
      그 주문의 각 라인에 대입 — 쿠팡의 (주문번호,옵션ID) 복합키와 다르다).
    ★ 창은 **구매확정일(인식일) 기준**이라 '지금'에서 뒤로 잡는다. 주문일 창으로 물으면
      옛 주문의 새 정산을 영영 못 본다(쿠팡과 같은 이유).
    ★ 저장분 조회를 주문일로 제한하지 않는다 — 매칭 키(odNo)가 있는 행만 갱신되므로
      전 기간을 훑어도 엉뚱한 행을 건드리지 않는다.
    ★ rate 버킷이 계정별(50/s·분1만 여유)이라 계정 병렬이 안전(11번가·스스의 IP전역과 다름).
    ★ 정산조회에 없는 주문은 그대로 둔다 — 없는 값을 0 으로 채우지 않는다. 클레임 행 제외.

    🔴 원천이 **둘**이다(2026-08-02 추가):
      ① OpenAPI SettleProduct — 구매확정분만.
      ② 셀러오피스 크롤(lotteon_settlements) — **미정산 포함**. ①이 없는 구간의 유일 원천.
      ②가 우선(같은 라인이 양쪽에 있으면 크롤값). 다만 ②는 **양수만** 쓴다 — 본문 주석 참조.
    Returns 집계 dict(숨기지 않는다).
    """
    now = _dt.datetime.now(KST)
    if until is None:
        until = now - _dt.timedelta(days=max(0, skip_days))
    if since is None:
        since = now - _dt.timedelta(days=max(1, days))
    stat = {"market": "lotteon", "accounts": 0, "settle_rows": 0,
            "crawl_rows": 0, "targets": 0, "updated": 0,
            "zero_reverted": 0, "confirmed_marked": 0, "errors": []}

    # ── 정산조회: 계정 단위로 **병렬**(rate 버킷 = 계정별) — ESM 과 같은 전략 ──────
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from shared.platforms.lotteon import settlement as _lo_settle
    clients = _esm_settlement_clients("lotteon")
    stat["accounts"] = len(clients)
    smap: dict = {}
    # 🔴 [2026-08-12] 구매확정일(seStdDt)도 같이 받는다. 이 값이 롯데온 지급내역
    #   (실입금일)의 조인 축이다 — 여태 응답에 있었는데 우리가 안 읽어서
    #   「롯데온은 입금 확인 창구가 없다」로 남아 있었다.
    dmap: dict = {}

    # ★정산액은 **라인(odNo,odSeq) 단위**로 조인한다 — odNo 총액을 각 라인에 넣으면 다품
    #   주문이 2배(2026-07-25 실측·diag odSeq1=odSeq2=41,624). 인라인(order_export)과 동형.
    def _fetch_one(name, cli):
        return name, _lo_settle.itmd_line_map(since, until, client=cli,
                                              with_dates=True)

    if clients:
        with ThreadPoolExecutor(max_workers=min(len(clients), 8)) as ex:
            futs = {ex.submit(_fetch_one, name, cli): name for name, cli in clients}
            for fut in as_completed(futs):
                try:
                    _name, got = fut.result()
                except Exception as e:   # noqa: BLE001 — 한 계정이 막혀도 나머지는 진행
                    msg = (f"[lotteon·{futs[fut] or '대표'}] 정산조회 실패: "
                           f"{type(e).__name__}: {e}")
                    logger.warning(msg)
                    stat["errors"].append(msg)
                    continue
                # 🔴 튜플이 아니면(옛 서명·시험 스텁) 금액만 온 것으로 본다 —
                #   여기서 터지면 위 except 가 삼켜 **정산 스윕이 통째로 죽는다**
                #   (CI 에서 실제로 그렇게 됐다: "정산조회 실패: TypeError").
                if isinstance(got, tuple):
                    got_amts, got_dates = got
                else:
                    got_amts, got_dates = got, {}
                for k, amt in got_amts.items():      # k=(odNo,odSeq), amt=int(0 도 실정산)
                    smap.setdefault((str(k[0]), str(k[1])), amt)
                for k, d in (got_dates or {}).items():
                    dmap.setdefault((str(k[0]), str(k[1])), d)
    stat["settle_rows"] = len(smap)
    # 🔴🔴 [2026-08-12] OpenAPI(SettleItmdSales) 로 온 키만 **따로** 기억한다.
    #   이 API 의 기준일이 구매확정일이라 여기 잡혔다는 것 자체가 「구매확정됐다」는 증거다.
    #   바로 아래에서 셀러오피스 크롤값이 smap 을 **덮어쓰는데**, 그쪽은 **미정산도 포함**한다
    #   (주석 참조: 크롤표 2,121건 중 0원이 1,744건). 섞인 뒤에 확정을 판정하면 아직 확정도
    #   안 된 주문을 「구매확정」으로 찍어 정산예정금액 탭의 확정/미확정이 통째로 틀어진다.
    _api_keys = set(smap.keys())
    _api_odnos = {k[0] for k in _api_keys}

    own = False
    if session is None:
        from shared import db as _db
        if getattr(_db, "_is_sqlite", False):     # 폴백 SQLite = 테스트 잔재 오염 방지
            return stat
        session = _db.SessionLocal()
        own = True
    try:
        # ── 셀러오피스 크롤 정산을 덧입힌다 — **최우선** ─────────────────────
        #  🔴🔴 2026-08-02 이게 없어서 크롤이 통째로 헛돌았다.
        #    크롤(확장)이 lotteon_settlements 에 정산예정금을 모으는데, 그 표를 읽는
        #    코드가 order_export.lotteon_order_rows **한 곳뿐**이었다 — 즉 롯데온을
        #    **라이브로 조회할 때만** 반영된다. 저장분(MarketOrderLine.row)에 밀어넣는
        #    경로가 없어서, 라이브 창(최근 21일) 밖 주문은 크롤을 아무리 모아도
        #    영영 안 붙었다.
        #    실측이 그대로 증명: 깊은 회차로 크롤표를 1,598→2,121건(양수 228→373)
        #    늘렸는데 저장분 실정산율은 49.3% → 49.3% 로 **한 톨도 안 올랐다**.
        #    이 스윕은 OpenAPI(SettleProduct=구매확정분)만 봤기 때문이다.
        #    → 여기서 크롤값을 덧입혀 저장분까지 닿게 한다. 승격 가능분 실측 135건
        #      (그중 배송완료 102 = 「진짜 문제」 149건의 68%).
        #
        #  🔴 **양수만** 쓴다 — order_export 인라인 조인(`if v is not None`)과 다른 점.
        #    크롤표 2,121건 중 **0원이 1,744건**이다. 0을 실정산으로 단정해 박으면
        #    그 주문 마진이 「매입가 전액 손실」로 뒤집힌다. 크롤 0원이 「미정산이라 아직
        #    0」인지 「취소돼서 진짜 0」인지 이 표만으론 못 가른다 → 단정하지 않고 그대로
        #    둔다(폴백·날조 금지). 취소의 진짜 0 은 zero_cancel 경로가 이미 담당한다.
        #    음수(환불 초과, 실측 1건)도 같은 이유로 건너뛴다.
        try:
            from lemouton.sourcing.models_v2 import LotteonSettlement
            n_crawl = 0
            for x in session.query(LotteonSettlement).all():
                amt = x.pymt_tgt_amt
                if amt is None or amt <= 0:
                    continue
                smap[(str(x.od_no), str(x.od_seq or "1"))] = amt   # 크롤 최우선(덮어씀)
                n_crawl += 1
            stat["crawl_rows"] = n_crawl
        except Exception as e:   # noqa: BLE001 — 표가 없어도 OpenAPI 분은 그대로 진행
            stat["errors"].append(f"[lotteon] 크롤 정산 읽기 실패: {type(e).__name__}: {e}")
            stat["crawl_rows"] = 0

        # 롯데온 지급내역(실입금일) — {구매확정일: 정산완료일}. 크롬 확장이 모아 둔 표다.
        #  🔴 이 조인이 여태 **없어서** 「입금일 지남 1,090만 전액 롯데온·확인 불가」가
        #    남아 있었다(paid_date_map 의 호출자가 시험뿐이었다).
        try:
            from lemouton.margin.lotteon_paid import paid_date_map
            _paid_map = paid_date_map(session=session)
        except Exception as e:   # noqa: BLE001 — 지급내역이 없어도 금액 갱신은 진행
            stat["errors"].append(f"[lotteon] 지급내역 읽기 실패: {type(e).__name__}: {e}")
            _paid_map = {}
        stat["paid_dates"] = len(_paid_map)

        # odSeq 없는 옛 저장분 폴백용 — odNo 에 라인이 정확히 1개면 그 값을 안전하게 쓴다
        #  (단일라인은 라인값=주문총액). 다품인데 odSeq 불명이면 폴백 안 함(2배 위험 회피).
        _od_lines: dict = {}
        for (odno, _seq), amt in smap.items():
            _od_lines.setdefault(odno, []).append(amt)

        from lemouton.markets.models_orders import MarketOrderLine
        from lemouton.markets.order_export import (_finalize_rows, _to_int,
                                                   _lo_subtract_shipping_once)
        lines = (session.query(MarketOrderLine)
                 .filter(MarketOrderLine.market == "lotteon").all())
        # ★smap 이 비어도 **되돌림 패스는 돌아야 한다** — 그게 원천과 무관하게
        #   「근거 없는 real 0」을 푸는 일이라서다. 예전엔 여기 위에 `if not smap: return`
        #   이 있어, 양쪽 원천이 다 빈 회차에선 되돌림이 통째로 건너뛰어졌다.
        for o in (lines if smap else []):
            row = dict(o.row or {})
            if str(row.get("_kind") or "") == "change":
                continue                          # 클레임 정산은 여기서 손대지 않는다
            odno = str(row.get("오픈마켓주문번호") or "").strip()
            odseq = str((row.get("_send_ids") or {}).get("od_seq") or "")
            amt = smap.get((odno, odseq))
            # 🔴 [2026-08-03] 폴백은 **odSeq 를 모를 때만**. 주석은 처음부터 "odSeq 불명
            #   (옛 행)" 이라고 적혀 있었는데 코드가 그 조건을 안 걸어, odSeq 를 **아는**
            #   행까지 다른 라인 값을 받아갔다. 다품 주문에서 그건 정확히 이 폴백이 막으려던
            #   「2배 계상」이다 — 라이브 실측 2026071416415130: seq1=10,000 / seq2=0 인데
            #   seq2 가 smap 에 없으면 seq1 의 10,000 을 가져다 쓴다(같은 돈을 두 줄에).
            if amt is None and not odseq:         # odSeq 불명(옛 행) — 단일라인만 폴백
                _lns = _od_lines.get(odno)
                amt = _lns[0] if _lns and len(_lns) == 1 else None
            if amt is None:
                continue                          # 정산조회에 없음/다품 odSeq 불명 = 그대로 둠
            # 🔴 [2026-08-12] 정산조회에 잡혔다 = 이 주문은 **구매확정됐다**.
            #   SettleItmdSales 의 정산기준일이 곧 구매확정일이기 때문이다.
            #   롯데온 odPrgsStepCd 에는 구매확정 코드가 **아예 없어**(11~15·21~27) 상태
            #   문자열로는 확정을 알 수 없었고, 그 탓에 정산예정금액 탭에서 롯데온은
            #   confirmed 부류가 구조적으로 0건 → 전부 「아직 구매확정 전」으로 떴다
            #   (사장님 신고). 마켓이 준 이 증거를 행에 남겨 settle_plan.line_confirmed 가 쓴다.
            #   ★ **언제** 확정됐는지는 응답에 없다 → 날짜를 지어내지 않고 사실만 적는다.
            #   ★ True 만 쓴다 — False 를 쓰면 다음 회차(창 밖 주문)에서 확정을 지워 버린다.
            #   ★ 판정 재료는 **OpenAPI 키(_api_keys)뿐**이다. smap 은 크롤(미정산 포함)이
            #     섞인 뒤라 그걸로 판정하면 안 된다(위 _api_keys 주석).
            _in_api = ((odno, odseq) in _api_keys
                       or (not odseq and odno in _api_odnos))
            # 🔴 [2026-08-12] 이제 **구매확정일 자체**를 적는다(예전엔 True 플래그뿐).
            #   그래야 롯데온 지급내역(구매확정일 단위)에서 실입금일을 찾아 붙일 수 있다.
            _cfm = dmap.get((odno, odseq))
            if _cfm is None and not odseq:
                _cfm = next((v for (o, _q), v in dmap.items() if o == odno), None)
            mark_confirmed = False
            if _in_api:
                if row.get("_settle_confirmed") is not True:
                    row["_settle_confirmed"] = True
                    mark_confirmed = True
                if _cfm and row.get("_settle_confirmed_date") != _cfm:
                    row["_settle_confirmed_date"] = _cfm
                    mark_confirmed = True
                # 그 확정일에 롯데온이 **실제로 입금한 날**이 있으면 같이 적는다.
                #  ★ 없으면 안 적는다 — 「받았다」로 단정하지 않는다(lotteon_paid 규약).
                _pd = _paid_map.get(_cfm) if _cfm else None
                if _pd and row.get("_settle_paid_date") != _pd:
                    row["_settle_paid_date"] = _pd
                    mark_confirmed = True
            # 🔴 pymtAmt 는 배송비 포함 지급액. 인라인 조인(order_export)은 정산예정금액을
            #   **상품분(−배송비)** 으로 저장하고 _finalize 가 +배송비로 '배송비포함' 열을
            #   복원한다. 인라인과 100% 같은 규약을 쓰려고 그 차감 함수를 그대로 재사용한다
            #   (주문당 1회·`0<ship≤st` 가드·change 스킵 포함 → amt=0/ship>amt 엣지도 일치).
            #   안 빼면 배송비포함 = pymtAmt+배송비 로 유료배송 주문마다 마진 과대.
            #
            # 🔴🔴 이미 real 인 행도 **알려진 이중가산 backlog 는 교정**한다. 단 확정 real 을
            #   임의로 재동기화하진 않는다(정산 재조회 transient 로 덮지 않는 원 설계 존중).
            #   교정 대상 = 두 서명 중 하나로 '틀린 채 굳은' 것뿐:
            #    ① 배송비 이중가산: 저장 배송비포함 == pymtAmt + 배송비 (배송비>0)
            #       — #477 전 _lo_dvcst 기준이라 크롤주문(=0)에서 빼기 스킵(실측 42건).
            #    ② 경계일 정산 2배: 저장 배송비포함 == 2 × pymtAmt
            #       — itmd_map 경계 중복(같은 라인이 앞뒤 창에 걸려 pymtAmt 2배, 실측 5건
            #         단일라인). settlement.py 경계 dedup 으로 pymtAmt 는 이미 바로잡혔고,
            #         굳은 저장분은 여기서 재도출로 되돌린다.
            #   교정 뒤엔 배송비포함==pymtAmt 라 두 서명 다 안 맞아 멱등(재실행 무해).
            was_real = str(row.get("_settle_source") or "") == "real"
            ship = _to_int(row.get("배송비"), 0) or 0
            if was_real:
                old_incl = _to_int(row.get("정산예정금(배송비포함)"))
                is_ship_double = (ship > 0 and old_incl is not None
                                  and old_incl == amt + ship)
                is_boundary_double = (old_incl is not None and amt > 0
                                      and old_incl == 2 * amt)
                if not (is_ship_double or is_boundary_double):
                    # 금액은 손대지 않되, **확정 사실만** 새로 적을 게 있으면 저장한다.
                    #  안 그러면 이미 real 인 롯데온 행(대부분)에 확정 증거가 영영 안 붙는다.
                    if mark_confirmed:
                        o.row = dict(row)         # 새 dict 대입 — JSON 컬럼 변경 감지
                        o.last_seen_at = _store._now()
                        stat["confirmed_marked"] += 1
                    continue                      # 정상 real → 금액은 손 안 댐
            new_row = dict(row)
            new_row["정산예정금액"] = amt
            new_row["_settle_source"] = "real"
            _lo_subtract_shipping_once([new_row])   # 인라인과 동일 규약으로 배송비 상품분 차감
            _finalize_rows([new_row])
            stat["targets"] += 1
            o.row = new_row                       # 새 dict 대입 — JSON 컬럼 변경 감지
            o.last_seen_at = _store._now()
            stat["updated"] += 1

        # ── 「팔았는데 정산 0원」으로 굳은 행 되돌리기 ────────────────────────
        #  🔴🔴 [2026-08-03] 인라인 조인이 크롤 0원을 실정산으로 박던 결함의 잔재.
        #    정산 크롤 회차를 180일로 넓히자 크롤표에 0원이 1,744건 쌓였고, 그게
        #    `if v is not None` 조건을 타고 real 0 으로 들어갔다. 라이브 실측:
        #    real 인데 정산 0원인 행이 10건(전부 반품완료=정상) → 21건으로 늘고
        #    그중 **배송완료 5건**. 배송완료인데 0원 = 팔았는데 한 푼도 못 받았다는
        #    뜻이라 마진이 「매입가 전액 손실」로 뒤집힌다(에러 없이 틀린 돈).
        #    조인 쪽은 order_export 에서 `v > 0` 으로 막았고, 여기선 **이미 굳은 것**을 푼다.
        #
        #  ★푸는 조건을 **셋 다** 만족할 때만 — 넓게 잡으면 멀쩡한 0 을 지운다.
        #    ① 취소·반품·철회·회수 계열이 아니다 — 그쪽 0 은 **진짜 0**(zero_cancel 규약).
        #    ② 이번 스윕이 아는 라인이 아니다 — smap 에 있으면 근거가 있는 값이다.
        #       🔴 특히 **OpenAPI 의 pymtAmt=0 은 진짜 실정산 0**이다(100% 쿠폰·전액할인
        #         구매확정). 그건 미정산이 아니라 확정된 0 이라 건드리면 추정치로 되돌아가
        #         오히려 과대해진다(test_전액할인_0원_정산도_실정산으로_확정 가 못 박은 규약).
        #         애매한 건 **크롤 0원뿐**이고, 그건 위에서 smap 에 안 넣었으므로 여기 걸린다.
        #    ③ 판매가 성립한 상태다.
        #    되돌린 뒤엔 값을 비우고 태그를 떼어, 다음 스윕·추정이 정상 경로로 다시 채운다
        #    (0 을 다른 숫자로 바꿔 쓰지 않는다 — 날조 금지).
        _판매성립 = ("배송완료", "구매확정", "배송중", "발송완료", "수취완료", "정산완료")
        _되돌림 = 0
        for o in lines:
            row = dict(o.row or {})
            if str(row.get("_kind") or "") == "change":
                continue
            if str(row.get("_settle_source") or "") != "real":
                continue
            if (_to_int(row.get("정산예정금액")) or 0) != 0:
                continue
            _odno = str(row.get("오픈마켓주문번호") or "").strip()
            _odseq = str((row.get("_send_ids") or {}).get("od_seq") or "")
            if smap.get((_odno, _odseq)) is not None:
                continue                          # ② 근거 있는 값(OpenAPI 확정 0 포함)
            if not _odseq:                        # odSeq 불명일 때만 단일라인 폴백도 근거
                _lns = _od_lines.get(_odno)
                if _lns and len(_lns) == 1:
                    continue
            # ★odSeq 를 아는 행은 **그 라인이 smap 에 있어야만** 근거가 있다.
            #   여기 `not _odseq` 가드가 없던 탓에 라이브 1건이 안 풀렸다:
            #   2026071416415130 odSeq=2(배송완료·real·0원) — 크롤이 그 라인을 0원으로
            #   주는데, 형제 라인(seq1=10,000)이 smap 에 하나 있다는 이유로 「근거 있음」
            #   판정을 받아 건너뛰어졌다. 형제의 금액은 이 라인의 근거가 아니다.
            st = str(row.get("주문상태") or "")
            if not any(k in st for k in _판매성립):
                continue                          # ① 취소·반품·철회·회수 → 0 이 맞다
            row["정산예정금액"] = ""
            row["_settle_source"] = "none"
            _finalize_rows([row])
            o.row = row
            o.last_seen_at = _store._now()
            _되돌림 += 1
        stat["zero_reverted"] = _되돌림
        stat["updated"] += _되돌림
        session.commit()
    finally:
        if own:
            session.close()
    return stat


# 쿠팡 정산 스윕 — ESM 과 기간 규칙이 다르다(아래 refresh_settlement_coupang 참고).
COUPANG_SETTLE_SWEEP_DAYS = 75      # 인식일 기준으로 이만큼 과거까지 훑는다
COUPANG_SETTLE_SWEEP_SKIP_DAYS = 3  # 최근 이 기간은 화면 조회가 이미 실값을 붙인다


def refresh_settlement_coupang(*, since=None, until=None,
                               days: int = COUPANG_SETTLE_SWEEP_DAYS,
                               skip_days: int = COUPANG_SETTLE_SWEEP_SKIP_DAYS,
                               session=None) -> dict:
    """쿠팡 저장분의 **정산액만** 마켓 실값으로 갱신한다(주문 조회 없음).

    🔴 왜 쿠팡만 따로인가 — 정산 인식 시점과 조인 키가 ESM 과 다르다.
      · **인식일 기준**: 쿠팡 정산은 구매확정 뒤에 인식된다. 두 달 전 주문이 최근에
        인식되므로, 옛 주문을 갱신하려면 **최근 인식일 창**을 훑어 orderId 로 되짚어야
        한다. ESM 처럼 '주문일 창'으로 물으면 옛 주문의 새 정산을 영영 못 본다.
        → since/until 은 **recognitionDate** 창이다(주문일 창이 아니다).
      · **(주문번호, 옵션ID) 복합키**: 한 주문에 여러 옵션이 있어 orderId 만으론 못 가른다
        (order_export 가 (oid, vendorItemId) 로 조인하는 것과 같은 규약).

    ★대상 = 아직 실정산이 아닌 쿠팡 주문 행. 클레임 행 제외(취소·반품 정산은 딴 경로).
    ★정산조회에 없는 주문은 그대로 둔다 — 없는 값을 0 으로 채우지 않는다.
    ★저장분 조회를 **주문일로 제한하지 않는다** — 인식일 창이 옛 주문을 덮는 게 핵심이라
      주문일로 좁히면 이 스윕의 존재 이유가 사라진다. 매칭 키가 있는 행만 갱신되므로
      전 기간을 훑어도 엉뚱한 행을 건드리지 않는다.
    Returns 집계 dict(숨기지 않는다).
    """
    from lemouton.markets.order_export import _coupang_settle_map
    from shared.platforms.coupang import settlements as _cp_settle
    now = _dt.datetime.now(KST)
    if until is None:
        until = now - _dt.timedelta(days=max(0, skip_days))
    if since is None:
        since = now - _dt.timedelta(days=max(1, days))
    stat = {"market": "coupang", "accounts": 0, "settle_rows": 0,
            "targets": 0, "updated": 0, "paid_marked": 0, "errors": []}

    # 계정별로 (주문번호,옵션ID)→상품정산액 지도를 모은다. 같은 셀러 중복은 접힌다.
    item_map: dict = {}
    date_map: dict = {}      # {orderId: {정산예정일, _settle_final_date?, _recognition_date}}
    # 🔴 [2026-08-13] 배송비 정산 실값 {orderId: deliveryFee.settlementAmount}.
    #   여태 받아서 **버렸다**(`imap, _deliv, dmap = ...`). 그 결과 `order_export` 를
    #   고쳐도 **이미 저장된 주문**은 영영 옛 값(N = M + 고객배송비)이었다 —
    #   화면·마진계산기·정산탭이 읽는 건 저장분이라, 라이브에선 고침이 안 보였다.
    #   라이브 실측 1100194049219: 배송비정산 4,000(옛) → 3,868(실값)이 되어야 한다.
    deliv_map: dict = {}
    hist_rows: list = []     # 지급내역 회차 — 인식일 구간으로 조인(아래 참조)
    for name, cli in _esm_settlement_clients("coupang"):
        stat["accounts"] += 1
        try:
            imap, dvmap, dmap = _coupang_settle_map(since, until, cli)
        except Exception as e:   # noqa: BLE001 — 한 계정이 막혀도 나머지는 진행
            msg = f"[coupang·{name or '대표'}] 정산조회 실패: {type(e).__name__}: {e}"
            logger.warning(msg)
            stat["errors"].append(msg)
            continue
        for k, v in imap.items():
            item_map.setdefault(k, v)             # (oid,vid) 키 — 첫 계정 우선
        for k, v in dmap.items():
            date_map.setdefault(k, v)
        for k, v in dvmap.items():
            deliv_map.setdefault(k, v)            # 첫 계정 우선 — item_map 과 같은 규약
        # ── 지급내역조회: 「입금됐나」를 아는 유일한 창구 ────────────────────
        #  🔴 2026-08-06 실측 — revenue-history 의 settlementDate 는 안 온다(1,820행 0건).
        #    그래서 「받을 날 지남·입금 확인 불가」가 쿠팡만 6,158만 쌓였다. 이 API 는
        #    정산 **회차**마다 DONE(지급완료)/SUBJECT(지급예정)와 지급일을 준다.
        #  ★ 조인 키 = 매출인식일(회차의 [from,to] 구간). 계정별로 물어야 그 계정 회차가 나온다.
        #  ★ 조회 실패는 조용히 넘기지 않고 errors 로 올린다(값은 그대로 둔다 — 날조 금지).
        try:
            months = sorted({d.strftime("%Y-%m") for d in
                             (since + _dt.timedelta(days=i)
                              for i in range(0, max(1, (until - since).days) + 1, 15))}
                            | {until.strftime("%Y-%m")})
            fast_rows = []
            # 🔴🔴 빠른정산 인출액은 **전용 필드가 없어 공제금액에서 역산**한다. 그래서 빠른정산을
            #   안 쓰는 계정의 다른 공제(정산차감·전주채권 등)까지 「미리 받은 돈」으로 잘못 부를 수 있다.
            #   2026-08-06 라이브: 세소(빠른정산 계정) 말고 **브랜드마켓(쿠팡)에도 214만**이 잡혔다.
            #   → 받지도 않은 돈으로 총액을 깎게 된다. **사장님이 지정한 빠른정산 계정만** 담는다.
            try:
                from lemouton.margin.settle_plan_rules import load_rules
                _fast_accts = set((load_rules().get("fast_accounts") or {}
                                   ).get("coupang") or [])
            except Exception:   # noqa: BLE001 — 규칙을 못 읽으면 아무 계정도 안 담는다(안전측)
                _fast_accts = set()
            for ym in months:
                for h in _cp_settle.fetch_settlement_histories(ym, client=cli):
                    hist_rows.append(h)
                    # ⚡ 빠른정산 선인출 = **이미 통장에 들어온 돈**. 주문별 정산액엔 그대로
                    #   남아 있어(회차 단위라 건별로 못 나눔) 안 빼면 「받을 돈」이 부푼다.
                    #   Wing 실측(세소 6월): 대상액 1,108만 중 291만을 7/14 에 이미 인출.
                    if (int(h.get("fastWithdrawn") or 0) > 0
                            and (name or "") in _fast_accts):
                        fast_rows.append(dict(h, market="coupang", account=name or ""))
            if fast_rows:
                from lemouton.margin import settle_fast_ledger as _fl
                stat["fast_rows"] = stat.get("fast_rows", 0) + _fl.record(fast_rows)
            # 설정에서 빠졌거나 예전에 잘못 담긴 계정 행을 걷어낸다(위 오염 이력 참고)
            try:
                from lemouton.margin import settle_fast_ledger as _fl2
                stat["fast_pruned"] = (stat.get("fast_pruned", 0)
                                       + _fl2.prune_accounts("coupang", _fast_accts))
            except Exception:   # noqa: BLE001 — 정리 실패가 스윕을 막지 않는다
                pass
        except Exception as e:   # noqa: BLE001 — 지급내역이 없어도 정산액 갱신은 진행
            msg = (f"[coupang·{name or '대표'}] 지급내역조회 실패: "
                   f"{type(e).__name__}: {e}")
            logger.warning(msg)
            stat["errors"].append(msg)
    stat["settle_rows"] = len(item_map)
    if not item_map and not date_map and not deliv_map:
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
        from lemouton.markets.order_export import _to_int as _oe_to_int
        lines = (session.query(MarketOrderLine)
                 .filter(MarketOrderLine.market == "coupang").all())
        # 쿠팡은 저장분의 `오픈마켓주문번호` 가 곧 배송건 열쇠(`_shipkey` 의 orderId)다.
        #  전 행을 다 보고 담당을 정하므로, 조인 키(vid)가 없어 아래에서 건너뛰는 행도
        #  「안 맡는 줄 0」을 제대로 받는다.
        ship_plan = _ship_settle_plan(
            lines, deliv_map,
            lambda row: str(row.get("오픈마켓주문번호") or "").strip())
        for o in lines:
            row = dict(o.row or {})
            if str(row.get("_kind") or "") == "change":
                continue                          # 클레임 정산은 여기서 손대지 않는다
            changed = False
            # ── 배송비 정산 실값 — M 이 아니라 N열에서만 쓰인다(별도 키) ──
            #   🔴 조인 키(vid) 검사보다 **먼저** 한다. 배송비 담당은 옵션ID와 무관하고,
            #     여기서 건너뛰면 「안 맡는 줄 0」이 안 써져 옛 값이 살아남는다.
            _want_ship = ship_plan.get(id(o))
            # ⚠️ main(PR #1001)이 이 함수에선 `_to_int` 를 `_oe_to_int` 로 들여온다.
            #   옆 함수(스스)는 `_to_int` 그대로라, 같은 줄을 복사하면 여기서만 NameError 로
            #   스윕이 통째로 죽는다 — 시험이 없으면 라이브에서야 알게 된다.
            if (_want_ship is not None
                    and _oe_to_int(row.get("_ship_settle")) != _want_ship):
                row["_ship_settle"] = _want_ship
                changed = True
            oid = str(row.get("오픈마켓주문번호") or "").strip()
            vid = str(row.get("_pd_market_option_id") or "").strip()
            if not oid or not vid:
                if not changed:
                    continue                      # 조인 키 없음 — 날조 방지
                _finalize_rows([row])
                o.row = row
                o.last_seen_at = _store._now()
                stat["updated"] += 1
                continue
            # ── 지급일은 real 여부와 무관하게 채운다(백필 겸용) — 금액 규약은 불변 ──
            #  settlementDate=1차 지급예정 / finalSettlementDate=유보 30% 지급예정.
            #  정산예정금액 탭이 분할지급을 실값으로 기간 배치한다(2026-08-06).
            d_ent = date_map.get(oid) or {}
            for k in ("정산예정일", "_settle_final_date"):
                v = d_ent.get(k)
                if v and row.get(k) != v:
                    row[k] = v
                    changed = True
            # ── 지급내역 회차로 「받았나」 판정 ────────────────────────────
            #  인식일이 DONE 회차 구간에 들면 그 주문은 **이미 받은 것**(_settle_paid_date).
            #  SUBJECT 회차만 남았으면 그 날이 앞으로 받을 날(정산예정일 실값).
            #  회차가 없으면 아무것도 안 쓴다 — 「지급 안 됨」으로 단정하지 않는다.
            rec = d_ent.get("_recognition_date") or row.get("_recognition_date")
            if rec and hist_rows:
                if row.get("_recognition_date") != rec:
                    row["_recognition_date"] = rec
                    changed = True
                m = _cp_settle.match_by_recognition_date(hist_rows, rec)
                if m["paid_date"] and row.get("_settle_paid_date") != m["paid_date"]:
                    row["_settle_paid_date"] = m["paid_date"]
                    stat["paid_marked"] += 1
                    changed = True
                if m["expect_date"] and row.get("정산예정일") != m["expect_date"]:
                    row["정산예정일"] = m["expect_date"]
                    changed = True
            # ── 배송비 정산 실값 — N열 전용(M열엔 절대 안 섞는다) ────────────
            #  🔴 정산 실값을 아는 주문이면 `_settle_source` 와 **무관하게** 채운다
            #    (이미 real 인 옛 저장분이 바로 고쳐야 할 대상이다 — 위 지급일과 같은
            #     백필 성격). 없으면 손대지 않는다: 「모른다」와 「0원」은 다르다.
            #  🔴 배송건당 1회 — 저장분은 배송건 **첫 행에만** `배송비`가 남아 있다.
            #    배송비 0 인 행에 실값을 얹으면 다품 주문에서 줄 수만큼 더해진다.
            dv = deliv_map.get(oid)
            if dv is not None:
                _carry = _oe_to_int(row.get("배송비"), 0) or 0
                want = int(dv) if _carry else 0
                if row.get("_ship_settle") != want:
                    row["_ship_settle"] = want
                    changed = True
            if str(row.get("_settle_source") or "") != "real":
                amt = item_map.get((oid, vid))
                if amt is not None:               # 정산조회에 없음 = 미정산(그대로 둠)
                    stat["targets"] += 1
                    row["정산예정금액"] = amt
                    row["_settle_source"] = "real"
                    changed = True
            if not changed:
                continue                          # 값이 같으면 안 쓴다(무의미한 쓰기 방지)
            _finalize_rows([row])
            o.row = row                           # 새 dict 대입 — JSON 컬럼 변경 감지
            o.last_seen_at = _store._now()
            stat["updated"] += 1
        session.commit()
    finally:
        if own:
            session.close()
    return stat


# ── 스마트스토어 정산 스윕 ────────────────────────────────────────────────────
#
# 🔴 왜 필요한가(2026-07-25 전 마켓 검수 실측) — 스마트스토어 구매확정 1,682건이 40일
#   넘게 추정치로 고착. real 은 전체의 4%뿐이었다. 정산은 구매확정 며칠 뒤에 확정되는데
#   ① 증분 수집은 최근 7일만 훑고 ② refresh_open_orders 는 '끝난' 주문(구매확정)을 건너뛴다
#   → 정산이 들어와도 다시 안 봐서 못 받아온다(옥션·G마켓과 같은 클래스).
#
# ★ 정산조회(iter_settle_by_case)만 훑는다 — 주문 조회 없음.
#   네이버 정산은 **결제일 기준**(period_type=PAY_DATE)이라, 결제일(≈주문일) 창을 하루씩
#   훑어 상품주문번호(productOrderId)로 저장분에 얹는다. smartstore_order_rows 의 정산
#   집계와 같은 규약(상품정산 by poid + 배송비정산 by orderId, 주문당 1회).
# 스케줄러 틱 창은 좁게(21일) — 네이버는 하루씩 조회 + 429 라 넓으면 한 틱이 100초를
#  넘고 rate limit 을 유발한다. 정산은 구매확정 며칠 뒤 확정이라 21일이면 증분(7일)이
#  놓친 구간을 덮는다. 옛 backlog(>40일)는 수동 넓은 스윕을 청크로 돌려 한 번에 푼다.
SS_SETTLE_SWEEP_DAYS = 21
SS_SETTLE_SWEEP_SKIP_DAYS = 4


def refresh_settlement_smartstore(*, since=None, until=None,
                                  days: int = SS_SETTLE_SWEEP_DAYS,
                                  skip_days: int = SS_SETTLE_SWEEP_SKIP_DAYS,
                                  session=None) -> dict:
    """스마트스토어 저장분의 **정산액만** 마켓 실값으로 갱신한다(주문 조회 없음).

    · 대상 = 아직 실정산이 아닌 스스 주문 행. 클레임 행 제외.
    · 정산조회에 없는 주문은 그대로 둔다 — 없는 값을 0 으로 채우지 않는다.
    · 배송비 정산은 주문(orderId)당 1회만 더한다(원본 규약 동일).
    Returns 집계 dict(숨기지 않는다).
    """
    from lemouton.markets.order_export import _account_client, _active_accounts
    from shared.platforms.smartstore import settlements as _ss
    try:
        from shared.platforms.smartstore.client import SmartStoreRateLimitError as _SsRateLimit
    except Exception:   # noqa: BLE001 — 클래스 못 찾으면 429 도 일반 예외로(무해)
        _SsRateLimit = type("_SsRateLimit", (Exception,), {})

    now = _dt.datetime.now(KST)
    if until is None:
        until = now - _dt.timedelta(days=max(0, skip_days))
    if since is None:
        since = now - _dt.timedelta(days=max(1, days))
    stat = {"market": "smartstore", "accounts": 0, "settle_rows": 0,
            "targets": 0, "updated": 0, "errors": []}

    # 결제일 창을 하루씩 훑어 상품/배송비 정산 맵 + poid→oid 링크를 만든다.
    prod: dict = {}
    deliv: dict = {}
    poid2oid: dict = {}
    pdate: dict = {}     # {poid: {정산예정일, _settle_paid_date?}} — 지급일 실값(상품행 기준)
    accounts = _active_accounts("smartstore") or [(None, "")]
    for prefix, name in accounts:
        cli = _account_client("smartstore", prefix)
        if cli is None:
            continue
        stat["accounts"] += 1
        day = since
        while day <= until:
            ds = day.strftime("%Y-%m-%d")
            day += _dt.timedelta(days=1)
            # 네이버는 병렬 시 429(IP 기준)라 계정 내 순차. period_type=결제일.
            #  ★429 는 비켜서 재시도한다 — 즉시 실패로 굳히면 그 하루의 정산이 통째로
            #    빠져 그 날 주문들이 추정치로 남는다(조용한 실패 방지). retry_after 만큼 쉰다.
            for _attempt in range(4):
                try:
                    for el in _ss.iter_settle_by_case(
                            search_date=ds, period_type="SETTLE_CASEBYCASE_PAY_DATE",
                            client=cli):
                        amt = el.get("settleExpectAmount")
                        if amt is None:
                            continue
                        if el.get("productOrderType") == "DELIVERY":
                            oid = el.get("orderId")
                            if oid is not None:
                                deliv[str(oid)] = deliv.get(str(oid), 0) + amt
                        else:
                            poid = el.get("productOrderId")
                            oid = el.get("orderId")
                            if poid is not None:
                                prod[str(poid)] = prod.get(str(poid), 0) + amt
                                if oid is not None:
                                    poid2oid[str(poid)] = str(oid)
                                # 지급일 실값 — settleExpectDate=정산예정일 /
                                # settleCompleteDate=정산완료(실지급 확인). 첫 값 유지.
                                if str(poid) not in pdate:
                                    d_ent = {}
                                    _ed = str(el.get("settleExpectDate") or "")[:10]
                                    _cd = str(el.get("settleCompleteDate") or "")[:10]
                                    if _ed:
                                        d_ent["정산예정일"] = _ed
                                    if _cd:
                                        d_ent["_settle_paid_date"] = _cd
                                    if d_ent:
                                        pdate[str(poid)] = d_ent
                    break                    # 이 하루 성공
                except _SsRateLimit as e:    # 429 — 비켜서 재시도
                    if _attempt >= 3:
                        stat["errors"].append(
                            f"[smartstore·{name or '대표'}·{ds}] 429 재시도 소진")
                        break
                    import time as _t
                    _t.sleep(max(1, getattr(e, "retry_after_sec", 5)) + _attempt)
                except Exception as e:   # noqa: BLE001 — 하루가 막혀도 나머지는 진행
                    stat["errors"].append(
                        f"[smartstore·{name or '대표'}·{ds}] 정산조회 실패: "
                        f"{type(e).__name__}: {e}")
                    break
    stat["settle_rows"] = len(prod)
    if not prod:
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
        from lemouton.markets.order_export import _finalize_rows, _to_int
        # 매칭 키가 있는 행만 갱신되므로 전 기간을 훑어도 엉뚱한 행을 건드리지 않는다
        # (주문일↔결제일 하루 어긋남으로 놓치지 않게 날짜로 좁히지 않는다 — 쿠팡과 동일).
        lines = (session.query(MarketOrderLine)
                 .filter(MarketOrderLine.market == "smartstore").all())
        # 🔴 [2026-08-13] `deliv`(배송비 정산 실값)를 만들어 놓고 **한 번도 안 읽고 있었다.**
        #   스스 저장분의 `오픈마켓주문번호` 는 **상품주문번호(poid)** 라 배송건 열쇠가 아니다
        #   — 정산조회가 준 `poid2oid` 로 부모 주문(orderId)까지 되짚어야 묶인다.
        #   ⚠️ 이번 조회 창에 안 잡힌 형제 상품주문은 poid2oid 에 없어 묶이지 않는다.
        #     그 행들은 인라인 경로가 이미 0 을 명시 대입해 뒀다(`2e2cc8a7`)라 이중가산은 없다.
        ship_plan = _ship_settle_plan(
            lines, deliv,
            lambda row: poid2oid.get(str(row.get("오픈마켓주문번호") or "").strip()))
        for o in lines:
            row = dict(o.row or {})
            if str(row.get("_kind") or "") == "change":
                continue
            changed = False
            # ── 배송비 정산 실값 — M 이 아니라 N열에서만(별도 키). 정산조회에 아직
            #   상품분이 안 뜬 형제 행도 「안 맡는 줄 0」을 받아야 하므로 먼저 한다.
            _want_ship = ship_plan.get(id(o))
            if _want_ship is not None and _to_int(row.get("_ship_settle")) != _want_ship:
                row["_ship_settle"] = _want_ship
                changed = True
            poid = str(row.get("오픈마켓주문번호") or "").strip()
            if not poid or poid not in prod:
                if not changed:
                    continue                      # 정산조회에 없음 = 아직 미정산(그대로 둠)
                _finalize_rows([row])
                o.row = row
                o.last_seen_at = _store._now()
                stat["updated"] += 1
                continue
            # ── 지급일은 real 여부와 무관하게 채운다(백필 겸용) — 금액 규약은 불변 ──
            #  settleExpectDate=정산예정일 / settleCompleteDate=실지급 확인(2026-08-06 탭).
            for k, v in (pdate.get(poid) or {}).items():
                if v and row.get(k) != v:
                    row[k] = v
                    changed = True
            # M열 = 상품 정산만 — 배송비 정산은 안 더한다.
            #  🔴 되채움도 빌더(order_export.smartstore_order_rows)와 **같은 규약**이어야
            #    한다. 한쪽만 고치면 같은 주문이 경로에 따라 다른 값이 된다(원천 분열).
            #    옛 규칙은 배송비 정산을 더했고, `_finalize_rows` 가 N열에서 고객배송비를
            #    또 더해 배송비가 두 번 들어갔다(2026-08-07 라이브 실측 2,910원 과다).
            #
            #  🔴🔴 **이미 `real` 인 행도 본다.** 규약 전환 전에 저장된 행은 배송비가 섞인
            #    채로 `real` 이라, 「이미 real 이면 안 건드린다」가 그 옛값을 영영 보호한다
            #    (11번가 「받은 날」이 real 행에 안 붙던 것과 같은 부류 — PR#907).
            #    정산조회가 주는 상품분과 **다를 때만** 쓴다 → 값이 같으면 안 쓰므로
            #    매번 전 행을 다시 쓰는 일은 없다.
            settle = prod[poid]
            _옛값 = _to_int(row.get("정산예정금액"))
            if str(row.get("_settle_source") or "") != "real" or _옛값 != settle:
                stat["targets"] += 1
                row["정산예정금액"] = settle
                row["_settle_source"] = "real"
                changed = True
            if not changed:
                continue                          # 값이 같으면 안 쓴다(무의미한 쓰기 방지)
            _finalize_rows([row])
            o.row = row
            o.last_seen_at = _store._now()
            stat["updated"] += 1
        session.commit()
    finally:
        if own:
            session.close()
    return stat


# 11번가 정산 스윕 — 구매확정일(정산기준일) 규칙. 계정 순차(IP 전역 rate).
ELEVEN11_SETTLE_SWEEP_DAYS = 60      # 구매확정일 기준 이만큼 과거까지 훑는다
ELEVEN11_SETTLE_SWEEP_SKIP_DAYS = 3  # 최근 이 기간은 적재틱이 이미 실값을 붙인다


def refresh_settlement_eleven11(*, since=None, until=None,
                                days: int = ELEVEN11_SETTLE_SWEEP_DAYS,
                                skip_days: int = ELEVEN11_SETTLE_SWEEP_SKIP_DAYS,
                                session=None) -> dict:
    """11번가 저장분의 **정산액만** 마켓 실값으로 갱신한다(주문 조회 없음).

    🔴 왜 11번가도 스윕이 필요한가 — 정산(settlementList, 구매확정분 stlAmt)은 구매확정
      뒤에 인식되는데 적재틱(21일)이 닫힌 뒤 구매확정된 옛 주문은 추정치(stlPlnAmt)로
      고착됐다(다른 5마켓이 이미 닫은 갭). `refresh_eleven11_stale_settles`(주문 API
      재조회·limit 8)는 빈칸 채움용이라 이 정산 갱신을 못 잡는다.

    ★ 조인 키 = (ordNo, ordPrdSeq) **라인 단위** — ordNo 만으로 매칭하면 다상품 주문의
      정산 합계가 각 행에 브로드캐스트돼 N배 계상(인라인 order_export:2582 규약과 동형).
    ★ 정산예정금액 = 정산금액 − 배송비정산(배송비 분리, 인라인:2592). '배송비포함' 열은
      _finalize 가 +고객배송비로 복원. 옵션추가금 실값이 있으면 함께 채운다.
    ★ 창은 **구매확정일 기준**이라 '지금'에서 뒤로 잡는다(주문일 창이면 옛 주문의 새 정산을
      영영 못 본다 — 쿠팡·롯데온과 같은 이유).
    ★ 🔴 rate 가 **IP 전역**이라 계정 **순차**로 돈다(ESM·롯데온의 계정 병렬과 정반대 —
      11번가는 병렬 조회 시 429 로 전체가 죽는 전례. `market_concurrency.must_be_sequential`).
    ★ 정산조회에 없는 주문은 그대로 둔다 — 없는 값을 0 으로 채우지 않는다. 클레임 행 제외.
    Returns 집계 dict(숨기지 않는다).
    """
    now = _dt.datetime.now(KST)
    if until is None:
        until = now - _dt.timedelta(days=max(0, skip_days))
    if since is None:
        since = now - _dt.timedelta(days=max(1, days))
    stat = {"market": "eleven11", "accounts": 0, "settle_rows": 0,
            "targets": 0, "updated": 0, "errors": []}

    # ── 정산조회: 계정 **순차**(IP 전역 rate — 병렬 금지) ──────────────────────
    from shared.platforms.eleven11 import settlement as _el_settle
    smap: dict = {}
    for name, cli in _esm_settlement_clients("eleven11"):
        stat["accounts"] += 1
        try:
            got = _el_settle.settlement_detail_map(since, until, client=cli)
        except Exception as e:   # noqa: BLE001 — 한 계정이 막혀도 나머지는 진행
            msg = f"[eleven11·{name or '대표'}] 정산조회 실패: {type(e).__name__}: {e}"
            logger.warning(msg)
            stat["errors"].append(msg)
            continue
        for k, v in got.items():
            smap.setdefault((str(k[0]), str(k[1])), v)   # (ordNo,ordPrdSeq) — 첫 계정 우선
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
        from lemouton.markets.order_export import _finalize_rows, _to_int
        lines = (session.query(MarketOrderLine)
                 .filter(MarketOrderLine.market == "eleven11").all())
        for o in lines:
            row = dict(o.row or {})
            if str(row.get("_kind") or "") == "change":
                continue                          # 클레임 정산은 여기서 손대지 않는다
            ono = str(row.get("오픈마켓주문번호") or "").strip()
            if not ono:
                continue                          # 주문번호 없음 — 조인 키 부재(날조 방지·형제 스윕 규약)
            seq = str((row.get("_send_ids") or {}).get("ord_prd_seq") or "")
            ent = smap.get((ono, seq))
            if ent is None:
                continue                          # 정산조회에 없음 = 아직 미정산(그대로 둠)
            # 정산금액 − 배송비정산 = 상품분(인라인:2592). '배송비포함'은 _finalize 가 +고객배송비.
            new_row = dict(row)
            # 송금예정일(stlPlnDy) = 지급예정일 실값 — real 여부와 무관하게 얹는다
            # (백필 겸용·금액 규약 불변, 2026-08-06 정산예정금액 탭).
            _pdt = ent.get("송금예정일")
            date_changed = bool(_pdt) and row.get("정산예정일") != _pdt
            if _pdt:
                new_row["정산예정일"] = _pdt
            # 🔴 stlDy(정산일) = **정산이 끝난 날** = 「입금됐다」의 유일한 근거.
            #   이 목록 자체가 구매확정분이라 여기 실린 라인은 정산이 이뤄진 것이다.
            #   (2026-08-06 지도 정독 전엔 금액만 읽어, 11번가 520만이 계속 「입금일
            #    지남·미확인」에 서 있었다 — 받았는지 못 받았는지 판정할 근거가 없었다)
            _paid = ent.get("정산일")
            if _paid and row.get("_settle_paid_date") != _paid:
                new_row["_settle_paid_date"] = _paid
                date_changed = True
            new_row["정산예정금액"] = ent["정산금액"] - ent.get("배송비정산", 0)
            new_row["_settle_source"] = "real"
            if "옵션추가금" in ent:                # 주문 API 엔 없는 실값(정산 optAmt 가 유일 소스)
                new_row["옵션추가금"] = ent["옵션추가금"]
            _finalize_rows([new_row])
            # 🔴🔴 이미 real 인 행도 **배송비 이중가산 backlog 는 교정**한다(롯데온 #484 와 동일
            #   클래스·2026-07-25 실측 9건). #stlPlnAmt −배송비 규약(_stl_net) 이전에 저장된
            #   real 행은 K 가 GROSS(배송비 포함)라 _finalize 가 배송비를 이중 가산했다
            #   (라이브 실측 20260625079413235: K=25,061=정답지 N, 저장 N=28,061=+3,000).
            #   임의 재동기화는 안 함 — **재도출 N + 배송비 == 저장 N** 인 이중가산 서명일 때만
            #   교정(배송비>0). 교정 뒤 서명 불일치 → 멱등. 정상 real 은 그대로 둔다.
            if str(row.get("_settle_source") or "") == "real":
                ship = _to_int(row.get("배송비"), 0) or 0
                old_n = _to_int(row.get("정산예정금(배송비포함)"))
                new_n = _to_int(new_row.get("정산예정금(배송비포함)"))
                if not (ship > 0 and old_n is not None and new_n is not None
                        and old_n == new_n + ship):
                    if not date_changed:
                        continue                  # 정상 real·날짜 변화 없음 → 손 안 댐
                    row2 = dict(row)              # 금액 불가침 — 날짜만 백필
                    # 🔴 [2026-08-07 라이브] 여기서 **정산예정일만** 쓰고 있었다.
                    #   이미 real 인 행은 이 경로를 타는데, 「입금 확인」의 근거인 정산일
                    #   (_settle_paid_date)이 빠져 11번가 110건(2,098만)이 stlDy 가 실제로
                    #   오는데도 계속 「입금일 지남·미확인」에 남았다(진단으로 stlDy 확인 후 발견).
                    #   ★ 없는 값으로 덮지 않는다 — _pdt 가 없는데 대입하면 날짜를 지운다.
                    if _pdt:
                        row2["정산예정일"] = _pdt
                    if _paid:
                        row2["_settle_paid_date"] = _paid
                    o.row = row2
                    o.last_seen_at = _store._now()
                    stat["updated"] += 1
                    continue
            stat["targets"] += 1
            o.row = new_row                       # 새 dict 대입 — JSON 컬럼 변경 감지
            o.last_seen_at = _store._now()
            stat["updated"] += 1
        session.commit()
    finally:
        if own:
            session.close()
    return stat


# ── 송장 스윕 ─────────────────────────────────────────────────────────────
#  🔴 왜 필요한가(2026-07-30 라이브 실측) — 저장분 송장 보유율이 마켓마다 크게 갈렸다:
#    쿠팡 3,546/3,546 · 스스 1,957/1,968 · 롯데온 807/808 (정상)
#    **G마켓 34/190 · 옥션 25/47 · 11번가 109/743** (저조)
#  같은 G마켓을 **라이브로** 최근 20일 조회하면 23/23(100%) 이다 → 마켓은 송장을 정상으로
#  준다. 문제는 **창고에 안 담긴 것**이고 원인은 둘:
#    ① ESM(옥션·G마켓): 증분 수집이 **주문일 기준 21일 창**만 다시 본다(_WIDE_DAYS).
#       주문 후 21일 지나 발송하면(해외배송·까대기 특성상 흔함) 그 송장을 영영 못 받는다.
#       ESM 조회는 requestDateType=1(주문일)이라 발송일로는 찾을 수도 없다.
#    ② 11번가: 배송중·배송완료 목록만 invcNo 를 준다. **구매확정(completed)은 안 준다.**
#       21일 안에 구매확정으로 넘어가면 송장 없이 굳는다.
#  → 정산 스윕(refresh_settlement*)과 같은 방식으로, 과거 발송건 중 **송장이 빈 행만**
#    마켓에 다시 물어 채운다. 주문 전체 재적재가 아니라 '빈 칸 채우기'라 가볍다.
INVOICE_SWEEP_DAYS = 120        # 이만큼 과거까지 훑는다(까대기 배송 지연 여유)
INVOICE_SWEEP_SKIP_DAYS = 0     # 최근분도 포함 — 증분이 놓친 건이 바로 여기 있다


def _is_blank_invoice(v) -> bool:
    """송장 칸이 '없는 것과 같은' 값인가. 진짜 번호면 False."""
    from lemouton.markets.order_export import is_invoice_no
    s = str(v or "").strip()
    return (not s) or s in ("송장미입력", "확인 불가") or not is_invoice_no(s)


def refresh_invoices(market: str, *, since=None, until=None,
                     days: int = INVOICE_SWEEP_DAYS,
                     skip_days: int = INVOICE_SWEEP_SKIP_DAYS,
                     session=None) -> dict:
    """저장분의 **송장번호·택배사만** 마켓 실값으로 채운다(주문 재적재 없음).

    · 대상 = 발송된 상태인데 송장이 빈 행. 이미 진짜 번호가 있으면 건드리지 않는다.
    · 마켓이 안 주면 그대로 둔다 — 없는 값을 지어내지 않는다(무결성 1원칙).
    · 택배사도 같이 채운다(ESM=TakbaeName · 11번가=dlvEtprsCd→공식 코드표).
    Returns 집계 dict(숨기지 않는다).
    """
    if market not in ("auction", "gmarket", "eleven11"):
        # 쿠팡·스스·롯데온은 주문조회가 송장을 늘 줘서 저장분이 이미 99%+ 다(실측).
        raise ValueError(f"송장 스윕 대상이 아니에요: {market}")
    now = _dt.datetime.now(KST)
    if until is None:
        until = now - _dt.timedelta(days=max(0, skip_days))
    if since is None:
        since = now - _dt.timedelta(days=max(1, days))
    stat = {"market": market, "accounts": 0, "fetched": 0,
            "targets": 0, "updated": 0, "errors": []}

    # 1) 마켓에서 (주문번호 → 송장·택배사) 지도를 만든다.
    inv_map: dict = {}
    for name, cli in _esm_settlement_clients(market):
        stat["accounts"] += 1
        try:
            rows = _invoice_rows_for(market, since, until, client=cli)
        except Exception as e:   # noqa: BLE001 — 한 계정이 막혀도 나머지는 진행
            msg = f"[{market}·{name or '대표'}] 송장조회 실패: {type(e).__name__}: {e}"
            logger.warning(msg)
            stat["errors"].append(msg)
            continue
        for ono, inv, courier in rows:
            if not ono or _is_blank_invoice(inv):
                continue
            prev = inv_map.get(ono)
            # 택배사는 있는 쪽이 이긴다(같은 주문이 여러 경로로 올 수 있다).
            if prev is None or (not prev[1] and courier):
                inv_map[ono] = (str(inv).strip(), str(courier or "").strip())
    stat["fetched"] = len(inv_map)
    if not inv_map:
        return stat

    # 2) 저장분에서 '발송됐는데 송장이 빈' 행만 골라 채운다.
    own = False
    if session is None:
        from shared import db as _db
        if getattr(_db, "_is_sqlite", False):     # 폴백 SQLite = 테스트 잔재 오염 방지
            return stat
        session = _db.SessionLocal()
        own = True
    try:
        from lemouton.markets.models_orders import MarketOrderLine
        from lemouton.markets.order_export import _SHIPPED_STATES
        lines = (session.query(MarketOrderLine)
                 .filter(MarketOrderLine.market == market).all())
        for o in lines:
            row = dict(o.row or {})
            if str(row.get("_kind") or "") == "change":
                continue                          # 클레임 행은 원배송 송장을 따로 다룬다
            if str(row.get("주문상태") or "").strip() not in _SHIPPED_STATES:
                continue                          # 발송 전 주문은 대상 아님
            has_inv = not _is_blank_invoice(row.get("송장입력"))
            has_cr = bool(str(row.get("택배사") or "").strip())
            if has_inv and has_cr:
                continue                          # 둘 다 있으면 볼 일 없다
            hit = inv_map.get(str(row.get("오픈마켓주문번호") or "").strip())
            if not hit:
                continue                          # 마켓이 안 줌 = 그대로 둔다(날조 금지)
            inv, courier = hit
            stat["targets"] += 1
            changed = False
            if not has_inv:
                row["송장입력"] = inv
                changed = True
            if not has_cr and courier:
                row["택배사"] = courier
                changed = True
            if not changed:
                continue
            o.row = row                           # 새 dict 대입 — JSON 컬럼 변경 감지
            o.last_seen_at = _store._now()
            stat["updated"] += 1
        session.commit()
    finally:
        if own:
            session.close()
    return stat


def _invoice_rows_for(market: str, since, until, *, client):
    """마켓별 (주문번호, 송장번호, 택배사) 튜플 목록. 송장을 주는 경로만 쓴다.

    ★ESM = 주문조회가 NoSongjang·TakbaeName 을 함께 준다(지도 esm:67).
      단 조회는 **주문일 기준**이라, 여기서도 '주문일이 이 창에 든 주문'만 나온다 —
      그래서 창을 넓게(기본 120일) 잡아 21일 창이 놓친 과거분을 훑는다.
    ★11번가 = 배송중(shipping)·배송완료(dlvcompleted) 목록만 invcNo 를 준다.
      구매확정(completed)은 안 준다 → 이 둘만 훑는다. 7일 창이라 잘게 쪼갠다.
    """
    out = []
    if market in ("auction", "gmarket"):
        from lemouton.markets.order_export import esm_order_rows
        rows = esm_order_rows(market, since, until, client=client,
                              include_settlement=False, orders_only=True)
        for r in rows:
            out.append((str(r.get("오픈마켓주문번호") or "").strip(),
                        r.get("송장입력"), r.get("택배사")))
        return out

    # 11번가 — 7일 창 제약(초과하면 조용히 0건) → 7일씩 끊어 배송중·배송완료를 훑는다.
    from shared.platforms.eleven11.orders import (courier_name, iter_delivered,
                                                  iter_shipping)
    for w0, w1 in windows(since, until, 7):
        for it in (iter_shipping, iter_delivered):
            try:
                for od in it(w0, w1, client=client):
                    out.append((str(od.get("ordNo") or "").strip(),
                                od.get("invcNo"),
                                courier_name(od.get("dlvEtprsCd"))))
            except Exception:   # noqa: BLE001 — 한 창·한 경로 실패는 나머지를 막지 않는다
                logger.warning("11번가 송장조회 실패 %s~%s %s",
                               w0.date(), w1.date(), it.__name__)
    return out
