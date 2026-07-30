# -*- coding: utf-8 -*-
"""배송흐름 최근 N일 요약 — 「지켜본 결과」를 날짜별로 보여준다.

## 왜 필요한가

배송흐름 감시가 「0건 멈춤」이라고만 하면, 사장님 입장에선 **정말 지켜본 건지**
알 수가 없다(사장님 요청 2026-07-30: "멈춘 주문 없음에 감시된 내용 요약을
설명해줘 — 최근 1~7일별 X건 송장번호 입력 / X건 배송중 / X건 배송완료").

## 무엇을 세는가

**그날 송장을 넣은 건(X)이 총계**고, 그게 지금 어디까지 갔는지를 넷으로 나눈다
(사장님 확정 2026-07-30): `X = Y + Z + K + Q`

| 칸 | 뜻 |
|---|---|
| X 송장 넣음 | 그날 발송처리된 건 **전부** |
| Y 배송준비중 | 송장은 넣었는데 **배송 흐름이 아직 안 잡힌** 건 |
| Z 배송 중 | 배송중·배송지시 |
| K 배송완료·구매확정 | 배송완료·수취완료·구매확정·구매결정 |
| Q 클레임 | 반품·교환·취소·회수 … 되돌아왔거나 취소된 건 |

★ **과거 날짜인데 Y 에 남아 있으면 정상이 아니다** — 송장을 넣고 그날이 지났는데도
배송 흐름이 안 잡힌 것이다. 화면이 빨간 숫자로 드러낸다(오늘·어제는 아직 정상 범위).

## 정직성 규칙

- **기준 날짜가 없으면 세지 않는다.** 대신 그 건수를 `unknown` 으로 함께
  돌려준다 — 화면이 "판정 못 한 N건"으로 보여줄 수 있게(조용한 실패 금지).
- 기준 날짜 = **마켓이 준 발송처리일**(`발송처리일`). 주는 마켓은 스마트스토어
  (sendDate) · 롯데온(dvTrcStatDttm) · 11번가(sndEndDt/dlvEndDt) 셋뿐이다.
  쿠팡·옥션·G마켓은 안 주므로 `unknown` 으로 샌다.
- ★ 송장 원장(`invoice_ledger.captured_at`)은 쓰지 않는다 — `onupdate` 라
  조회할 때마다 갱신돼 '처음 넣은 날'이 아니다(쓰면 전부 오늘로 몰린다).
"""
from __future__ import annotations

import datetime as _dt

from lemouton.markets.flow_stall import KST, _parse_dt, _real_invoice
from lemouton.markets.invoice_ledger import _ONCE_SHIPPED_STATES
from lemouton.markets.order_export import _SHIPPED_STATES

# 그날의 주문상태로 가르는 기준 — 화면 4칸에 대응.
#  ★ 「발송완료」를 빠뜨렸다가 라이브에서 롯데온 1건이 「배송준비중」으로 빨갛게 떴다
#    (2026-07-30). `_SHIPPED_STATES` 를 **빠짐없이 덮는지** 테스트가 지킨다.
_ING = ("배송중", "배송지시", "발송완료")
_FIN = ("배송완료", "수취완료", "구매확정", "구매결정")
#  클레임 = 되돌아왔거나 취소된 것. 목록은 송장 원장과 **같은 것**을 쓴다(두 벌 만들면 갈린다).
_CLM = _ONCE_SHIPPED_STATES
#  아직 안 움직인 것 — **이 목록에 있는 것만** 「멈췄다」고 빨갛게 칠한다.
#   모르는 상태를 멈춘 걸로 몰면 없는 문제를 만든다(위 롯데온 사고).
_PREP = ("배송준비중", "상품준비중", "결제완료", "신규주문", "출고지시", "발송대기")

# 주문일이 발송처리일보다 얼마나 앞설 수 있다고 보고 읽을지.
#  ★ 이 숫자가 곧 응답 시간이다 — 적재분을 통째로 읽어 파이썬에서 거르는 구조라
#    창이 넓으면 그만큼 느려진다(라이브 실측 2026-07-30: 60일 → 16.7초,
#    감시가 쓰는 21일 → 3.6초). 발송은 보통 주문 뒤 며칠 안에 끝나므로 30일이면
#    실무상 충분하고, 더 오래 걸린 주문은 세지 못한 채 `beyond` 로 드러낸다.
_LOOKBACK_DAYS = 30
#  X(송장 넣음)은 총계라 갈래가 아니다 — 아래 넷의 합이 곧 X.
_KINDS = ("prep", "ing", "fin", "clm")


def _bucket(status: str) -> str:
    """주문상태 → 'ing' / 'fin' / 'clm' / 'prep'(그 밖 = 흐름이 아직 안 잡힘)."""
    st = str(status or "").strip()
    if st in _FIN:
        return "fin"
    if st in _ING:
        return "ing"
    if st in _CLM:
        return "clm"
    return "prep"


