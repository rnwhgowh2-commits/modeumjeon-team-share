# -*- coding: utf-8 -*-
"""11번가 **구매확정 전** 정산예정액 — 셀러오피스 화면 API 실값을 주문라인에 붙인다.

🔴🔴 2026-08-08 사장님이 화면에서 뒤집은 사실.
   전날 나는 「11번가는 구매확정 전 정산예정액을 마켓 자체가 안 준다(구조적 한계)」고
   결론 냈다. **틀렸다.** 근거로 삼은 게 「정산 미확정 건 0」이었는데, 그때 조회 축이
   `searchDtType=BUY_CNFRM_DT`(구매확정일)였다. 구매확정 전 주문은 구매확정일이 없으니
   **애초에 조회 대상이 아니어서 0건**이었던 것이지, 마켓이 안 주는 게 아니었다.
   축을 `STL_DT`(결제일)로 바꾸자 발주확인·배송완료 10건이 정산예정금액과 함께 나왔다.

   ★ 교훈: **0건은 「없다」가 아니라 「이 축으로는 안 보인다」일 수 있다.**
     조회 축을 바꿔 보기 전에 「마켓이 안 준다」고 말하지 말 것.

■ 창구 (읽기 전용·로컬 PC 크롬 확장 — 셀러오피스 세션 쿠키가 필요해 서버에선 못 부른다)
    POST soffice.11st.co.kr/remittance/SellerRemittanceAction.tmall
      ?method=getSelAllStatDtlsSoffice&start=0&limit=300
      &dtlSearchStlmntType=N        ← N=정산 미확정(=구매확정 전 포함)  ★
      &searchDtType=STL_DT          ← 결제일 기준                       ★
      &stDate=YYYYMMDD&edDate=YYYYMMDD   ← 화면 상한이 **한 달**이라 토막내 부른다
      &cnsgnDlvYn=N&quickStlYn=N&searchType=ALL&ordPrdStat=&dtlSearchType=&dtlSearchVal=

■ 응답(2026-08-08 라이브 실측 10건 · 화면 합계와 정확히 일치)
    ordNo 20260806090786705 · ordPrdSeq 1 · ordPrdStat '발주확인'
    selPrc 58,400 − deductAmt 10,506 = **stlAmt 47,894**  ← 정산예정금액
    selFixedFee '13.00%' · stlPlnDy '' (구매확정 전이라 예정일은 아직 없다)
    합계: 공제 83,009 · 정산예정 464,691 = 화면과 동일 (판매금액만 배송비만큼 낮다 —
          배송비는 selPrc 밖이지만 **stlAmt 안에는 들어 있다**).

■ 왜 `stlAmt` 를 `정산예정금(배송비포함)` 에 그대로 쓰는가
    이 값에 이미 배송비가 반영돼 있어 우리 단일 원천 규약과 정의가 같다
    (`sell_source._settlement_for` 스펙 §4 ②). 여기서 배송비를 또 더하면 이중계상이다.
"""
from __future__ import annotations

SETTLE_FIELD = "정산예정금(배송비포함)"       # N열 — stlAmt 그대로(배송비 포함)
SETTLE_M_FIELD = "정산예정금액"               # M열 — 배송비 제외(11번가 빌더와 같은 규약)
NET_FLAG = "_stl_net"                         # M열=배송비 제외로 저장됨(구 저장분 구분자)
SRC_FIELD = "_settle_source"


def _i(v) -> int:
    """'1,776' · '58400' · '' → int. 11번가는 콤마가 섞여 온다(selFee 실측)."""
    try:
        return int(round(float(str(v or 0).replace(",", "").strip() or 0)))
    except (TypeError, ValueError):
        return 0


def parse_rows(payload, *, account: str = "") -> tuple[list, int]:
    """응답 → 저장용 목록. 반환 (rows, 버린수).

    ★ `ordNo`·`ordPrdSeq` 가 없으면 버린다 — 조인 키를 못 만든다(추측 금지).
    ★ `stlAmt` 가 비면 버린다 — 0 으로 채우면 정산이 사라진 것처럼 보인다.
    """
    if isinstance(payload, dict):
        lst = payload.get("list")
        if lst is None:
            lst = ((payload.get("json") or {}).get("list")
                   if isinstance(payload.get("json"), dict) else None) or []
    else:
        lst = payload or []
    out, skipped = [], 0
    for r in lst:
        if not isinstance(r, dict):
            skipped += 1
            continue
        ord_no = str(r.get("ordNo") or "").strip()
        seq = str(r.get("ordPrdSeq") or "").strip()
        raw_amt = r.get("stlAmt")
        if not ord_no or not seq or raw_amt in (None, "", "null"):
            skipped += 1
            continue
        out.append({
            "line_uid": f"eleven11|{ord_no}|{seq}",
            "ord_no": ord_no,
            "ord_prd_seq": seq,
            "stl_amt": _i(raw_amt),
            "ord_prd_stat": str(r.get("ordPrdStat") or "")[:20],
            "pay_date": str(r.get("ordStlEndDt") or "")[:10],
            "sel_prc": _i(r.get("selPrc")),
            "deduct_amt": _i(r.get("deductAmt")),
            "seller_id": str(r.get("sellerId") or "")[:40],
            "account": (account or "")[:40],
        })
    return out, skipped


