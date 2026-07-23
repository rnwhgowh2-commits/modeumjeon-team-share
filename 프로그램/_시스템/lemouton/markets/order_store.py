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
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from lemouton.markets import line_uid as _luid

# 마켓 표기(한글) → 마켓 키. ESM 은 판매처가 '옥션'/'G마켓' 으로 들어온다.
_MARKET_KEY = {"스마트스토어": "smartstore", "쿠팡": "coupang", "11번가": "eleven11",
               "롯데온": "lotteon", "옥션": "auction", "G마켓": "gmarket"}


def _clean(v) -> str:
    return str(v or "").strip()


def _date10(v) -> str:
    """값에서 'YYYY-MM-DD' 추출 — ISO·컴팩트(YYYYMMDD…)·구분자 혼용 모두. 없으면 ""."""
    import re
    m = re.search(r"(\d{4})[-./]?(\d{2})[-./]?(\d{2})", str(v or ""))
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else ""


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
                # ★ 같은 라인의 주문행 '상태'만 최신으로 — 안 하면 취소된 주문이
                #   적재분 조회에서 '배송준비중' 매출로 계속 잡힌다(2026-07-21 검수).
                #   상태만이다: 클레임행은 상품명·단가가 공란인 마켓이 많아
                #   통째로 합치면 주문행의 실값이 지워진다.
                st_new = _clean(r.get("주문상태"))
                if uid and st_new:
                    line = pending.get(("ord", uid)) or s.get(MarketOrderLine, uid)
                    if line is not None:
                        line.status = st_new
                        row2 = dict(line.row or {})
                        row2["주문상태"] = st_new
                        raw = _clean(r.get("주문상태원본"))
                        if raw:
                            row2["주문상태원본"] = raw
                        line.row = row2
                        line.last_seen_at = _now()
                        pending[("ord", uid)] = line
                        stat["orders_status_from_claim"] = (
                            stat.get("orders_status_from_claim", 0) + 1)
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
                # 클레임도 기간으로 거른다 — 안 거르면 모든 조회에 전체 이력이 딸려
                # 온다(2026-07-21 라이브: 3.5개월 조회에 기간 밖 1,998건). 기준은
                # 변경일 **또는** 실주문일 중 하나라도 기간 안이면 보존(7월 주문의
                # 9월 취소는 7월 조회에서도 매출·취소가 짝으로 보여야 한다).
                # 날짜를 둘 다 모르면 보존 — 지우는 쪽 실수가 더 위험하다(누락 금지).
                if since or until:
                    # 변경일 컬럼이 비었어도 payload 의 _change_date 가 있으면 쓴다
                    # (재수집이 payload 만 갱신하는 경로 대비).
                    cd = (_date10(c.changed_at)
                          or _date10((c.row or {}).get("_change_date")))
                    od = _date10((c.row or {}).get("주문일"))
                    if (cd or od) and not any(
                            (not since or d >= since) and (not until or d <= until)
                            for d in (cd, od) if d):
                        continue
                out.append(dict(c.row or {}))
        _heal_eleven11_status(out)
        return out
    finally:
        if own:
            s.close()


def _heal_eleven11_status(rows) -> int:
    """저장분의 11번가 숫자 주문상태를 한글로 바꾼다(읽기 시점 치유). 바꾼 수 반환.

    🔴 2026-07-23: 주문번호 단건 복구 경로가 코드(ordPrdStat)를 그대로 실어 '901'
      411건·'501' 4건·'A01' 23건이 숫자·코드로 저장됐다. 원천은 고쳤지만 **이미 저장된
      행은 재수집 전까지 그대로**이고, 1년치 재수집은 비싸다.

    ★ 여기(load)에 두는 이유 — 소비자가 여럿이다. 주문내역 화면은 order_store.load 를
      직접 부르고(webapp/routes/orders.py:_rows_from_store), 마진계산기는 order_source
      를 거친다. 상류 한 곳(order_source)에만 넣었더니 주문내역에는 숫자가 그대로
      남았다(2026-07-23 배포 후 실측). **모든 읽기가 지나는 이 한 곳**이 옳은 자리다.

    표(shared.platforms.eleven11.orders.ORD_PRD_STAT_KO)가 유일한 원천 — 코드를 여기
    복사하지 않는다. 표에 없는 값은 손대지 않는다(날조 금지).
    """
    try:
        from shared.platforms.eleven11.orders import ORD_PRD_STAT_KO
    except Exception:                                 # noqa: BLE001
        return 0
    n = 0
    for r in rows or []:
        if str(r.get("판매처") or "") != "11번가":
            continue
        raw = str(r.get("주문상태") or "").strip()
        ko = ORD_PRD_STAT_KO.get(raw.upper())
        if ko and ko != raw:
            r["주문상태"] = ko
            r.setdefault("주문상태원본", raw)          # 무엇이 왔는지 추적 가능하게 보존
            n += 1
    return n


