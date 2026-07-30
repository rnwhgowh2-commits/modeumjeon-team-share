# -*- coding: utf-8 -*-
"""배송흐름 최근 N일 요약 — 「지켜본 결과」를 날짜별로 보여준다.

## 왜 필요한가

배송흐름 감시가 「0건 멈춤」이라고만 하면, 사장님 입장에선 **정말 지켜본 건지**
알 수가 없다(사장님 요청 2026-07-30: "멈춘 주문 없음에 감시된 내용 요약을
설명해줘 — 최근 1~7일별 X건 송장번호 입력 / X건 배송중 / X건 배송완료").

## 무엇을 세는가

날짜별로 세 가지. **기준은 전부 마켓이 준 날짜**다.

- 송장 입력 : 그날 우리가 송장을 넣어 마켓이 발송처리한 건
- 배송 중   : 그날 배송중 상태인 건
- 배송 완료 : 그날 배송완료 상태인 건

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

# 그날의 상태로 세는 기준 — 화면 3칸에 대응.
_ING = ("배송중", "배송지시")
_FIN = ("배송완료", "수취완료", "구매확정", "구매결정")

# 주문일이 발송처리일보다 얼마나 앞설 수 있다고 보고 읽을지.
#  ★ 이 숫자가 곧 응답 시간이다 — 적재분을 통째로 읽어 파이썬에서 거르는 구조라
#    창이 넓으면 그만큼 느려진다(라이브 실측 2026-07-30: 60일 → 16.7초,
#    감시가 쓰는 21일 → 3.6초). 발송은 보통 주문 뒤 며칠 안에 끝나므로 30일이면
#    실무상 충분하고, 더 오래 걸린 주문은 세지 못한 채 `beyond` 로 드러낸다.
_LOOKBACK_DAYS = 30
_KINDS = ("inp", "ing", "fin")


def _bucket(status: str) -> str:
    """주문상태 → 'ing'(배송 중) / 'fin'(배송 완료) / 'inp'(송장 입력만)."""
    st = str(status or "").strip()
    if st in _FIN:
        return "fin"
    if st in _ING:
        return "ing"
    return "inp"


def summarize(*, days: int = 7, now=None, session=None) -> dict:
    """최근 N일 날짜별 요약.

    Returns {days, unknown, rows:[{date, label, inp, ing, fin, total}]}
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
        cell = tally.setdefault(d, {"inp": 0, "ing": 0, "fin": 0})
        cell[_bucket(r.get("주문상태"))] += 1

    out = []
    for i in range(days):
        day = today - _dt.timedelta(days=i)
        d = day.strftime("%Y-%m-%d")
        c = tally.get(d, {"inp": 0, "ing": 0, "fin": 0})
        out.append({"date": d, "label": _label(i), "md": day.strftime("%m-%d"),
                    "inp": c["inp"], "ing": c["ing"], "fin": c["fin"],
                    "total": c["inp"] + c["ing"] + c["fin"]})
    return {"days": days, "unknown": unknown, "rows": out}


def _label(i: int) -> str:
    return {0: "오늘", 1: "어제"}.get(i, f"{i}일 전")


def _detail_rows(date: str, now, session) -> dict:
    """그날 주문을 세 갈래로 나눠 담는다. 요약과 **같은 기준**이라 숫자가 맞는다.

    ★ 한 번 읽어 셋을 다 만든다 — 갈래마다 따로 부르면 같은 적재분을 세 번 읽어
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
        out[_bucket(r.get("주문상태"))].append(d)
    for k in _KINDS:
        out[k].sort(key=lambda x: x["_dispatch_at"], reverse=True)
    return out


def detail(*, date: str, kind: str = "inp", now=None, session=None) -> dict:
    """그날 그 갈래의 주문 목록. kind = inp | ing | fin | all.

    화면에서 날짜를 눌렀을 때 쓴다. `all` 이면 세 갈래를 한 번에 돌려준다.
    """
    now = now or _dt.datetime.now(KST)
    got = _detail_rows(date, now, session)
    if kind == "all":
        return {"date": date, "kind": "all",
                "counts": {k: len(got[k]) for k in _KINDS},
                "rows": {k: got[k] for k in _KINDS}}
    out = got.get(kind, [])
    return {"date": date, "kind": kind, "count": len(out), "rows": out}
