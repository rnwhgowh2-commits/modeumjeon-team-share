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


# 비교용 최소값 — last_seen_at 이 비어 있는 옛 행이 최신을 이기지 않게.
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


# 근거 없음을 뜻하는 `_settle_source` 값 — 빈칸과 같은 뜻이다.
_WEAK_SETTLE_TAGS = ("", "none")


def _merge_row(old: dict, new: dict) -> dict:
    """새 조회분으로 갱신하되, 새 값이 비었으면 기존 값을 지우지 않는다."""
    merged = dict(old or {})
    # ★ 근거 태그(`_settle_source`)는 정산액(`정산예정금액`)의 설명이다 — 한 벌로 움직인다.
    #   이번 조회가 정산액을 못 가져왔으면 근거도 못 가져온 것이다. 그런데 새 행의 태그
    #   초깃값은 `"none"` 이라 **빈 값이 아니어서** 아래 규칙을 통과해 기존 태그를 덮었다.
    #   그 결과 금액은 남고 근거만 사라진 행이 생겼고, 마진계산기는 근거 없는 금액을
    #   안 믿으므로(취소건 배송비 잔존 오인 방지) 그 돈을 **0 으로** 봤다.
    #     2026-07-25 라이브 실측 226건 — G마켓 44 · 롯데온 124 · 11번가 57 · 스스 1.
    #     대표(G마켓 4463818179): 주문내역 69,530 vs 마진계산기 0.
    #   금액을 안 지우는 것과 같은 이유로 근거도 안 지운다.
    keep_tag = (
        (new or {}).get("정산예정금액") in ("", None)
        and str((new or {}).get("_settle_source") or "").strip() in _WEAK_SETTLE_TAGS
        and str(merged.get("_settle_source") or "").strip() not in _WEAK_SETTLE_TAGS)
    for k, v in (new or {}).items():
        if k == "_settle_source" and keep_tag:
            continue
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


# 더 볼 필요 없는 상태 — 여기 닿으면 상태·송장이 더 안 바뀐다.
#  ★ '배송완료'·'수취완료'는 넣지 않는다 — 그 다음에 구매확정으로 한 번 더 바뀐다.
DONE_STATUSES = ("구매확정", "구매결정", "취소완료", "반품완료", "교환완료")