def set_order_dates(market: str, dates: dict, *, session=None) -> dict:
    """{주문번호: 'YYYY-MM-DD HH:MM:SS'} 로 주문일 공란을 채운다 — 빈 칸만(실값 보존).

    쿠팡 취소주문(클레임행만 존재)의 실주문일 채움용(2026-07-23). 주문행·클레임행
    양쪽의 '주문일' 공란과 order_date 컬럼을 함께 갱신한다. 멱등.
    """
    from lemouton.markets.models_orders import MarketClaimEvent, MarketOrderLine

    s, own = _open_session(session)
    lines = claims = 0
    try:
        nos = sorted(k for k, v in (dates or {}).items() if k and v)
        for o in (s.query(MarketOrderLine)
                  .filter(MarketOrderLine.market == market,
                          MarketOrderLine.order_no.in_(nos)).all()):
            dt = dates[o.order_no]
            row2 = dict(o.row or {})
            if not _clean(row2.get("주문일")):
                row2["주문일"] = dt
                o.row = row2
                lines += 1
            if not _clean(o.order_date):
                o.order_date = dt
        for c in (s.query(MarketClaimEvent)
                  .filter(MarketClaimEvent.market == market,
                          MarketClaimEvent.order_no.in_(nos)).all()):
            dt = dates[c.order_no]
            row2 = dict(c.row or {})
            if not _clean(row2.get("주문일")):
                row2["주문일"] = dt
                c.row = row2
                claims += 1
        s.commit()
        return {"requested": len(nos), "lines_filled": lines,
                "claims_filled": claims}
    finally:
        if own:
            s.close()


def restore_eleven11_qty_from_claims(session=None) -> dict:
    """11번가 주문행 수량 0(잔여수량 오염) → 클레임행의 원수량으로 복원 — 멱등 보수.

    by-no 단건 복구가 ordQty(주문−취소−반품=0)를 원수량 자리에 덮은 274건의 치유
    (2026-07-23 실측). 클레임행(취소·반품 응답)의 수량이 원수량의 마켓 원본이다.
    클레임에도 없으면 '' 로 비운다(0 은 거짓값 — 공란이 정직).
    """
    from lemouton.markets.models_orders import MarketClaimEvent, MarketOrderLine

    s, own = _open_session(session)
    fixed = blanked = 0
    try:
        rows = (s.query(MarketOrderLine)
                .filter(MarketOrderLine.market == "eleven11").all())
        targets = [o for o in rows
                   if str((o.row or {}).get("수량", "")).strip() in ("0", "0.0")]
        for o in targets:
            qty = ""
            for c in (s.query(MarketClaimEvent)
                      .filter(MarketClaimEvent.market == "eleven11",
                              MarketClaimEvent.order_no == o.order_no).all()):
                v = str((c.row or {}).get("수량", "")).strip()
                if v and v not in ("0", "0.0"):
                    qty = v
                    break
            row2 = dict(o.row or {})
            row2["수량"] = qty
            o.row = row2
            o.last_seen_at = _now()
            if qty:
                fixed += 1
            else:
                blanked += 1
        s.commit()
        return {"targets": len(targets), "fixed": fixed, "blanked": blanked}
    finally:
        if own:
            s.close()


def backfill_claim_dates_from_lines(session=None) -> dict:
    """날짜(변경일·주문일) 둘 다 없는 클레임에 실주문일을 채운다 — 멱등 보정.

    11번가 클레임 727건이 날짜불명이라 기간 필터가 못 걸러 **모든 조회에** 통째로
    딸려 나왔다(2026-07-21 검수). 같은 라인의 저장 주문행(line_uid 조인)에서 실주문일을
    가져온다 — 추정이 아니라 우리가 이미 가진 실데이터다(fill_claim_blanks 와 같은 기준).
    짝이 없으면 그대로 둔다(날조 금지 — 그런 행은 계속 '기간 무관 보존'으로 나온다).
    """
    from lemouton.markets.models_orders import MarketClaimEvent, MarketOrderLine

    s, own = _open_session(session)
    try:
        checked = filled = 0
        for ev in s.query(MarketClaimEvent).all():
            row = dict(ev.row or {})
            if _date10(ev.changed_at) or _date10(row.get("주문일")):
                continue                      # 날짜가 이미 있으면 손대지 않는다
            uid = _clean(ev.line_uid)
            if not uid:
                continue
            checked += 1
            # 클레임 uid = 라인 uid 뒤에 클레임 식별자가 붙는 꼴(11번가 clmReqSeq,
            # 롯데온 clmNo). 꼬리를 하나씩 줄여 가며 주문행을 찾는다.
            # 마켓|주문번호|순번(3조각) 밑으로는 안 내려간다 — 과매칭(엉뚱한 라인) 금지.
            parts = uid.split("|")
            cands = [uid]
            while len(parts) > 3:
                parts = parts[:-1]
                cands.append("|".join(parts))
            line = None
            for c in cands:
                line = s.get(MarketOrderLine, c)
                if line is not None:
                    break
            od = _clean((line.row or {}).get("주문일")) if line is not None else ""
            if not od:
                continue
            row["주문일"] = od
            ev.row = row
            ev.last_seen_at = _now()
            filled += 1
        s.commit()
        return {"checked": checked, "filled": filled}
    finally:
        if own:
            s.close()


