# -*- coding: utf-8 -*-
"""[TEST] 「주문 내역」 송장 라우트 — 엑셀 업로드 매칭 · 전송(드라이런 게이트).

안전 규칙(테스트로 못박음):
  · 요청이 live=true 라도 서버 전역 스위치(MOUM_LIVE_UPLOAD)가 꺼져 있으면 실제 전송 금지.
  · 미지원 마켓·식별자 없음은 조용히 성공하지 않는다.
"""
import io
import json

import pytest
from flask import Flask

from webapp.routes import orders as om


@pytest.fixture
def client():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(om.bp)
    return app.test_client()


def _xlsx(rows):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


# ── 업로드·매칭 ──────────────────────────────────────────────
class TestUpload:
    def test_upload_matches_by_open_market_order_no(self, client):
        data = {
            "file": (_xlsx([["오픈마켓주문번호", "택배사", "운송장번호"],
                            ["A1", "로젠택배", "111"],
                            ["NOPE", "로젠택배", "999"]]), "송장.xlsx"),
            "order_nos": "A1,A2",
        }
        r = client.post("/orders/invoice/upload", data=data,
                        content_type="multipart/form-data")
        assert r.status_code == 200
        body = r.get_json()
        assert body["ok"] is True
        assert body["matched"] == {"A1": {"invoice_no": "111", "courier": "로젠택배"}}
        assert body["unmatched"] == ["NOPE"]
        assert body["conflicts"] == []

    def test_upload_reports_conflict(self, client):
        data = {
            "file": (_xlsx([["오픈마켓주문번호", "운송장번호"],
                            ["A1", "111"], ["A1", "222"]]), "송장.xlsx"),
            "order_nos": "A1",
        }
        body = client.post("/orders/invoice/upload", data=data,
                           content_type="multipart/form-data").get_json()
        assert body["conflicts"] == ["A1"]
        assert "A1" not in body["matched"]

    def test_upload_bad_columns_is_400(self, client):
        data = {"file": (_xlsx([["주문번호", "운송장번호"], ["A1", "1"]]), "x.xlsx"),
                "order_nos": "A1"}
        r = client.post("/orders/invoice/upload", data=data,
                        content_type="multipart/form-data")
        assert r.status_code == 400
        assert "오픈마켓주문번호" in r.get_json()["error"]

    def test_upload_without_file_is_400(self, client):
        r = client.post("/orders/invoice/upload", data={"order_nos": "A1"},
                        content_type="multipart/form-data")
        assert r.status_code == 400


# ── 전송(드라이런 게이트) ────────────────────────────────────
def _send_body(live, market="coupang"):
    return {"live": live, "rows": [{
        "market": market, "order_no": "100", "courier": "로젠택배",
        "invoice_no": "1234567890", "alias": "브랜드마켓",
        "send_ids": {"shipment_box_id": "SB1", "order_sheet_id": "100"},
    }]}


