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


def summary(*, session=None) -> dict:
    """화면용 요약 — 「받을 돈」과 「이미 받은 돈」을 갈라 준다.

    받을돈 = 지급액 − 빠른정산 선인출(음수는 0). 선인출은 이미 통장에 있는 돈이라
    안 빼면 로켓그로스만큼 자금계획이 부푼다.
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