def apply_rows(rows: list, *, session=None) -> dict:
    """주문라인에 실값을 붙인다. 반환 = 무엇이 붙고 무엇이 안 붙었는지 **전부**.

    🔴 못 붙은 건을 숨기지 않는다. 「몇 건 저장」만 돌려주면 조인 축이 어긋나
      0건이 되어도 성공처럼 보인다(라이브에서 실제로 겪은 조용한 실패 유형).
    """
    from sqlalchemy.orm.attributes import flag_modified

    from lemouton.markets.models_orders import MarketOrderLine as L

    own = session is None
    if own:
        from shared.db import SessionLocal
        session = SessionLocal()
    try:
        rep = {"받은건수": len(rows or []), "적용": 0, "값동일": 0, "미매칭": 0,
               "미매칭목록": [], "바뀐금액합": 0, "표본": []}
        by_uid = {r["line_uid"]: r for r in (rows or [])}
        if not by_uid:
            return rep
        found = session.query(L).filter(L.line_uid.in_(list(by_uid))).all()
        hit = {o.line_uid for o in found}
        for uid, r in by_uid.items():
            if uid not in hit:
                rep["미매칭"] += 1
                if len(rep["미매칭목록"]) < 30:
                    rep["미매칭목록"].append(
                        {"주문번호": r["ord_no"], "순번": r["ord_prd_seq"],
                         "정산예정": r["stl_amt"], "상태": r["ord_prd_stat"]})
        for o in found:
            r = by_uid[o.line_uid]
            row = dict(o.row or {})
            before = row.get(SETTLE_FIELD)
            before_src = row.get(SRC_FIELD)
            # 🔴 [2026-08-13] M열(정산예정금액)도 같이 채운다 — 안 채우면 **조용히 지워진다.**
            #   저장분 보강(`order_export` enrich)이 `_finalize_rows` 를 다시 돌리고,
            #   거기서 N 은 `M + 배송비` 로 새로 만들어진다. M 이 비면 N 이 **빈칸**,
            #   M 에 추정치가 있으면 그 추정치로 **덮인다**. 둘 다 마켓 실값이 사라진다.
            #   규약은 구매확정 **후** 빌더와 똑같이 — `M = 실값 − 배송비`(stlAmt 는
            #   stlPlnAmt 처럼 배송비를 품고 있다. 이 모듈 머리글 실측 참고).
            #   🔴 두 벌이 되면 같은 주문이 경로에 따라 다른 값이 된다(원천 분열).
            want_m = r["stl_amt"] - _i(row.get("배송비"))
            _m_now = row.get(SETTLE_M_FIELD)
            _same_m = (_m_now not in (None, "") and _i(_m_now) == want_m
                       and row.get(NET_FLAG) is True)
            if _i(before) == r["stl_amt"] and before_src == "real" and _same_m:
                rep["값동일"] += 1
                continue
            row[SETTLE_FIELD] = r["stl_amt"]
            row[SETTLE_M_FIELD] = want_m
            row[NET_FLAG] = True     # M열=배송비 제외 규약으로 저장됨(구 저장분과 구분)
            row[SRC_FIELD] = "real"
            # 근거를 행에 남긴다 — 나중에 「이 숫자 어디서 왔나」를 답할 수 있게.
            row["_11st_unconf_stat"] = r["ord_prd_stat"]
            row["_11st_unconf_pay_date"] = r["pay_date"]
            o.row = row
            flag_modified(o, "row")
            rep["적용"] += 1
            rep["바뀐금액합"] += r["stl_amt"] - _i(before)
            if len(rep["표본"]) < 8:
                rep["표본"].append(
                    {"주문번호": r["ord_no"], "상태": r["ord_prd_stat"],
                     "이전": before, "이전출처": before_src, "이후": r["stl_amt"]})
        session.commit()
        return rep
    finally:
        if own:
            session.close()
