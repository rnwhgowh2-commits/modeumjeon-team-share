# -*- coding: utf-8 -*-
"""송장 원장 — 한 번 본 송장번호를 영구 보관하고, 나중에 '확인 불가'를 채운다.

문제: 11번가는 주문이 '구매확정'으로 넘어가면 어떤 목록 API로도 송장번호(invcNo)를
      돌려주지 않는다(배송중·배송완료 목록엔 있으나 상태 전이 후 빠짐, 2026-07-10 실측).
      그러면 이미 발송된 주문인데 화면에 '확인 불가'로 뜬다.

해법: 배송중·배송완료 때 본 송장번호를 DB(invoice_ledger)에 저장(``remember``)해두고,
      번호가 빈 발송완료 주문은 저장분에서 채운다(``fill_missing``). 모든 마켓 공통.

정직성:
  · 발송 전('송장미입력')은 채우지 않는다 — 아직 송장이 없는 게 맞다.
  · 저장된 적 없는 과거 주문은 '확인 불가'로 남긴다(번호를 지어내지 않는다).
  · API 실값이 있으면 그걸 우선한다(원장은 빈 곳만 메운다).
"""
from __future__ import annotations

from typing import Optional

from lemouton.markets.order_export import _SHIPPED_STATES, is_invoice_no

# 진짜 송장번호가 아닌 화면 표기값 — 저장/판단에서 '번호 없음'으로 취급.
_SENTINELS = {"", "확인 불가", "송장미입력"}

# 클레임으로 끝난 주문도 '한때 발송됐던' 주문이다 — 그때 우리가 실제로 본 번호가 원장에
#  있으면 채운다. 마켓 API 는 클레임 행에 원배송 송장을 안 준다(쿠팡 반품조회는 **회수**
#  송장만 준다 — 2026-07-23 지도 확인). 발송 전에 취소된 주문은 원장에 없어 그대로 남는다
#  (없는 번호를 지어내지 않는다).
_ONCE_SHIPPED_STATES = {"반품요청", "반품완료", "교환요청", "교환완료", "미수령신고",
                        "취소요청", "취소완료", "회수지시", "회수진행", "회수완료",
                        "회수확정", "철회"}
_FILLABLE_STATES = _SHIPPED_STATES | _ONCE_SHIPPED_STATES


def _clean(v) -> str:
    return str(v or "").strip()


def _is_real(inv: str) -> bool:
    """진짜 송장번호인가. 상태 문구('송장입력됨' 등)는 번호가 아니다(is_invoice_no)."""
    return bool(inv) and inv not in _SENTINELS and bool(is_invoice_no(inv))


def _open_session(session):
    """session 이 주어지면 그대로(호출자 소유), 없으면 SessionLocal 로 연다(우리 소유)."""
    if session is not None:
        return session, False
    from shared.db import SessionLocal
    return SessionLocal(), True


def remember(rows, *, session=None) -> int:
    """발송된 상태이고 진짜 송장번호가 있는 행을 (판매처, 주문번호) 키로 upsert.

    Returns: 저장(신규+갱신)한 건수.
    """
    from lemouton.sourcing.models_v2 import InvoiceLedger

    s, own = _open_session(session)
    saved = 0
    # ★ 한 배치에 같은 (판매처,주문번호)가 여러 번 온다(11번가는 한 주문에 상품라인 여러 개).
    #   프로덕션 SessionLocal 은 autoflush=False 라 s.get 이 방금 add 한 형제를 못 봐,
    #   그대로 두면 중복 PK 로 commit 이 통째로 터져 0건 저장된다. 이 배치에서 이미 다룬
    #   객체를 pending 에 들고 있다가 재사용(마지막 값이 이긴다).
    pending: dict = {}
    try:
        for r in rows:
            status = _clean(r.get("주문상태"))
            if status not in _SHIPPED_STATES:
                continue
            inv = _clean(r.get("송장입력"))
            if not _is_real(inv):
                continue
            market = _clean(r.get("판매처"))
            order_no = _clean(r.get("오픈마켓주문번호"))
            if not market or not order_no:
                continue
            courier = _clean(r.get("택배사"))
            key = (market, order_no)
            row = pending.get(key)
            if row is None:
                row = s.get(InvoiceLedger, {"market": market, "order_no": order_no})
            if row is None:
                row = InvoiceLedger(market=market, order_no=order_no,
                                    invoice_no=inv, courier=courier or None)
                s.add(row)
            else:
                row.invoice_no = inv
                if courier:
                    row.courier = courier
            pending[key] = row
            saved += 1
        s.commit()
    finally:
        if own:
            s.close()
    return saved


