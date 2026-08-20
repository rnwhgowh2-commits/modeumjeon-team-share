# -*- coding: utf-8 -*-
"""[TEST] 송장 엑셀 업로드 — 열 인식 · 오픈마켓주문번호 매칭.

확정 규칙(사용자):
  ① 엑셀의 「오픈마켓주문번호」 == 주문의 「오픈마켓주문번호」 인 행을 찾는다.
  ② 그 행에 엑셀의 운송장번호를 넣는다.
  · 한 주문 = 송장 1개.
  · 합포장 허용 — 서로 다른 주문번호가 같은 송장번호를 가질 수 있다.
  · 같은 주문번호에 서로 다른 송장번호 = 모순 → 조용히 덮지 말고 오류로 표면화.
"""
import io

import pytest


def _xlsx(rows):
    """rows(list[list]) → xlsx bytes."""
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ── 엑셀 열 인식 ──────────────────────────────────────────────
class TestParse:
    def test_reads_by_header_regardless_of_order(self):
        from lemouton.markets.invoice_excel import parse_invoice_excel
        data = _xlsx([
            ["운송장번호", "택배사", "오픈마켓주문번호"],   # 순서 뒤섞임
            ["1234567890", "로젠택배", "20240710-1234"],
        ])
        rows = parse_invoice_excel(data)
        assert rows == [{"order_no": "20240710-1234",
                         "invoice_no": "1234567890",
                         "courier": "로젠택배"}]

    def test_courier_column_optional(self):
        from lemouton.markets.invoice_excel import parse_invoice_excel
        rows = parse_invoice_excel(_xlsx([["오픈마켓주문번호", "운송장번호"],
                                          ["A1", "111"]]))
        assert rows[0]["courier"] == ""

    def test_송장번호_alias_accepted(self):
        from lemouton.markets.invoice_excel import parse_invoice_excel
        rows = parse_invoice_excel(_xlsx([["오픈마켓주문번호", "송장번호"], ["A1", "111"]]))
        assert rows[0]["invoice_no"] == "111"

    def test_missing_required_column_raises(self):
        from lemouton.markets.invoice_excel import parse_invoice_excel, InvoiceExcelError
        with pytest.raises(InvoiceExcelError):
            parse_invoice_excel(_xlsx([["주문번호", "운송장번호"], ["A1", "111"]]))

    def test_blank_rows_and_spaces_ignored(self):
        from lemouton.markets.invoice_excel import parse_invoice_excel
        rows = parse_invoice_excel(_xlsx([
            ["오픈마켓주문번호", "운송장번호"],
            ["  A1  ", " 111 "],
            [None, None],
            ["", ""],
        ]))
        assert rows == [{"order_no": "A1", "invoice_no": "111", "courier": ""}]

    def test_numeric_cells_become_text(self):
        """엑셀이 숫자로 읽어도 주문번호·송장번호는 문자열로(앞자리 0·지수표기 방지)."""
        from lemouton.markets.invoice_excel import parse_invoice_excel
        rows = parse_invoice_excel(_xlsx([["오픈마켓주문번호", "운송장번호"],
                                          [2024071098765, 1234567890]]))
        assert rows[0]["order_no"] == "2024071098765"
        assert rows[0]["invoice_no"] == "1234567890"


# ── 매칭 ─────────────────────────────────────────────────────
class TestMatch:
    def test_matches_by_open_market_order_no(self):
        from lemouton.markets.invoice_excel import match_invoices
        excel = [{"order_no": "A1", "invoice_no": "111", "courier": "로젠택배"}]
        res = match_invoices(excel, order_nos={"A1", "A2"})
        assert res.matched == {"A1": {"invoice_no": "111", "courier": "로젠택배"}}
        assert res.unmatched == [] and res.conflicts == []

    def test_excel_row_without_matching_order_is_unmatched(self):
        from lemouton.markets.invoice_excel import match_invoices
        excel = [{"order_no": "NOPE", "invoice_no": "111", "courier": ""}]
        res = match_invoices(excel, order_nos={"A1"})
        assert res.matched == {}
        assert res.unmatched == ["NOPE"]

    def test_bundled_shipping_same_invoice_two_orders_allowed(self):
        """합포장 — 다른 주문번호가 같은 송장번호를 갖는 건 정상."""
        from lemouton.markets.invoice_excel import match_invoices
        excel = [{"order_no": "A1", "invoice_no": "111", "courier": ""},
                 {"order_no": "A2", "invoice_no": "111", "courier": ""}]
        res = match_invoices(excel, order_nos={"A1", "A2"})
        assert set(res.matched) == {"A1", "A2"}
        assert res.conflicts == []

    def test_same_order_different_invoice_is_conflict(self):
        """같은 주문번호에 서로 다른 송장번호 = 모순 → 오류, 매칭에서 제외."""
        from lemouton.markets.invoice_excel import match_invoices
        excel = [{"order_no": "A1", "invoice_no": "111", "courier": ""},
                 {"order_no": "A1", "invoice_no": "222", "courier": ""}]
        res = match_invoices(excel, order_nos={"A1"})
        assert res.conflicts == ["A1"]
        assert "A1" not in res.matched          # 조용히 덮어쓰지 않음

    def test_same_order_same_invoice_duplicate_row_is_ok(self):
        """같은 주문·같은 송장이 두 줄이면 멱등 — 모순 아님."""
        from lemouton.markets.invoice_excel import match_invoices
        excel = [{"order_no": "A1", "invoice_no": "111", "courier": ""},
                 {"order_no": "A1", "invoice_no": "111", "courier": ""}]
        res = match_invoices(excel, order_nos={"A1"})
        assert res.matched == {"A1": {"invoice_no": "111", "courier": ""}}
        assert res.conflicts == []

    def test_conflicted_order_never_comes_back_to_matched(self):
        """한 번 모순난 주문은 뒤에 같은 송장 줄이 또 나와도 전송 대상에 복귀하면 안 된다.

        (복귀하면 어느 송장이 맞는지 모른 채 전송 → 오배송)
        """
        from lemouton.markets.invoice_excel import match_invoices
        excel = [{"order_no": "A1", "invoice_no": "111", "courier": ""},
                 {"order_no": "A1", "invoice_no": "222", "courier": ""},
                 {"order_no": "A1", "invoice_no": "111", "courier": ""}]
        res = match_invoices(excel, order_nos={"A1"})
        assert res.conflicts == ["A1"]
        assert "A1" not in res.matched