def summarize(*, days: int = 7, now=None, session=None) -> dict:
    """최근 N일 날짜별 요약.

    Returns {days, unknown, rows:[{date, label, md, sent, prep, ing, fin, clm, stuck}]}
    `sent` = 그날 송장 넣은 총계(X) = prep + ing + fin + clm.
    `stuck` = 과거 날짜인데 prep 에 남은 건수(오늘·어제는 0 — 아직 정상 범위).
    최신 날짜가 앞에 온다(오늘 → 6일 전).
    """
    from lemouton.markets import order_store as _store

    now = now or _dt.datetime.now(KST)
    today = now.date()
    since = (now - _dt.timedelta(days=days - 1)).strftime("%Y-%m-%d")
    # 주문일이 발송처리일보다 앞서므로 그만큼 앞에서부터 읽고 발송처리일로 거른다.
    load_since = (now - _dt.timedelta(days=days + _LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    rows = _store.load(since=load_since, until=now.strftime("%Y-%m-%d"),
                       include_claims=False, session=session)

    tally: dict = {}
    unseen: dict = {}       # 처음 보는 주문상태 → 건수(조용히 삼키지 않는다)
    unknown = 0
    for r in rows:
        if not _real_invoice(r.get("송장입력")):
            continue                      # 송장이 없으면 지켜볼 대상이 아니다
        base = _parse_dt(r.get("발송처리일"))
        if base is None:
            unknown += 1                  # 마켓이 날짜를 안 줌 — 숨기지 않는다
            continue
        d = base.strftime("%Y-%m-%d")
        if d < since or d > today.strftime("%Y-%m-%d"):
            continue
        st = str(r.get("주문상태") or "").strip()
        cell = tally.setdefault(d, dict.fromkeys(_KINDS, 0))
        b = _bucket(st)
        cell[b] += 1
        if b == "prep" and st not in _PREP:
            # 처음 보는 상태 — 숨기지 않고 이름째 드러낸다(멈춘 걸로 몰지도 않는다).
            unseen[st or "(빈칸)"] = unseen.get(st or "(빈칸)", 0) + 1
            cell.setdefault("_unknown", 0)
            cell["_unknown"] += 1

    out = []
    for i in range(days):
        day = today - _dt.timedelta(days=i)
        d = day.strftime("%Y-%m-%d")
        c = tally.get(d, dict.fromkeys(_KINDS, 0))
        row = {"date": d, "label": _label(i), "md": day.strftime("%m-%d")}
        row.update({k: c[k] for k in _KINDS})
        row["sent"] = sum(c[k] for k in _KINDS)      # X = Y + Z + K + Q
        # 오늘·어제는 아직 흐름이 안 잡혀도 정상이다 — 그 뒤부터 「멈춘 것」으로 본다.
        #  ★ **아는 상태만** 멈춘 것으로 센다. 모르는 상태를 몰면 없는 문제를 만든다.
        row["stuck"] = max(0, c["prep"] - c.get("_unknown", 0)) if i >= 2 else 0
        out.append(row)
    return {"days": days, "unknown": unknown, "rows": out,
            "stuck": sum(r["stuck"] for r in out),
            "unseen": dict(sorted(unseen.items(), key=lambda kv: -kv[1]))}


def _label(i: int) -> str:
    return {0: "오늘", 1: "어제"}.get(i, f"{i}일 전")


def _seen_at(r: dict) -> str:
    """상태가 바뀐 것을 우리가 처음 본 시각(KST 'MM-DD HH:MM'). 기록 전이면 ''.

    ★ 없는 값을 지어내지 않는다 — 2026-07-30 이전 주문은 기록이 없어 빈칸이다.
    """
    v = str(r.get("_status_at") or "").strip()
    if not v:
        return ""
    try:                                   # 저장은 UTC naive → 보여줄 땐 KST
        t = _dt.datetime.fromisoformat(v)
    except ValueError:
        return ""
    if t.tzinfo is None:
        t = t.replace(tzinfo=_dt.timezone.utc)
    return t.astimezone(KST).strftime("%m-%d %H:%M")


def _detail_rows(date: str, now, session) -> dict:
    """그날 주문을 네 갈래로 나눠 담는다. 요약과 **같은 기준**이라 숫자가 맞는다.

    ★ 한 번 읽어 넷을 다 만든다 — 갈래마다 따로 부르면 같은 적재분을 네 번 읽어
      탭을 누를 때마다 수십 초씩 기다린다(라이브 실측 2026-07-30: 갈래당 28초).
    """
    from lemouton.markets import order_store as _store

    # 그 날짜 하루만 필요하다 — 그 앞 _LOOKBACK_DAYS 일 안에 들어온 주문까지 본다.
    day = _dt.datetime.strptime(date, "%Y-%m-%d").date()
    load_since = (day - _dt.timedelta(days=_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    rows = _store.load(since=load_since, until=date,
                       include_claims=False, session=session)
    out: dict = {k: [] for k in _KINDS}
    for r in rows:
        if not _real_invoice(r.get("송장입력")):
            continue
        base = _parse_dt(r.get("발송처리일"))
        if base is None or base.strftime("%Y-%m-%d") != date:
            continue
        d = dict(r)
        d["_dispatch_at"] = base.strftime("%Y-%m-%d %H:%M")
        # 두 시각은 뜻이 다르다 — 하나로 합치면 안 된다.
        #  · _dispatch_at   = 마켓이 준 **송장 전송(발송처리) 시각**
        #  · _status_seen   = 주문상태가 바뀐 것을 **우리가 처음 본** 시각(관측값)
        d["_status_seen"] = _seen_at(r)
        out[_bucket(r.get("주문상태"))].append(d)
    for k in _KINDS:
        out[k].sort(key=lambda x: x["_dispatch_at"], reverse=True)
    return out


def detail(*, date: str, kind: str = "prep", now=None, session=None) -> dict:
    """그날 그 갈래의 주문 목록. kind = prep | ing | fin | clm | all.

    화면에서 날짜를 눌렀을 때 쓴다. `all` 이면 네 갈래를 한 번에 돌려준다.
    """
    now = now or _dt.datetime.now(KST)
    got = _detail_rows(date, now, session)
    if kind == "all":
        cnt = {k: len(got[k]) for k in _KINDS}
        return {"date": date, "kind": "all", "counts": cnt,
                "sent": sum(cnt.values()),     # X — 요약의 「송장 넣음」과 같아야 한다
                "rows": {k: got[k] for k in _KINDS}}
    out = got.get(kind, [])
    return {"date": date, "kind": kind, "count": len(out), "rows": out}