def fill_missing(rows, *, session=None) -> int:
    """발송됐는데 송장번호·택배사가 빈 행을 원장에서 채운다.

    반품·교환처럼 클레임으로 끝난 행도 대상이다(_ONCE_SHIPPED_STATES) — 원장에 있으면
    그건 우리가 그 주문을 발송할 때 실제로 본 값이다. 원장에 없으면 그대로 둔다.
    발송 전('송장미입력')이고 원장에도 없는 행은 건드리지 않는다.

    ★택배사도 같이 채운다(사장님 요청 2026-07-25) — 마켓 주문조회가 택배사를 주는 곳은
      ESM(TakbaeName)뿐이라, 쿠팡·롯데온·스스·11번가는 화면에서 늘 비어 있었다.
      **우리가 송장을 보낼 때 고른 택배사**가 원장에 남으므로(orders.py 송장 전송 성공 시
      remember_sent), 그 값을 되채우면 전 마켓에서 정확한 이름이 나온다.
      ⚠️ 번호가 이미 있어도 택배사만 비면 채운다 — 둘은 서로 다른 칸이다.
      ⚠️ 원장에 없으면 비워 둔다(이름 날조 금지 — 무결성 1원칙).
    Returns: 채운 건수(번호·택배사 어느 쪽이든 채웠으면 1).
    """
    from lemouton.sourcing.models_v2 import InvoiceLedger

    # 원장 조회가 필요한 행 — 번호가 없거나(기존) 택배사가 없는(신규) 발송건.
    targets = [r for r in rows
               if _clean(r.get("주문상태")) in _FILLABLE_STATES
               and _clean(r.get("오픈마켓주문번호"))
               and (not _is_real(_clean(r.get("송장입력")))
                    or not _clean(r.get("택배사")))]
    if not targets:
        return 0

    s, own = _open_session(session)
    filled = 0
    try:
        # [2026-08-06 PERF] 원장 조회를 **한 행에 한 번**(s.get) 씩 하던 것을 마켓별
        #   묶음 조회로 바꾼다. 실측(라이브 /orders/flow-daily.json?days=1):
        #   DB 1,066쿼리·5.8초 — 그 대부분이 여기였다. 주문 적재분을 읽는 모든 화면
        #   (주문내역·마진·정산·폰 주문)이 이 함수를 지난다.
        #   ★ 고르는 값·판정은 아래 루프 그대로다 — 조회 방법만 바꾼다(숫자 불변).
        #   ★ IN 절 길이 상한은 remember/load 와 같은 관례로 900개씩 끊는다.
        ledger: dict[tuple[str, str], object] = {}
        by_market: dict[str, list[str]] = {}
        for r in targets:
            by_market.setdefault(_clean(r.get("판매처")), []).append(
                _clean(r.get("오픈마켓주문번호")))
        for market, order_nos in by_market.items():
            uniq = sorted(set(order_nos))
            for i in range(0, len(uniq), 900):
                got = (s.query(InvoiceLedger)
                        .filter(InvoiceLedger.market == market,
                                InvoiceLedger.order_no.in_(uniq[i:i + 900]))
                        .all())
                for row in got:
                    ledger[(row.market, row.order_no)] = row

        for r in targets:
            row = ledger.get((_clean(r.get("판매처")),
                              _clean(r.get("오픈마켓주문번호"))))
            if row is None:
                continue
            hit = False
            if not _is_real(_clean(r.get("송장입력"))) and _is_real(_clean(row.invoice_no)):
                r["송장입력"] = row.invoice_no
                hit = True
            if not _clean(r.get("택배사")) and _clean(row.courier):
                r["택배사"] = row.courier
                hit = True
            if hit:
                filled += 1
    finally:
        if own:
            s.close()
    return filled


def remember_sent(market: str, order_no: str, invoice_no: str,
                  courier: str = "", *, session=None) -> bool:
    """우리가 **방금 마켓으로 보낸** 송장·택배사를 원장에 기록한다. 저장했으면 True.

    ★왜 필요한가(사장님 요청 2026-07-25) — 마켓 주문조회가 택배사를 돌려주는 곳은
      ESM(TakbaeName)뿐이다. 쿠팡·롯데온·스스·11번가는 아무리 조회해도 택배사가 안 온다.
      그런데 **우리가 보낼 때는 택배사를 직접 골랐다** — 그 값이 가장 정확한 원천이다.
      전송 성공 시 여기 남겨 두면 다음 조회부터 fill_missing 이 화면에 채워 준다.

    ★remember(조회분 일괄)와 달리 '방금 전송한 한 건'을 받는다 — 조회 응답이 택배사를
      안 주는 마켓에서도 확실히 남길 수 있는 유일한 지점이다.
    ★기존 값을 지우지 않는다(빈 courier 로 덮어쓰기 금지).
    """
    from lemouton.sourcing.models_v2 import InvoiceLedger

    market, order_no = _clean(market), _clean(order_no)
    inv, cr = _clean(invoice_no), _clean(courier)
    if not market or not order_no or not _is_real(inv):
        return False

    s, own = _open_session(session)
    try:
        row = s.get(InvoiceLedger, {"market": market, "order_no": order_no})
        if row is None:
            s.add(InvoiceLedger(market=market, order_no=order_no,
                                invoice_no=inv, courier=cr or None))
        else:
            row.invoice_no = inv
            if cr:                      # 빈 값이 실값을 덮지 않게
                row.courier = cr
        s.commit()
        return True
    finally:
        if own:
            s.close()
