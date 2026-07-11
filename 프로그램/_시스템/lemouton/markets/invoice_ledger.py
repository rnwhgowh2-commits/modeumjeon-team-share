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

from lemouton.markets.order_export import _SHIPPED_STATES

# 진짜 송장번호가 아닌 화면 표기값 — 저장/판단에서 '번호 없음'으로 취급.
_SENTINELS = {"", "확인 불가", "송장미입력"}


def _clean(v) -> str:
    return str(v or "").strip()


def _is_real(inv: str) -> bool:
    return bool(inv) and inv not in _SENTINELS


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
    """발송됐는데 송장이 비어('확인 불가') 있는 행을 원장에서 채운다.

    발송 전('송장미입력')·이미 진짜 번호가 있는 행은 건드리지 않는다.
    Returns: 채운 건수.
    """
    from lemouton.sourcing.models_v2 import InvoiceLedger

    # 원장 조회가 필요한 행만 추림(발송완료인데 번호 없음).
    targets = [r for r in rows
               if _clean(r.get("주문상태")) in _SHIPPED_STATES
               and not _is_real(_clean(r.get("송장입력")))
               and _clean(r.get("오픈마켓주문번호"))]
    if not targets:
        return 0

    s, own = _open_session(session)
    filled = 0
    try:
        for r in targets:
            key = {"market": _clean(r.get("판매처")),
                   "order_no": _clean(r.get("오픈마켓주문번호"))}
            row = s.get(InvoiceLedger, key)
            if row is not None and _is_real(_clean(row.invoice_no)):
                r["송장입력"] = row.invoice_no
                filled += 1
    finally:
        if own:
            s.close()
    return filled
