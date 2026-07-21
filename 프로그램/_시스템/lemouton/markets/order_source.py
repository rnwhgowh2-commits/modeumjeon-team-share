"""주문 조회의 단일 진입점 — 적재분(빠름·완전) + 최근 라이브 보충(신선).

## 왜

마진계산기·주문내역이 지금까지 매번 마켓 API 를 **라이브로** 조회했다. 과거 1년치를
부르면 창 제약 때문에 수백~수천 번 호출 → 수십 분 or 실패. 사장님이 "수시로 과거
내역 포함해 마진 조회"를 원하는데 그 구조로는 안 된다.

이 모듈은 **적재분(order_store)에서 과거를 즉시 읽고, 최근 며칠(아직 수집 안 된
꼬리)만 라이브로 보충**해 합친다. 그래서:
  · 1년치 조회 = 적재분 읽기(즉시) + 최근 N일 라이브(빠름)
  · 오늘 들어온 주문도 놓치지 않음(라이브 보충)
  · 증분 수집이 적재분을 계속 최신으로 유지 → 다음 조회는 더 빠름

## 정직성

- 요청 기간이 적재 범위보다 과거로 더 뻗으면(백필 안 된 마켓·구간) **경고를 남긴다**
  (빈 결과를 완전한 것처럼 보이면 금전 오판). df/호출부가 warnings 로 노출.
- 적재분과 라이브가 겹치는 최근 구간은 line_uid 로 중복 제거(라이브가 최신이라 우선).
- 라이브 보충이 실패하면 그 사유를 warnings 에 담고 적재분만이라도 돌려준다
  (조용한 실패 금지 — 최근 주문이 빠졌을 수 있음을 명시).
"""
from __future__ import annotations

import datetime as _dt
import logging
from typing import Optional

from lemouton.markets import line_uid as _luid

logger = logging.getLogger(__name__)

KST = _dt.timezone(_dt.timedelta(hours=9))

# 라이브로 보충하는 최근 일수. 증분 수집이 최근 며칠을 채우지만, 그 사이·오늘 들어온
# 주문을 놓치지 않도록 넉넉히 겹쳐 라이브 조회한다. 이 구간만 라이브라 빠르다.
LIVE_TAIL_DAYS = 5


def _date_str(v) -> str:
    if isinstance(v, _dt.datetime):
        return v.strftime("%Y-%m-%d")
    return str(v or "")[:10]


def _key(row: dict) -> str:
    return str(row.get(_luid.FIELD) or "")


def fetch_rows(since, until, markets, *, warnings: Optional[list] = None,
              live_tail_days: int = LIVE_TAIL_DAYS, session=None) -> list[dict]:
    """[since, until] 주문 행 — 적재분 + 최근 라이브 보충.

    since/until = datetime(또는 date-like). markets = 조회할 마켓 키 목록.
    """
    if warnings is None:
        warnings = []
    markets = list(markets or [])
    now = _dt.datetime.now(KST)
    if until is None:
        until = now
    since_s, until_s = _date_str(since), _date_str(until)

    # ── 1) 적재분(과거·대부분) ──
    from lemouton.markets import order_store as _store
    try:
        stored = _store.load(markets, since=since_s, until=until_s, session=session)
    except Exception as e:                            # noqa: BLE001
        logger.exception("적재분 읽기 실패 markets=%s", markets)
        stored = []
        warnings.append(f"저장된 주문을 읽지 못했어요({type(e).__name__}) — 라이브로만 조회합니다.")

    # 적재 범위가 요청 시작보다 과거로 못 미치면 경고(빈 구간을 완전한 것처럼 보이지 않게).
    try:
        cov = {c["market"]: c for c in _store.coverage(session=session)}
    except Exception:                                 # noqa: BLE001
        cov = {}
    short = []
    for m in markets:
        c = cov.get(m)
        oldest = (c or {}).get("oldest", "")[:10]
        if not c or (oldest and oldest > since_s):
            short.append(f"{m}({oldest or '적재없음'}~)")
    if short:
        warnings.append(
            "요청 기간의 앞부분이 아직 저장돼 있지 않아요 — 저장된 범위: "
            + ", ".join(short) + ". 「미리 채우기」를 돌리면 과거까지 즉시 조회됩니다.")

    # ── 2) 최근 라이브 보충(신선) ──
    tail_since = max(_ensure_dt(since, now), now - _dt.timedelta(days=max(0, live_tail_days)))
    live = []
    if live_tail_days > 0 and _ensure_dt(until, now) >= tail_since:
        from lemouton.markets import order_export as _oe
        try:
            live = _oe.combined_order_rows(markets, since=tail_since,
                                           until=_ensure_dt(until, now), warnings=warnings)
        except Exception as e:                        # noqa: BLE001
            logger.exception("라이브 보충 실패 markets=%s", markets)
            warnings.append(
                f"최근 주문 라이브 보충에 실패했어요({type(e).__name__}: {e}) — "
                "저장된 주문만 보여드려요(오늘 들어온 주문이 빠졌을 수 있어요).")

    # ── 3) 병합(line_uid 로 중복 제거, 라이브가 최신이라 우선) ──
    merged: dict = {}
    order: list = []
    for r in stored:
        k = _key(r) or f"_s{len(order)}"
        if k not in merged:
            order.append(k)
        merged[k] = r
    for r in live:
        k = _key(r)
        if not k:                     # 키 없는 라이브 행은 그대로 추가(합칠 근거 없음)
            k = f"_l{len(order)}"
            order.append(k)
        elif k not in merged:
            order.append(k)
        merged[k] = r                 # 라이브가 이기게(최신 상태·정산)
    return [merged[k] for k in order]


def _ensure_dt(v, default):
    if isinstance(v, _dt.datetime):
        return v if v.tzinfo else v.replace(tzinfo=KST)
    if isinstance(v, _dt.date):
        return _dt.datetime(v.year, v.month, v.day, tzinfo=KST)
    return default