def open_order_dates(market: str, *, since: str, until: str,
                     limit: int = 0, session=None) -> list[str]:
    """아직 **안 끝난** 주문이 있는 날짜 목록(YYYY-MM-DD). 오래 안 본 날짜부터.

    왜 필요한가 — 스마트스토어·롯데온은 **하루씩만** 조회할 수 있어(마켓 제한),
    최근 3주를 통째로 훑으면 창이 21개가 된다. 그런데 이미 끝난 주문은 값이 더
    안 바뀌므로 다시 볼 이유가 없다. **안 끝난 건이 남아 있는 날짜만** 골라
    그 하루만 다시 조회하면 같은 최신성을 훨씬 적은 호출로 얻는다.

    정렬 = 그 날짜 주문을 **가장 오래 안 본 순**(last_seen_at 최솟값). 한 틱에
    limit 개만 처리해도 다음 틱이 나머지를 가져가 자연히 돌아간다(굶는 날짜 없음).
    """
    from sqlalchemy import func

    from lemouton.markets.models_orders import MarketOrderLine

    s, own = _open_session(session)
    try:
        rows = (s.query(func.substr(MarketOrderLine.order_date, 1, 10).label("d"),
                        func.min(MarketOrderLine.last_seen_at).label("seen"))
                .filter(MarketOrderLine.market == market)
                .filter(MarketOrderLine.order_date >= since)
                .filter(MarketOrderLine.order_date <= until + " 99")
                .filter(func.coalesce(MarketOrderLine.status, "").notin_(DONE_STATUSES))
                .group_by("d").order_by("seen").all())
        out = [r[0] for r in rows if r[0]]
        return out[:limit] if limit else out
    finally:
        if own:
            s.close()


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
        # 같은 라인이 여러 행으로 잡히면 **지금 상태 한 줄만** 내보낸다(사장님 확정
        #  2026-07-24: "변경이력보다는 최신화 주문상태의 현재기준으로 1건만").
        #  왜 여러 행이 되나 — 저장 키가 마켓 식별자 조합이라, 그 조합이 시절마다
        #  달랐던 주문은 옛 키·새 키 두 행으로 남는다(롯데온 실측 3건: 출고지시 +
        #  배송완료 / 회수지시 + 배송완료 / 철회 + 배송완료).
        #  ★ 고르는 기준은 **마켓이 가장 최근에 알려준 행**(last_seen_at) 이다. 상태
        #    이름으로 순위를 매기면(배송완료 > 출고지시 …) 마켓마다 다른 말을 쓰는
        #    순간 틀린다 — 지어낸 서열 대신 실제 관측 시각을 쓴다.
        #  ★ 지우지 않는다. 화면에 무엇을 보여줄지만 정한다(옛 행은 그대로 남는다).
        _pick: dict = {}
        for o in q.all():
            od = o.order_date or ""
            if od:                                  # 공란은 기간 필터에서 제외하지 않는다
                if since and od[:10] < since:
                    continue
                if until and od[:10] > until:
                    continue
            row = dict(o.row or {})
            # 관측 시각을 행에 실어 보낸다 — 하류(마진 계산)도 '어느 쪽이 최신인지'를
            #  지어내지 않고 사실로 고를 수 있어야 한다. 저장 키 그 자체도 함께 실어
            #  둔다(payload 의 _line_uid 와 실제 저장 키가 다른 행을 눈으로 잡기 위함).
            if o.last_seen_at is not None:
                row["_seen_at"] = o.last_seen_at.isoformat()
            row["_store_pk"] = o.line_uid
            # 식별자가 없으면 합치지 않는다(정체 불확실 — 남의 주문과 섞이면 더 위험).
            key = _clean(row.get(_luid.FIELD)) or f"__pk__{o.line_uid}"
            prev = _pick.get(key)
            if prev is None or (o.last_seen_at or _EPOCH) > (prev[0] or _EPOCH):
                _pick[key] = (o.last_seen_at, row)
        out.extend(r for _t, r in _pick.values())
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
                # ★ **클레임 테이블에서 읽었으면 클레임이다.** 저장된 payload 의
                #   `_kind` 를 믿지 않는다 — 옛 경로가 남긴 행 중엔 이 표시가 없거나
                #   'order' 로 들어 있는 게 있고, 그러면 화면이 그걸 **주문 줄로 착각**해
                #   한 주문이 두 줄로 그려진다(2026-07-24 롯데온 실측 3건: 출고지시·
                #   회수지시·철회가 배송완료 줄과 나란히 떴다). 어느 테이블에서 왔는지가
                #   유일한 진실이므로 여기서 다시 새긴다. 지우지 않는다 — 표시만 고친다.
                _crow = dict(c.row or {})
                _crow["_kind"] = "change"
                if c.last_seen_at is not None:
                    _crow["_seen_at"] = c.last_seen_at.isoformat()
                _crow["_store_pk"] = c.event_uid
                out.append(_crow)
        _heal_eleven11_status(out)
        _heal_invoice_status_text(out)
        _fill_invoice_from_ledger(out)
        return out
    finally:
        if own:
            s.close()


def _fill_invoice_from_ledger(rows) -> int:
    """발송됐는데 송장이 빈 행을 **송장 원장**에서 채운다. 채운 수 반환.

    🔴 2026-07-24 실측: 11번가 79건이 판매처에서 배송완료·구매확정인데 송장번호가
      비어 있었다. 11번가 API 는 구매확정된 건의 invcNo 를 더 주지 않는다 —
      배송중일 때 한 번 준 뒤 회수한다(invoice_ledger 가 생긴 이유).

    🔴 근본 원인은 **원장 채움이 주문내역 라우트에만 걸려 있던 것**이다. 마진계산기는
      order_source → order_store.load 로 같은 저장분을 읽는데, 그 층을 안 지나가서
      같은 주문이 화면마다 달라 보였다. 11번가 주문상태 '901' 치유를 라우트에 두었다가
      주문내역이 못 타서 옮겼던 것과 **똑같은 함정**이라, 이번엔 처음부터 읽기 층에 둔다.

    ★쓰기(remember)는 여기 넣지 않는다 — 읽을 때마다 저장하면 조회가 무거워진다.
      기억은 주문내역 조회가 계속 해 주므로, 읽기 층은 **채우기만** 한다.
    ★원장은 보조기능이다. DB 가 말썽이어도 주문 조회는 살아야 하므로 실패는 삼킨다.
    """
    try:
        from lemouton.markets import invoice_ledger as _led
        return int(_led.fill_missing(rows) or 0)
    except Exception:   # noqa: BLE001 — 원장 실패가 주문 조회를 막지 않는다
        import logging
        logging.getLogger(__name__).exception("invoice ledger fill failed")
        return 0


