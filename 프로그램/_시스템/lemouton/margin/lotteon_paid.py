# -*- coding: utf-8 -*-
"""롯데온 지급내역 — 파싱·저장·조인(「언제 실제로 입금됐나」).

🔴 2026-08-07 실브라우저로 찾은 **롯데온 입금 확인의 유일한 창구**.
   정산 OpenAPI 8종·정산예정금액조회·정산요약·셀러머니 전부 실지급일이 없었고,
   셀러오피스 「중개거래정산관리 > 지급내역」의 `seCmptDt` 만이 답이었다.
   그 전까지 롯데온만 「받았을 것(확인 불가) 2,604만 + 입금일 지남 1,337만」이 판정 불가였다.

★ 롯데온은 **일정산** — 주문 단위가 아니라 **구매확정일(seStdDt) 단위**로 묶여 며칠 뒤 지급된다.
  그래서 주문에 붙일 때는 그 주문의 구매확정일로 이 표를 찾는다(쿠팡 회차 조인과 같은 방식).
"""
from __future__ import annotations


def _i(v) -> int:
    try:
        return int(round(float(v or 0)))
    except (TypeError, ValueError):
        return 0


def _ymd(v) -> str:
    """'2026-07-13' 그대로 / '20260713' → ISO. 형식 불명은 빈 문자열(날조 금지)."""
    t = str(v or "").strip()[:10]
    if len(t) == 8 and t.isdigit():
        t = f"{t[:4]}-{t[4:6]}-{t[6:8]}"
    return t if (len(t) == 10 and t[4] == "-" and t[7] == "-") else ""


def parse_rows(payload, *, tr_no: str = "", account: str = "") -> tuple[list, int]:
    """selectMediationSettleDetail 응답 → 저장용 목록. 반환 (rows, 버린수).

    정산기준일(seStdDt)이 없는 행은 버린다 — 조인 축이 없으면 붙일 수 없다.
    """
    if isinstance(payload, dict):
        data = payload.get("data") or {}
        lst = ((data.get("settleDetailList") or {}).get("dataList")
               if isinstance(data, dict) else None) or []
    else:
        lst = payload or []
    out, skipped = [], 0
    for r in lst:
        if not isinstance(r, dict):
            skipped += 1
            continue
        std = _ymd(r.get("seStdDt"))
        if not std:
            skipped += 1
            continue
        out.append({
            "tr_no": (tr_no or "")[:20],
            "se_std_dt": std,
            "se_cmpt_dt": _ymd(r.get("seCmptDt")),
            "fnl_pymt_bgt_amt": _i(r.get("fnlPymtBgtAmt")),
            "pymt_tgt_amt": _i(r.get("pymtTgtAmt")),
            "se_typ": str(r.get("seCclCdText") or "")[:20],
            "account": (account or "")[:40],
        })
    return out, skipped


def save(rows: list, *, source: str = "manual", session=None) -> int:
    """(tr_no, se_std_dt) upsert. 같은 날을 다시 훑어도 겹쳐 쌓이지 않는다."""
    from lemouton.sourcing.models_v2 import LotteonSettlePaid as M
    own = session is None
    if own:
        from shared.db import SessionLocal
        session = SessionLocal()
    try:
        n = 0
        for r in rows or []:
            if not r.get("tr_no"):
                continue                      # 판매자ID 없으면 계정 구분이 안 된다
            obj = session.get(M, {"tr_no": r["tr_no"], "se_std_dt": r["se_std_dt"]})
            if obj is None:
                obj = M(tr_no=r["tr_no"], se_std_dt=r["se_std_dt"])
                session.add(obj)
            for k, v in r.items():
                if k not in ("tr_no", "se_std_dt"):
                    setattr(obj, k, v)
            obj.source = source
            n += 1
        session.commit()
        return n
    finally:
        if own:
            session.close()


def paid_date_map(*, session=None) -> dict:
    """{구매확정일: 정산완료일} — 주문에 「받은 날」을 붙일 때 쓴다.

    ★ 정산완료일이 없는 행(아직 미지급)은 담지 않는다 — 「받았다」로 단정하지 않는다.
    ★ 계정이 여럿이면 같은 날짜에 여러 행이 있을 수 있다. 그때는 **가장 늦은 완료일**을 쓴다
      (한 계정이라도 아직 안 들어왔으면 「다 받았다」고 하면 안 되므로 보수적으로).
    """
    from lemouton.sourcing.models_v2 import LotteonSettlePaid as M
    own = session is None
    if own:
        from shared.db import SessionLocal
        session = SessionLocal()
    try:
        out: dict = {}
        for o in session.query(M).all():
            d = str(o.se_cmpt_dt or "")
            if not d:
                continue
            k = str(o.se_std_dt or "")
            if k and (k not in out or d > out[k]):
                out[k] = d
        return out
    finally:
        if own:
            session.close()


def summary(*, session=None) -> dict:
    """화면·진단용 요약 — 몇 날짜치를 갖고 있고 지급 합이 얼마인지."""
    from lemouton.sourcing.models_v2 import LotteonSettlePaid as M
    own = session is None
    if own:
        from shared.db import SessionLocal
        session = SessionLocal()
    try:
        rows = session.query(M).all()
        paid = [o for o in rows if o.se_cmpt_dt]
        return {"날짜수": len(rows), "지급확정": len(paid),
                "지급합": sum(int(o.fnl_pymt_bgt_amt or 0) for o in paid),
                "최근완료일": max((str(o.se_cmpt_dt) for o in paid), default="")}
    finally:
        if own:
            session.close()
