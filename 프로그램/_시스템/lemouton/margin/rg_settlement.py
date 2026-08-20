# -*- coding: utf-8 -*-
"""로켓그로스 정산 회차 — 저장·요약.

🔴 2026-08-07 실브라우저 실측으로 창구를 찾았다. 그 전까지 로켓그로스는 정산액을 알 길이 없어
   「받을 돈」에서 통째로 빠져 있었다(사장님 지시: "로켓그로스도 포함해주고 별도 카드로").

   유일한 창구 = Wing 화면 API `GET /tenants/rfm/v2/settlements/status/api`
   · OpenAPI 엔 없다 — 매출내역에 로켓그로스 주문 0건, 정산 회차도 마켓플레이스 몫만.
   · 로그인 세션 쿠키가 필요해 서버에서 못 부른다 → 로컬 크롤 → push.

★ 「받을 돈」 = 지급액(totalPayableAmount) − 빠른정산 선인출(totalArFactoringDeductionAmount).
  선인출은 **이미 통장에 들어온 돈**이라 빼야 중복이 없다(마켓플레이스와 같은 규약).
  세소 22회차 실측: 지급액 27,319,558 · 선인출 17,811,420 · 최종지급 8,643,762.
"""
from __future__ import annotations


def _i(v) -> int:
    try:
        return int(round(float(v or 0)))
    except (TypeError, ValueError):
        return 0


def _ymd(v) -> str:
    """'2026-08-02T15:00:00Z' → '2026-08-02'. 값 없으면 빈 문자열(날조 금지)."""
    t = str(v or "")[:10]
    return t if len(t) == 10 and t[4] == "-" else ""


def parse_rows(rows: list, *, account: str = "") -> tuple[list, int]:
    """Wing 응답 settlementStatusReports[] → 저장용 dict 목록. 반환 (rows, 버린수).

    회차키(group_key)가 없는 행은 버린다 — 신원 없는 금액을 넣으면 겹쳐 쌓인다.
    """
    out, skipped = [], 0
    for r in rows or []:
        if not isinstance(r, dict):
            skipped += 1
            continue
        gk = str(r.get("settlementGroupKey") or "").strip()
        if not gk:
            skipped += 1
            continue
        d = r.get("settlementStatusReportDetail") or {}
        out.append({
            "group_key": gk[:64],
            "ratio": _i(r.get("settlementRatio")),
            "account": (account or "")[:40],
            "settlement_date": _ymd(r.get("settlementDate")),
            "period_start": _ymd(r.get("settlementPeriodStartDate")),
            "period_end": _ymd(r.get("settlementPeriodEndDate")),
            "sales_amount": _i(d.get("totalSalesAmount")),
            "payable_amount": _i(d.get("totalPayableAmount")),
            "fast_withdrawn": _i(d.get("totalArFactoringDeductionAmount")),
            "final_amount": _i(r.get("finalSettlementAmount")
                               or d.get("totalFinalSettlementAmount")),
        })
    return out, skipped


def save(rows: list, *, source: str = "manual", session=None) -> int:
    """회차 upsert. 키 = (group_key, ratio) — 같은 기간 30%·70% 가 서로 덮지 않게."""
    from lemouton.sourcing.models_v2 import RocketGrowthSettlement as M
    own = session is None
    if own:
        from shared.db import SessionLocal
        session = SessionLocal()
    try:
        n = 0
        for r in rows or []:
            obj = session.get(M, {"group_key": r["group_key"], "ratio": r["ratio"]})
            if obj is None:
                obj = M(group_key=r["group_key"], ratio=r["ratio"])
                session.add(obj)
            for k, v in r.items():
                if k not in ("group_key", "ratio"):
                    setattr(obj, k, v)
            obj.source = source
            n += 1
        session.commit()
        return n
    finally:
        if own:
            session.close()


#: 「지급 예상금액」이 세는 창 — 오늘 다음날부터 이만큼.
#  🔴 2026-08-13 사장님 화면 실측으로 **원 단위 확정**(아래 ahead_summary 주석 참조).
RG_AHEAD_DAYS = 31


