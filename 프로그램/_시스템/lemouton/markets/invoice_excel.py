# -*- coding: utf-8 -*-
"""송장 엑셀 업로드 — 열 인식 · 「오픈마켓주문번호」 매칭.

확정 규칙:
  ① 엑셀의 「오픈마켓주문번호」 == 주문의 「오픈마켓주문번호」 인 행을 찾는다.
  ② 그 행에 엑셀의 운송장번호를 넣는다.

도메인 사실(사용자 확인):
  · 한 주문 = 송장 1개.
  · **합포장 허용** — 서로 다른 주문번호가 같은 송장번호를 가질 수 있다(2주문 1송장).
  · **같은 주문번호에 서로 다른 송장번호 = 모순** → 조용히 덮어쓰지 않고 오류로 표면화.
    (조용히 덮으면 송장이 뒤바뀌어 오배송 — CLAUDE.md 무결성 원칙)

주문번호·송장번호는 항상 문자열로 다룬다(엑셀이 숫자로 읽어 앞자리 0·지수표기가 깨지는 것 방지).
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import Iterable

ORDER_NO_HEADERS = ("오픈마켓주문번호",)
INVOICE_HEADERS = ("운송장번호", "송장번호")
COURIER_HEADERS = ("택배사",)


class InvoiceExcelError(ValueError):
    """엑셀 형식 오류(필수 열 없음 등)."""


def _cell_text(v) -> str:
    """셀 값 → 문자열. 숫자는 정수면 정수 문자열로(1234567890.0 방지)."""
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip()


def parse_invoice_excel(data: bytes) -> list[dict]:
    """xlsx 바이트 → [{order_no, invoice_no, courier}]. 헤더 이름으로 열을 찾는다(순서 무관)."""
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        raise InvoiceExcelError("빈 엑셀입니다.")

    header = [_cell_text(c) for c in rows[0]]

    def find(names) -> int:
        for i, h in enumerate(header):
            if h in names:
                return i
        return -1

    i_order, i_inv, i_cr = find(ORDER_NO_HEADERS), find(INVOICE_HEADERS), find(COURIER_HEADERS)
    if i_order < 0:
        raise InvoiceExcelError("「오픈마켓주문번호」 열이 없습니다.")
    if i_inv < 0:
        raise InvoiceExcelError("「운송장번호」(또는 「송장번호」) 열이 없습니다.")

    out: list[dict] = []
    for r in rows[1:]:
        order_no = _cell_text(r[i_order]) if i_order < len(r) else ""
        invoice_no = _cell_text(r[i_inv]) if i_inv < len(r) else ""
        if not order_no or not invoice_no:      # 빈 줄·불완전 줄은 건너뜀
            continue
        courier = _cell_text(r[i_cr]) if 0 <= i_cr < len(r) else ""
        out.append({"order_no": order_no, "invoice_no": invoice_no, "courier": courier})
    return out


@dataclass
class MatchResult:
    """매칭 결과. matched 만 전송 대상."""
    matched: dict[str, dict] = field(default_factory=dict)   # 주문번호 → {invoice_no, courier}
    unmatched: list[str] = field(default_factory=list)       # 엑셀엔 있으나 주문에 없음
    conflicts: list[str] = field(default_factory=list)       # 같은 주문에 다른 송장(모순)


def match_invoices(excel_rows: Iterable[dict], order_nos: Iterable[str]) -> MatchResult:
    """엑셀 행 ↔ 주문의 「오픈마켓주문번호」 매칭.

    합포장(다른 주문·같은 송장)은 정상. 같은 주문에 다른 송장은 conflicts 로 빼고 전송 제외.
    """
    known = {str(n) for n in order_nos}
    res = MatchResult()
    seen_unmatched: set[str] = set()
    conflicted: set[str] = set()   # 한 번 모순난 주문은 영구 제외(복귀 금지)

    for row in excel_rows:
        order_no = str(row.get("order_no") or "")
        invoice_no = str(row.get("invoice_no") or "")
        courier = str(row.get("courier") or "")
        if not order_no or not invoice_no:
            continue

        if order_no in conflicted:      # 뒤에 같은 송장이 또 나와도 되살리지 않는다
            continue

        if order_no not in known:
            if order_no not in seen_unmatched:
                seen_unmatched.add(order_no)
                res.unmatched.append(order_no)
            continue

        prev = res.matched.get(order_no)
        if prev is None:
            res.matched[order_no] = {"invoice_no": invoice_no, "courier": courier}
        elif prev["invoice_no"] != invoice_no:
            # 모순 — 어느 쪽이 맞는지 알 수 없으므로 전송 대상에서 영구 제외(조용한 덮어쓰기 금지)
            conflicted.add(order_no)
            res.conflicts.append(order_no)
            res.matched.pop(order_no, None)
        # 같은 주문·같은 송장 중복 줄 → 멱등(무시)

    return res