def dedupe_undated_claim_ghosts(session=None) -> dict:
    """날짜가 생긴 쌍둥이가 있으면 '날짜 없는' 유령 클레임 이벤트를 지운다 — 멱등.

    이벤트키(claim_event_uid)에 변경일이 들어가서, 같은 클레임을 날짜 없이 한 번
    (11번가 clmDt 오독 시절)·날짜 있게 한 번(필드 교정 후 재수집) 받으면 이벤트가
    두 개가 된다. line_uid(11번가는 클레임 식별자 clmReqSeq 포함)와 상태원본이 같고
    한쪽만 날짜가 있으면 같은 실제 이벤트다 — 정보가 적은 쪽만 제거한다.
    상태원본이 다르면 다른 이벤트(요청→완료 이력)이므로 절대 지우지 않는다.
    """
    from lemouton.markets.models_orders import MarketClaimEvent

    s, own = _open_session(session)
    try:
        groups: dict = {}
        for ev in s.query(MarketClaimEvent).all():
            uid = _clean(ev.line_uid)
            if not uid:
                continue                      # 정체성 불확실 — 안 건드린다
            groups.setdefault((uid, _clean(ev.status_raw)), []).append(ev)
        removed = 0
        for evs in groups.values():
            def _has_date(e):
                row = e.row or {}
                return bool(_date10(e.changed_at) or _date10(row.get("_change_date"))
                            or _date10(row.get("주문일")))
            dated = [e for e in evs if _has_date(e)]
            undated = [e for e in evs if not _has_date(e)]
            if dated and undated:
                for e in undated:
                    s.delete(e)
                    removed += 1
        s.commit()
        return {"removed": removed}
    finally:
        if own:
            s.close()


def sync_status_from_claims(session=None, *, stale_hours: int = 1) -> dict:
    """클레임 이력으로 주문행 상태를 보정한다 — 일회성 백필 + 주기 자가치유.

    save() 는 클레임이 들어올 때 주문행 상태를 같이 갱신하지만,
      ① 그 갱신이 생기기 전(2026-07-21 이전)에 쌓인 적재분(라이브 74쌍)과
      ② 백필이 클레임보다 **나중에** 주문행을 넣는 순서
    에서는 주문행이 옛 상태(배송준비중 등)로 남아, 취소된 주문이 매출로 계상된다.

    종결 상태(…완료)만 적용한다 — '요청/진행중'은 이후 철회됐을 수 있어 옛 이벤트로
    현재 상태를 덮으면 오히려 오염이다(최근 상태는 증분 수집이 신선한 값으로 맞춘다).
    같은 라인에 이벤트가 여러 개면 변경일이 가장 늦은 종결 상태를 쓴다. 멱등.

    🔴 stale_hours 가드(2026-07-24 실측) — 예전엔 종결 클레임을 **매 틱 무조건** 다시
    씌웠다. 그래서 취소가 철회되고 마켓이 그 주문을 다시 정상으로 보고해도, 다음 틱이
    또 '취소완료'로 되돌렸다: 11번가 20260707082636494 는 주문행 원본코드가 901(수취완료)
    인데 주문상태만 '취소완료'로 남아 있었고, 마켓 라이브 조회는 '구매확정'이었다.
    취소완료면 정산 0 이 규칙이라 **마진계산기에서 매입 전액이 손실로 잡힌다.**
    그래서 주문행이 클레임보다 stale_hours 이상 **나중에** 마켓에서 확인됐으면 덮지
    않는다. 같은 틱에 둘 다 갱신되는 진짜 취소건은 예전대로 그대로 적용된다.
    """
    from lemouton.markets.models_orders import MarketClaimEvent, MarketOrderLine

    s, own = _open_session(session)
    try:
        latest: dict = {}                  # line_uid → (정렬키, 상태, 상태원본, 클레임 확인시각)
        for ev in s.query(MarketClaimEvent).all():
            uid = _clean(ev.line_uid)
            st = _clean(ev.status)
            if not uid or "완료" not in st:
                continue
            k = (_date10(ev.changed_at), _clean(ev.changed_at))
            if uid not in latest or k >= latest[uid][0]:
                latest[uid] = (k, st, _clean(ev.status_raw), ev.last_seen_at)
        fixed = 0
        skipped_stale = 0
        for uid, (_k, st, raw, ev_seen) in latest.items():
            line = s.get(MarketOrderLine, uid)
            if line is None or _clean(line.status) == st:
                continue
            if (ev_seen is not None and line.last_seen_at is not None
                    and line.last_seen_at - ev_seen
                        > timedelta(hours=stale_hours)):
                skipped_stale += 1        # 마켓이 그 뒤로도 계속 준 주문 — 옛 클레임 무시
                continue
            line.status = st
            row2 = dict(line.row or {})
            row2["주문상태"] = st
            if raw:
                row2["주문상태원본"] = raw
            line.row = row2
            line.last_seen_at = _now()
            fixed += 1
        s.commit()
        return {"checked": len(latest), "fixed": fixed,
                "skipped_stale": skipped_stale}
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