def ahead_summary(*, today=None, window_days: int = RG_AHEAD_DAYS, session=None) -> dict:
    """쿠팡 화면 「지급 예상금액」과 **같은 규칙**으로 「앞으로 받을 돈」을 센다.

    🔴 규칙을 추측하지 않고 **실측으로 확정했다**(2026-08-13, 사장님 Wing 화면 25회차):
        Σ최종지급액 (21건 전부)              = 9,045,123
        Σ최종지급액 (정산일 이미 지남)         = 1,226,921
        Σ최종지급액 (오늘 이후 ~ 한 달 이내)    = **7,818,202**  ← 화면 숫자와 원 단위 일치
      더 뒤 회차(09-14·10-01·10-07 합 1,710,221)는 화면 숫자에 **안 들어간다** —
      그래서 「오늘 이후 전부」가 아니라 **한 달 창**이다.

    🔴 우리가 쓰던 `지급액 − 빠른정산` 은 **틀렸다**(라이브 9,508,138 vs 화면 7,818,202).
      두 가지가 어긋나 있었다: ① 기간 제한이 없어 **이미 받은 회차**까지 셌다
      ② 마켓이 이미 계산해 준 `최종지급액` 을 두고 우리가 다시 만들었다.
      마켓이 주는 완성된 숫자가 있으면 그걸 쓴다 — 재계산은 어긋날 자리만 늘린다.

    🔴 가상계좌 내역이 이 해석을 뒷받침한다(같은 날 실측):
        07-20 입금 193,790 = 정산일 07-20 회차의 최종지급액
        08-03 입금 323,725 = 그날 30% 회차 3건 합(127,470+113,202+83,053)
      입금 즉시 「판매자 자동인출」로 빠져나가 잔액이 늘 0이다.

    ⚠️ 창 길이(31일)는 **하루치 관측**으로 정했다. 대조에서 어긋나기 시작하면 여기부터
      다시 볼 것 — 그래서 상수로 빼 두었다.
    """
    import datetime as _d
    from lemouton.sourcing.models_v2 import RocketGrowthSettlement as M
    own = session is None
    if own:
        from shared.db import SessionLocal
        session = SessionLocal()
    try:
        t = today or _d.date.today()
        if isinstance(t, _d.datetime):
            t = t.date()
        end = (t + _d.timedelta(days=int(window_days))).isoformat()
        t_s = t.isoformat()
        금액, n, 지난 = 0, 0, 0
        for o in session.query(M).all():
            sd = str(o.settlement_date or "")
            fin = int(o.final_amount or 0)
            if not sd:
                continue                      # 정산일 없는 회차는 시기를 못 가른다
            if sd <= t_s:
                지난 += fin                    # 이미 받은 회차 — 앞으로 받을 돈이 아니다
            elif sd <= end:
                금액 += fin
                n += 1
        return {"금액": 금액, "회차수": n, "이미받은회차합": 지난,
                "창": f"{t_s} 다음날 ~ {end}",
                "구성": f"최종지급액 합(정산일 {t_s} 이후 ~ {end})"}
    finally:
        if own:
            session.close()


def summary(*, session=None) -> dict:
    """화면용 요약 — 「받을 돈」과 「이미 받은 돈」을 갈라 준다.

    ⚠️ 여기 `받을돈`(= 지급액 − 빠른정산)은 **쿠팡 화면 「지급 예상금액」과 다르다.**
      화면과 맞대려면 `ahead_summary()` 를 쓸 것(2026-08-13 실측으로 확정).
      이 값은 기간 제한이 없어 이미 받은 회차까지 포함한다.
    """
    from lemouton.sourcing.models_v2 import RocketGrowthSettlement as M
    own = session is None
    if own:
        from shared.db import SessionLocal
        session = SessionLocal()
    try:
        rows = session.query(M).all()
        by_acc: dict = {}
        for o in rows:
            b = by_acc.setdefault(o.account or "(대표)",
                                  {"계정": o.account or "(대표)", "지급액": 0,
                                   "빠른정산": 0, "최종지급": 0, "회차수": 0})
            b["지급액"] += int(o.payable_amount or 0)
            b["빠른정산"] += int(o.fast_withdrawn or 0)
            b["최종지급"] += int(o.final_amount or 0)
            b["회차수"] += 1
        for b in by_acc.values():
            b["받을돈"] = max(0, b["지급액"] - b["빠른정산"])
        계정들 = sorted(by_acc.values(), key=lambda b: -b["지급액"])
        지급 = sum(b["지급액"] for b in 계정들)
        빠른 = sum(b["빠른정산"] for b in 계정들)
        return {"지급액": 지급, "빠른정산": 빠른, "받을돈": max(0, 지급 - 빠른),
                "최종지급": sum(b["최종지급"] for b in 계정들),
                "회차수": len(rows), "계정별": 계정들}
    finally:
        if own:
            session.close()