def _heal_invoice_status_text(rows) -> int:
    """송장번호 칸에 앉은 **상태 문구**를 정리한다. 바꾼 수 반환.

    🔴 2026-07-24 실측: 쿠팡 89건·11번가 1건의 송장번호 칸에 번호가 아니라 「송장입력됨」
      이라는 **문구**가 들어 있었다. 샵마인 대조 백필이 샵마인 송장 열을 그대로 실은 것으로,
      지금은 원천에 is_invoice_no 가드가 있지만 **이미 저장된 행은 그대로 남는다**
      (11번가 주문상태 '901' 과 같은 패턴 — 원천만 고치면 저장분이 낡은 채 남는다).

    ★번호를 모르는 것이므로 「확인 불가」로 둔다 — '송장미입력'(=아직 안 넣음)과 뜻이 다르다.
      번호인 척하는 문구를 그대로 두면 사장님이 번호로 읽고, 송장 유무 판정도 틀린다.
    ★진짜 번호와 '송장미입력'·'확인 불가' 는 손대지 않는다.
    """
    from lemouton.markets.order_export import is_invoice_no

    KEEP = ("송장미입력", "확인 불가")
    n = 0
    for r in rows or []:
        v = str(r.get("송장입력") or "").strip()
        if not v or v in KEEP or is_invoice_no(v):
            continue
        r["송장입력"] = "확인 불가"
        r.setdefault("송장입력원본", v)      # 무엇이 왔는지 추적 가능하게 보존
        n += 1
    return n


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


def dedupe_short_uid_ghosts(session=None) -> dict:
    """같은 라인이 **짧은 키**로 한 번 더 저장된 빈 껍데기를 지운다 — 멱등.

    🔴 2026-07-24 실측(롯데온 187건) — line_uid 는 마켓이 주는 식별자를 이어 붙인다.
    롯데온은 (odNo, odSeq[, sitmNo]) 인데, **정산 API 백필은 sitmNo 를 안 준다**.
    그래서 같은 상품라인이
        정산 백필 →  lotteon|2026061116973269|1                (상품명·단가·상태 공란)
        209 조회  →  lotteon|2026061116973269|1|LO2686862490_… (실데이터)
    두 키로 갈려 **한 주문이 두 행**이 됐다. 짧은 쪽은 값이 하나도 없는 껍데기다.

    지우는 조건(전부 만족할 때만 — 정보 손실 0):
      ① 긴 키(`짧은키|…`)를 가진 형제 행이 실제로 있다
      ② 짧은 쪽이 **비어 있다**(상품명·단가 둘 다 공란/0)
    형제가 없거나 짧은 쪽에 값이 있으면 **절대 안 지운다**(그건 유일한 원본일 수 있다).
    """
    from lemouton.markets.models_orders import MarketOrderLine

    s, own = _open_session(session)
    try:
        rows = s.query(MarketOrderLine).all()
        by_prefix: dict = {}                  # '짧은키|' 로 시작하는 형제 존재 여부
        for o in rows:
            uid = _clean(o.line_uid)
            if "|" in uid:
                head = uid.rsplit("|", 1)[0]
                by_prefix.setdefault(head, []).append(o)
        removed = 0
        for o in rows:
            uid = _clean(o.line_uid)
            sibs = [x for x in by_prefix.get(uid, []) if _clean(x.line_uid) != uid]
            if not sibs:
                continue                      # ① 긴 키 형제 없음
            row = o.row or {}
            name = _clean(row.get("상품명"))
            price = _clean(row.get("단가"))
            if name or (price and price not in ("0", "0.0")):
                continue                      # ② 값이 있으면 껍데기가 아니다
            s.delete(o)
            removed += 1
        s.commit()
        return {"removed": removed}
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