class TestSend:
    def test_default_is_dry_run_no_external_call(self, client, monkeypatch):
        import shared.platforms.coupang.orders as cp
        called = []
        monkeypatch.setattr(cp, "send_tracking", lambda *a, **k: called.append(1))

        body = client.post("/orders/invoice/send", json=_send_body(live=False)).get_json()
        assert body["ok"] is True and body["live"] is False
        assert body["results"][0]["dry_run"] is True
        assert called == []

    def test_route_gate_reads_invoice_switch_not_upload_switch(self, monkeypatch):
        """/orders 의 게이트는 MOUM_LIVE_INVOICE 를 본다 — 가격·재고 스위치가 아니라."""
        monkeypatch.delenv("MOUM_LIVE_UPLOAD", raising=False)
        monkeypatch.delenv("MOUM_LIVE_INVOICE", raising=False)
        assert om._live_enabled() is False

        monkeypatch.setenv("MOUM_LIVE_INVOICE", "1")
        assert om._live_enabled() is True

    def test_live_request_refused_when_global_switch_off(self, client, monkeypatch):
        """요청이 live=true 라도 전역 스위치 OFF 면 실제 전송하지 않는다."""
        import shared.platforms.coupang.orders as cp
        called = []
        monkeypatch.setattr(cp, "send_tracking", lambda *a, **k: called.append(1))
        monkeypatch.setattr(om, "_live_enabled", lambda: False)

        body = client.post("/orders/invoice/send", json=_send_body(live=True)).get_json()
        assert body["live"] is False                  # 서버가 강등
        assert body["results"][0]["dry_run"] is True
        assert called == []                           # 실제 전송 없음

    def test_live_send_when_switch_on(self, client, monkeypatch):
        got = {}

        def fake(shipment_box_id, order_sheet_id, delivery_company_code, invoice_number, client=None):
            got.update(sb=shipment_box_id, code=delivery_company_code, inv=invoice_number)
            return {"code": 200}

        import shared.platforms.coupang.orders as cp
        monkeypatch.setattr(cp, "send_tracking", fake)
        monkeypatch.setattr(om, "_live_enabled", lambda: True)
        monkeypatch.setattr(om, "_client_for", lambda market, alias: None)

        body = client.post("/orders/invoice/send", json=_send_body(live=True)).get_json()
        assert body["live"] is True
        assert body["results"][0]["success"] is True
        assert body["results"][0]["dry_run"] is False
        assert got == {"sb": "SB1", "code": "KGB", "inv": "1234567890"}
        assert body["sent"] == 1 and body["failed"] == 0

    def test_success_carries_market_readback_number(self, client, monkeypatch):
        """실전송 성공 시 응답에 마켓 재조회 송장번호가 실린다(화면 표시 기준)."""
        import shared.platforms.coupang.orders as cp
        from lemouton.markets import invoice_send as isend
        monkeypatch.setattr(cp, "send_tracking", lambda *a, **k: {"code": 200})
        monkeypatch.setattr(om, "_live_enabled", lambda: True)
        monkeypatch.setattr(om, "_client_for", lambda market, alias: None)
        monkeypatch.setattr(isend, "read_registered_invoice",
                            lambda **k: "614199998888")

        body = client.post("/orders/invoice/send", json=_send_body(live=True)).get_json()
        assert body["results"][0]["success"] is True
        assert body["results"][0]["market_invoice_no"] == "614199998888"

    def test_dry_run_does_not_read_back(self, client, monkeypatch):
        """미리보기는 마켓을 되읽지 않는다(외부 조회 0)."""
        import shared.platforms.coupang.orders as cp
        from lemouton.markets import invoice_send as isend
        monkeypatch.setattr(cp, "send_tracking", lambda *a, **k: None)
        monkeypatch.setattr(om, "_live_enabled", lambda: False)
        called = []
        monkeypatch.setattr(isend, "read_registered_invoice",
                            lambda **k: called.append(1))

        body = client.post("/orders/invoice/send", json=_send_body(live=True)).get_json()
        assert body["results"][0]["dry_run"] is True
        assert body["results"][0]["market_invoice_no"] is None
        assert called == []

    def test_unsupported_market_fails_loudly(self, client, monkeypatch):
        """옥션은 발송처리 미구현 → 조용히 성공하지 않고 실패로 집계."""
        monkeypatch.setattr(om, "_live_enabled", lambda: True)
        monkeypatch.setattr(om, "_client_for", lambda market, alias: None)
        body = client.post("/orders/invoice/send",
                           json=_send_body(live=True, market="auction")).get_json()
        assert body["results"][0]["success"] is False
        assert "auction" in body["results"][0]["error"]
        assert body["sent"] == 0 and body["failed"] == 1

    def test_eleven11_sends_with_dlv_no(self, client, monkeypatch):
        """11번가는 배송번호(dlvNo)로 발송처리한다 — 로젠 코드 00002(실측 확정)."""
        import shared.platforms.eleven11.shipping as el
        got = {}
        monkeypatch.setattr(el, "send_tracking", lambda **k: got.update(k) or True)
        monkeypatch.setattr(om, "_live_enabled", lambda: True)
        monkeypatch.setattr(om, "_client_for", lambda market, alias: None)

        body = _send_body(live=True, market="eleven11")
        body["rows"][0]["send_ids"] = {"dlv_no": "D77", "ord_no": "100", "ord_prd_seq": "1"}
        res = client.post("/orders/invoice/send", json=body).get_json()
        assert res["results"][0]["success"] is True
        assert got["dlv_no"] == "D77" and got["delivery_company_code"] == "00002"

    def test_eleven11_blocked_when_courier_unverified(self, client, monkeypatch):
        """실계정으로 대조하지 못한 택배사(CJ)는 조용히 보내지 않는다."""
        import shared.platforms.eleven11.shipping as el
        called = []
        monkeypatch.setattr(el, "send_tracking", lambda **k: called.append(1))
        monkeypatch.setattr(om, "_live_enabled", lambda: True)
        monkeypatch.setattr(om, "_client_for", lambda market, alias: None)

        body = _send_body(live=True, market="eleven11")
        body["rows"][0]["courier"] = "CJ대한통운"
        body["rows"][0]["send_ids"] = {"dlv_no": "D77"}
        res = client.post("/orders/invoice/send", json=body).get_json()
        assert res["results"][0]["success"] is False
        assert "택배사 코드" in res["results"][0]["error"]
        assert called == []


class TestInvoiceLedgerWiring:
    """조회 시 송장 원장이 적용돼, 한 번 본 송장번호를 잃지 않는다."""

    def test_preview_applies_ledger(self, client, monkeypatch):
        seen = {}
        monkeypatch.setattr(om._oe, "combined_order_rows",
                            lambda *a, **k: [{"판매처": "11번가", "오픈마켓주문번호": "O1",
                                              "송장입력": "확인 불가", "주문상태": "구매확정"}])

        def fake_remember(rows, **k): seen["remember"] = True
        def fake_fill(rows, **k):
            seen["fill"] = True
            rows[0]["송장입력"] = "9988776655"
        import lemouton.markets.invoice_ledger as led
        monkeypatch.setattr(led, "remember", fake_remember)
        monkeypatch.setattr(led, "fill_missing", fake_fill)

        body = client.get("/orders/preview.json?markets=eleven11&days=7").get_json()
        assert seen == {"remember": True, "fill": True}
        assert body["rows"][0]["송장입력"] == "9988776655"

    def test_ledger_failure_does_not_break_preview(self, client, monkeypatch):
        """원장(DB) 오류가 나도 주문 화면은 원본 그대로 뜬다."""
        monkeypatch.setattr(om._oe, "combined_order_rows",
                            lambda *a, **k: [{"판매처": "쿠팡", "오픈마켓주문번호": "O1",
                                              "송장입력": "111", "주문상태": "배송완료"}])
        import lemouton.markets.invoice_ledger as led
        monkeypatch.setattr(led, "remember",
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down")))

        r = client.get("/orders/preview.json?markets=coupang&days=7")
        assert r.status_code == 200
        assert r.get_json()["rows"][0]["송장입력"] == "111"

    def test_empty_rows_is_400(self, client):
        r = client.post("/orders/invoice/send", json={"live": False, "rows": []})
        assert r.status_code == 400
