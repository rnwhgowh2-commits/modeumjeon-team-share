# -*- coding: utf-8 -*-
"""롯데온 셀러오피스 주문 크롤분 — 업서트·채움·누락 취소라인 추가·상태 교정.

왜 이 소스가 필요한가(2026-07-23 샵마인 387건 대조로 확정):
  ① 취소완료 주문의 상품 라인이 통째 누락 — 부분취소(수취완료+취소 2라인) 주문의
     취소 라인을 OpenAPI 가 안 준다(018057538·018074798 실측).
  ② 취소완료 주문의 구매자·수령자 — 클레임 API 42필드 전수조사에도 없음.
  ③ 철회 취소(철회 접수 후 정상 수취완료 복귀) — 140 진행단계에 신호 없음
     (철회 레코드가 최신이라 못 덮음, 1917781423 실측).
셀러오피스 화면(soapi)이 이 셋의 유일한 원천 — 샵마인이 보던 그 데이터다.
수집=확장(moum-crawler, 로컬 크롬 로그인 세션) → push=/api/orders-ingest/lotteon-so-upsert.

원칙: 빈칸만 채움(날조 금지)·상태 교정은 SO 원문이 정상완료류일 때만(marker 표식).
"""
from __future__ import annotations

import re as _re


def _norm(v) -> str:
    s = str(v if v is not None else "").strip()
    # 셀러오피스/엑셀 경유 HTML 이스케이프(&lt; 등) 정규화 — 대조 실측(샵 파일 &lt;매장정품&gt;)
    return (s.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&"))


def upsert_rows(rows: list, *, session) -> dict:
    """확장이 push 한 정규화 라인들을 (od_no, od_seq) 업서트. 멱등.

    같은 배치 안 중복 키는 마지막 값 채택(pending 충돌 방지 — shopmine-upsert 와 동형).
    od_no 없는 라인은 스킵(카운트 보고 — 조용한 실패 금지).
    """
    from lemouton.markets.models_shopmine import LotteonSoOrder
    seen: dict = {}
    skipped = 0
    for r in rows or []:
        od = _norm(r.get("od_no"))
        # 롯데온 주문번호는 숫자만 — 진단 프로브 등 오염 행이 테이블에 남지 않게 차단.
        if not od or not od.isdigit():
            skipped += 1
            continue
        # ★(odNo, odSeq, procSeq) 3키 — procSeq 를 빼면 취소(2)가 원주문(1)을 덮어써
        #   부분취소가 통째 사라진다(2026072218515514 라이브 실측).
        seen[(od, _norm(r.get("od_seq")) or "1", _norm(r.get("proc_seq")) or "1")] = r
    new = updated = 0
    for (od, seq, pseq), r in seen.items():
        row = session.get(LotteonSoOrder, (od, seq, pseq))
        if row is None:
            row = LotteonSoOrder(od_no=od, od_seq=seq, proc_seq=pseq)
            session.add(row)
            new += 1
        else:
            updated += 1
        row.status = _norm(r.get("status"))
        row.status_code = _norm(r.get("status_code"))
        row.od_typ = _norm(r.get("od_typ"))
        row.claimed_at = _norm(r.get("claimed_at"))
        row.ch_no = _norm(r.get("ch_no"))
        row.discount = _norm(r.get("discount"))
        row.ship_fee = _norm(r.get("ship_fee"))
        row.ordered_at = _norm(r.get("ordered_at"))
        row.product_name = _norm(r.get("product_name"))
        row.option1 = _norm(r.get("option1"))
        row.qty = _norm(r.get("qty"))
        row.unit_price = _norm(r.get("unit_price"))
        row.paid_amount = _norm(r.get("paid_amount"))
        row.buyer = _norm(r.get("buyer"))
        row.recipient = _norm(r.get("recipient"))
        row.phone = _norm(r.get("phone"))
        row.buyer_phone = _norm(r.get("buyer_phone"))
        row.zipcode = _norm(r.get("zipcode"))
        row.address = _norm(r.get("address"))
        row.tr_no = _norm(r.get("tr_no"))
        row.raw = dict(r)
    session.commit()
    return {"new": new, "updated": updated, "skipped_no_odno": skipped}


# SO 열 → 우리 행 열 (빈칸 채움 대상)
_FILL_MAP = [("buyer", "구매자"), ("recipient", "수령자"), ("phone", "수령자전화번호"),
             ("buyer_phone", "구매자번호"), ("zipcode", "우편번호"), ("address", "주소"),
             ("product_name", "상품명"), ("option1", "옵션"), ("qty", "수량"),
             ("unit_price", "단가"), ("paid_amount", "실결제금액"),
             ("ordered_at", "주문일")]

# 주문 단위(어느 라인이든 동일) — 라인 특정 안 돼도 채워도 안전한 열
_ORDER_LEVEL = {"구매자", "수령자", "수령자전화번호", "구매자번호", "우편번호", "주소", "주문일"}

def _to_int_seq(v) -> int:
    """procSeq 정렬용 — 숫자 아니면 0(정렬 뒤로)."""
    try:
        return int(str(v).strip() or 0)
    except (TypeError, ValueError):
        return 0


_NORMAL_DONE = _re.compile(r"수취완료|배송완료|구매확정")
_CLAIMY = _re.compile(r"취소|철회|회수|반품|교환")


def fill_from_so(session, targets: list) -> None:
    """롯데온 행의 빈칸을 SO 크롤분으로 채움 + 철회 잔존 상태 교정.

    · 빈칸만 채운다. 라인 금액류(단가·수량·실결제)는 SO 라인이 특정될 때만
      (그 주문의 SO 라인이 1개, 또는 옵션 텍스트 일치) — 다품 오채움 금지.
    · 상태 교정: 우리 행이 철회·회수 진행형인데 그 주문의 SO 라인(옵션 일치 또는
      단일)이 수취완료/배송완료류(취소·회수 아님)면 = 철회가 취소된 것 —
      SO 상태로 교정하고 _kind(change) 해제(_so_status_fixed 표식).
    """
    from lemouton.markets.models_shopmine import LotteonSoOrder
    onos = {str(r.get("오픈마켓주문번호") or "").strip() for r in targets}
    onos.discard("")
    if not onos:
        return
    by_od: dict = {}
    for o in (session.query(LotteonSoOrder)
              .filter(LotteonSoOrder.od_no.in_(sorted(onos))).all()):
        by_od.setdefault(o.od_no, []).append(o)

    for r in targets:
        od = str(r.get("오픈마켓주문번호") or "").strip()
        lines = by_od.get(od)
        if not lines:
            continue
        # 라인 특정 — 단일 라인이거나 옵션 텍스트 일치
        opt = _norm(r.get("옵션"))
        line = lines[0] if len(lines) == 1 else None
        if line is None and opt:
            hits = [x for x in lines if _norm(x.option1) and _norm(x.option1) == opt]
            if len(hits) == 1:
                line = hits[0]
        # 상태(취소완료/배송완료)까지 같은 라인이 하나뿐이면 그것으로 특정 — 부분취소
        # 주문에서 취소 행이 배송완료 라인의 금액을 집어가는 것을 막는다.
        if line is None:
            st_our = str(r.get("주문상태") or "")
            same = [x for x in lines if _norm(x.status) and _norm(x.status) in st_our]
            if len(same) == 1:
                line = same[0]
        filled = []
        for src_col, our_col in _FILL_MAP:
            if str(r.get(our_col) or "").strip():
                continue                              # 이미 있는 값은 안 덮는다
            src_row = line if line is not None else (
                lines[0] if our_col in _ORDER_LEVEL else None)
            if src_row is None:
                continue                              # 라인 미특정 — 금액류 안 붙임
            v = getattr(src_row, src_col, "") or ""
            if not v:
                continue
            r[our_col] = v
            filled.append(our_col)
        if filled:
            r["_so_filled"] = " ".join(filled)
        # ── 제휴 판별 보강 — 주문 API 가 취소건엔 유입채널(chNo)을 안 준다.
        #   셀러오피스 크롤 라인엔 그 값이 있어(2026-07-23 실측) 확정으로 승격한다.
        #   이미 확정(제휴/롯데ON)인 행은 건드리지 않는다.
        route = str(r.get("판매경로") or "")
        if route in ("", "미확인", "확인 불가"):
            src_line = line if line is not None else lines[0]
            ch = _norm(getattr(src_line, "ch_no", ""))
            if ch:
                from lemouton.markets.order_export import _lo_channel_affiliate
                by = _lo_channel_affiliate(ch)
                if by is not None:
                    r["판매경로"] = "제휴" if by else "롯데ON"
                    r["_lo_is_affiliate"] = by
                    r["_판매경로사유"] = (f"셀러오피스 크롤의 유입채널 {ch} 로 확정"
                                       + ("(제휴 채널)" if by else "(롯데ON 직영 채널)"))
                else:
                    r["판매경로"] = "확인 불가"
                    r["_판매경로사유"] = (f"셀러오피스 크롤에서 유입채널 {ch} 를 받았지만 "
                                       "제휴/직영 분류표에 없는 채널입니다.")
            elif route == "미확인":
                # 수집은 됐는데 원천에 채널값이 없다 = 봐도 없는 것 → 확인 불가로 승격.
                r["판매경로"] = "확인 불가"
                r["_판매경로사유"] = ("셀러오피스 크롤에는 이 주문이 있지만 유입채널 값이 "
                                   "없습니다(마켓이 안 줌).")

        # ── 철회 잔존 교정 — SO(셀러오피스 현재 화면)가 정답(샵마인과 같은 원천) ──
        #  ★기준 = **같은 주문라인(odSeq)의 procSeq 최댓값 = 그 라인의 현재 상태**.
        #   철회는 '접수' 상태라 취소되면 같은 라인이 procSeq 를 하나 더 달고 수취완료로
        #   돌아온다(1917781423 실측). 옵션만 보면 두 라인이 같아 특정이 안 되고, 우리
        #   상태(철회)와 같은 라인을 고르면 영영 교정이 안 걸린다.
        #   odSeq 가 다른 라인은 '다른 상품'이라 부분취소이므로 절대 섞지 않는다.
        st = str(r.get("주문상태") or "")
        if "철회" in st or "회수" in st:
            odseq = str(r.get("_odseq") or "").strip()
            same_line = [x for x in lines if str(x.od_seq or "") == odseq] if odseq else []
            cur = None
            if same_line:
                cur = max(same_line, key=lambda x: _to_int_seq(x.proc_seq))
            elif line is not None:
                cur = line                       # odSeq 없으면 기존 특정 라인으로 판단
            if cur is not None:
                so_st = _norm(cur.status)
                if _NORMAL_DONE.search(so_st) and not _CLAIMY.search(so_st):
                    r["주문상태"] = _NORMAL_DONE.search(so_st).group(0)
                    r["주문상태원본"] = so_st
                    r.pop("_kind", None)
                    r.pop("_change_date", None)
                    r["_so_status_fixed"] = "1"


def add_missing_claims(rows: list, session) -> list:
    """우리 행에 없는 SO 취소완료 라인을 클레임 행으로 추가(부분취소 라인누락 복원).

    대상 = rows 에 등장하는 롯데온 주문번호의 SO 라인 중 상태에 '취소완료'가 있고,
    그 주문에 우리 취소류 행이 하나도 없는 것(보수적 — 다중 취소라인 부분누락은
    옵션 매칭이 애매해 안 만든다·날조 금지). zero_cancel(_finalize)이 정산 0·K=원금
    처리하므로 여기선 라인 사실만 만든다.
    """
    from lemouton.markets.models_shopmine import LotteonSoOrder
    onos = {str(r.get("오픈마켓주문번호") or "").strip() for r in rows
            if str(r.get("판매처") or "") == "롯데온"}
    onos.discard("")
    if not onos:
        return rows
    has_claim = {str(r.get("오픈마켓주문번호") or "").strip()
                 for r in rows if _CLAIMY.search(str(r.get("주문상태") or ""))}
    added = []
    for o in (session.query(LotteonSoOrder)
              .filter(LotteonSoOrder.od_no.in_(sorted(onos))).all()):
        if "취소완료" not in (o.status or ""):
            continue
        if o.od_no in has_claim:
            continue
        added.append({
            "판매처": "롯데온", "쇼핑몰": "롯데온", "쇼핑몰ID": "",
            "_kind": "change", "_so_added": "1",
            "주문일": o.ordered_at or "", "_change_date": o.ordered_at or "",
            "주문상태": "취소완료", "주문상태원본": o.status or "",
            "오픈마켓주문번호": o.od_no,
            "상품명": o.product_name or "", "옵션": o.option1 or "",
            "수량": o.qty or "", "단가": o.unit_price or "",
            "실결제금액": o.paid_amount or "",
            "구매자": o.buyer or "", "수령자": o.recipient or "",
            "수령자전화번호": o.phone or "", "구매자번호": o.buyer_phone or "",
            "우편번호": o.zipcode or "", "주소": o.address or "",
            "배송메시지": "", "옵션추가금": 0, "배송비": 0,
            "정산예정금액": "", "_settle_source": "none",
        })
        has_claim.add(o.od_no)                        # 같은 주문 중복 추가 방지
    return rows + added
