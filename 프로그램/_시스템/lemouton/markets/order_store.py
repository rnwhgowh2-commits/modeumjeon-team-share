"""주문·클레임 적재 — 한 번 가져온 주문을 DB 에 쌓고, 화면은 DB 에서 읽는다.

## 왜 필요한가

지금은 화면을 열 때마다 마켓 API 를 직접 조회한다(캐시는 메모리 90초뿐). 1년치를
실시간으로 하면 창 크기 제약 때문에 **약 1,760회 호출·30분+** 이 걸려 사실상 불가능하다
(스마트스토어 1일 창 → 365회, 롯데온 1일 → 365회, 11번가 7일 × 9경로 → 477회 …).

샵마인이 1년치를 즉시 보여주는 건 조회를 잘 쪼개서가 아니라 **미리 쌓아두기 때문**이다.
이 모듈이 그 저장소다. 수집은 조금씩·주기적으로, 조회는 DB 에서.

## 정직성 규칙

- **line_uid 없는 행은 저장하지 않는다.** 추측한 키로 저장하면 서로 다른 주문이
  합쳐지거나(주문 소실) 같은 주문이 두 번 쌓인다(금액 2배). 저장 못 한 건수는
  숨기지 않고 돌려준다.
- **클레임은 별도 테이블(이벤트)** 로 쌓는다. 같은 라인이 반품요청→반품완료로 갈 때
  주문 테이블에 덮어쓰면 이력이 사라진다.
- **덮어쓰기는 갱신만**. 이미 있는 행의 값은 최신 조회분으로 갱신하되, 새 조회가
  값을 안 주면(공란) 기존 값을 지우지 않는다 — 마켓이 구매확정 후 송장을 빼는 등
  '나중 조회가 덜 준다'가 실제로 있다(invoice_ledger 가 생긴 이유).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Iterable, Optional

from lemouton.markets import line_uid as _luid

# 마켓 표기(한글) → 마켓 키. ESM 은 판매처가 '옥션'/'G마켓' 으로 들어온다.
_MARKET_KEY = {"스마트스토어": "smartstore", "쿠팡": "coupang", "11번가": "eleven11",
               "롯데온": "lotteon", "옥션": "auction", "G마켓": "gmarket"}


def _clean(v) -> str:
    return str(v or "").strip()


def _market_key(row: dict) -> str:
    """행의 마켓 키. line_uid 앞부분이 가장 믿을 만하고, 없으면 판매처 표기로 폴백."""
    uid = _clean(row.get(_luid.FIELD))
    if uid and "|" in uid:
        return uid.split("|", 1)[0]
    return _MARKET_KEY.get(_clean(row.get("판매처")), "")


def _jsonable(row: dict) -> dict:
    """JSON 으로 저장 가능한 형태만 남긴다(직렬화 실패로 적재가 통째 죽지 않게)."""
    out = {}
    for k, v in (row or {}).items():
        try:
            json.dumps(v)
        except (TypeError, ValueError):
            continue
        out[str(k)] = v
    return out


def _open_session(session):
    if session is not None:
        return session, False
    from shared.db import SessionLocal
    return SessionLocal(), True


def _now():
    return datetime.now(timezone.utc)


def _merge_row(old: dict, new: dict) -> dict:
    """새 조회분으로 갱신하되, 새 값이 비었으면 기존 값을 지우지 않는다."""
    merged = dict(old or {})
    for k, v in (new or {}).items():
        if v in ("", None) and k in merged and merged[k] not in ("", None):
            continue                      # 나중 조회가 덜 주는 경우(송장 등) — 기존 유지
        merged[k] = v
    return merged


def save(rows: Iterable[dict], *, session=None) -> dict:
    """주문·클레임 행을 적재. Returns 집계 dict(숨기지 않는다)."""
    from lemouton.markets.models_orders import MarketClaimEvent, MarketOrderLine

    s, own = _open_session(session)
    stat = {"orders_new": 0, "orders_updated": 0,
            "claims_new": 0, "claims_updated": 0, "skipped_no_uid": 0}
    pending: dict = {}                     # 배치 내 중복 가드(autoflush=False 대응)
    try:
        for r in rows or []:
            uid = _clean(r.get(_luid.FIELD))
            is_claim = _clean(r.get("_kind")) == "change"
            payload = _jsonable(r)
            market = _market_key(r)
            order_no = _clean(r.get("오픈마켓주문번호"))

            if is_claim:
                ev = _luid.claim_event_uid(r)
                if not ev:
                    stat["skipped_no_uid"] += 1
                    continue
                key = ("clm", ev)
                obj = pending.get(key) or s.get(MarketClaimEvent, ev)
                if obj is None:
                    obj = MarketClaimEvent(
                        event_uid=ev, line_uid=uid, market=market, order_no=order_no,
                        changed_at=_clean(r.get("_change_date")),
                        status=_clean(r.get("주문상태")),
                        status_raw=_clean(r.get("주문상태원본")),
                        row=payload, first_seen_at=_now(), last_seen_at=_now())
                    s.add(obj)
                    stat["claims_new"] += 1
                else:
                    obj.row = _merge_row(obj.row, payload)
                    obj.status = _clean(r.get("주문상태")) or obj.status
                    obj.last_seen_at = _now()
                    stat["claims_updated"] += 1
                pending[key] = obj
                continue

            if not uid:
                # 주문행은 line_uid 없이는 저장하지 않는다 — 키를 지어내면 주문이 합쳐진다.
                stat["skipped_no_uid"] += 1
                continue
            key = ("ord", uid)
            obj = pending.get(key) or s.get(MarketOrderLine, uid)
            if obj is None:
                obj = MarketOrderLine(
                    line_uid=uid, market=market, order_no=order_no,
                    order_date=_clean(r.get("주문일")),
                    status=_clean(r.get("주문상태")),
                    account=_clean(r.get("쇼핑몰별칭")),
                    row=payload, first_seen_at=_now(), last_seen_at=_now())
                s.add(obj)
                stat["orders_new"] += 1
            else:
                obj.row = _merge_row(obj.row, payload)
                obj.status = _clean(r.get("주문상태")) or obj.status
                # 주문일은 나중에 실값으로 교정되는 경우가 있다(11번가 ordNo 근사 → 실주문일).
                od = _clean(r.get("주문일"))
                if od:
                    obj.order_date = od
                obj.last_seen_at = _now()
                stat["orders_updated"] += 1
            pending[key] = obj
        s.commit()
    finally:
        if own:
            s.close()
    return stat


def load(markets: Optional[Iterable[str]] = None, *,
         since: Optional[str] = None, until: Optional[str] = None,
         include_claims: bool = True, session=None) -> list[dict]:
    """적재분에서 행을 읽는다. since/until 은 'YYYY-MM-DD' 문자열(주문일 기준).

    주문일은 `_norm_order_dt` 로 'YYYY-MM-DD HH:MM:SS' 정규화돼 저장되므로 문자열
    비교가 곧 시간 비교다. **주문일이 공란인 행(클레임 등)은 기간으로 거르지 않는다** —
    거르면 통째로 사라진다(주문일 없는 게 정상인 마켓이 있다).
    """
    from lemouton.markets.models_orders import MarketClaimEvent, MarketOrderLine

    s, own = _open_session(session)
    try:
        out: list[dict] = []
        q = s.query(MarketOrderLine)
        mk = [m for m in (markets or []) if m]
        if mk:
            q = q.filter(MarketOrderLine.market.in_(mk))
        for o in q.all():
            od = o.order_date or ""
            if od:                                  # 공란은 기간 필터에서 제외하지 않는다
                if since and od[:10] < since:
                    continue
                if until and od[:10] > until:
                    continue
            out.append(dict(o.row or {}))
        if include_claims:
            qc = s.query(MarketClaimEvent)
            if mk:
                qc = qc.filter(MarketClaimEvent.market.in_(mk))
            for c in qc.all():
                out.append(dict(c.row or {}))
        return out
    finally:
        if own:
            s.close()


def coverage(session=None) -> list[dict]:
    """마켓별 적재 현황 — 어디까지 쌓였는지. 백필 진행·구멍 확인용."""
    from sqlalchemy import func

    from lemouton.markets.models_orders import MarketOrderLine

    s, own = _open_session(session)
    try:
        rows = (s.query(MarketOrderLine.market,
                        func.count(MarketOrderLine.line_uid),
                        func.min(MarketOrderLine.order_date),
                        func.max(MarketOrderLine.order_date))
                .group_by(MarketOrderLine.market).all())
        return [{"market": m, "rows": n, "oldest": lo or "", "newest": hi or ""}
                for m, n, lo, hi in rows]
    finally:
        if own:
            s.close()
