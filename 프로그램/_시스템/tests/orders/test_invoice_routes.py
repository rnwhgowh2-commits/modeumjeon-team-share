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


@pytest.fixture
def store(monkeypatch):
    """적재분 흉내 — 업로드는 **엑셀의 주문번호로 여기서 직접 찾는다**
    (2026-07-30: 화면이 미리 불러 둔 목록에 기대지 않는다)."""
    from lemouton.markets import order_store
    have = {}

    def _load(**kw):
        want = set(kw.get("order_nos") or [])
        return [r for r in have.values() if r["오픈마켓주문번호"] in want]

    monkeypatch.setattr(order_store, "load", _load)

    def put(*order_nos):
        for o in order_nos:
            have[o] = {"오픈마켓주문번호": o, "판매처": "쿠팡", "송장입력": "송장미입력"}
    return put


# ── 업로드·매칭 ──────────────────────────────────────────────
class TestUpload:
    def test_upload_matches_by_open_market_order_no(self, client, store):
        store("A1", "A2")
        data = {
            "file": (_xlsx([["오픈마켓주문번호", "택배사", "운송장번호"],
                            ["A1", "로젠택배", "111"],
                            ["NOPE", "로젠택배", "999"]]), "송장.xlsx"),
        }
        r = client.post("/orders/invoice/upload", data=data,
                        content_type="multipart/form-data")
        assert r.status_code == 200
        body = r.get_json()
        assert body["ok"] is True
        assert body["matched"] == {"A1": {"invoice_no": "111", "courier": "로젠택배"}}
        assert body["unmatched"] == ["NOPE"]
        assert body["conflicts"] == []
        assert [r["오픈마켓주문번호"] for r in body["rows"]] == ["A1"]

    def test_upload_reports_conflict(self, client, store):
        store("A1")
        data = {
            "file": (_xlsx([["오픈마켓주문번호", "운송장번호"],
                            ["A1", "111"], ["A1", "222"]]), "송장.xlsx"),
        }
        body = client.post("/orders/invoice/upload", data=data,
                           content_type="multipart/form-data").get_json()
        assert body["conflicts"] == ["A1"]
        assert "A1" not in body["matched"]

    def test_화면이_준_목록에_기대지_않는다(self, client, store):
        """예전엔 화면이 보낸 order_nos 로만 맞췄다 — 기간을 좁게 잡으면 놓쳤다."""
        store("A1")
        body = client.post(
            "/orders/invoice/upload",
            data={"file": (_xlsx([["오픈마켓주문번호", "운송장번호"], ["A1", "111"]]), "x.xlsx"),
                  "order_nos": ""},          # 화면이 아무것도 안 줘도
            content_type="multipart/form-data").get_json()
        assert "A1" in body["matched"]       # 적재분에서 찾아낸다

    def test_upload_bad_columns_is_400(self, client):
        data = {"file": (_xlsx([["주문번호", "운송장번호"], ["A1", "1"]]), "x.xlsx")}
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
        """미배선 마켓은 조용히 성공하지 않고 실패로 집계.
        (옥션·G마켓은 2026-07-21 ESM ShippingInfo 배선으로 지원 목록에 들어갔다 —
         대신 위메프로 같은 원칙을 검증한다.)"""
        monkeypatch.setattr(om, "_live_enabled", lambda: True)
        monkeypatch.setattr(om, "_client_for", lambda market, alias: None)
        body = client.post("/orders/invoice/send",
                           json=_send_body(live=True, market="wemakeprice")).get_json()
        assert body["results"][0]["success"] is False
        assert "wemakeprice" in body["results"][0]["error"]
        assert body["sent"] == 0 and body["failed"] == 1

    def test_esm_전송은_클라이언트_없으면_정직하게_실패한다(self, client, monkeypatch):
        """옥션이 배선된 뒤에도 계정 클라이언트를 못 만들면 조용한 성공은 없다."""
        monkeypatch.setattr(om, "_live_enabled", lambda: True)
        monkeypatch.setattr(om, "_client_for", lambda market, alias: None)
        body = client.post("/orders/invoice/send",
                           json=_send_body(live=True, market="auction")).get_json()
        assert body["results"][0]["success"] is False
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
        """실계정으로 대조하지 못한 택배사는 조용히 보내지 않는다.

        [2026-07-30] CJ·한진은 대조가 끝나 이제 보낼 수 있다 — 아직 대조 못 한
        우체국택배로 대상을 바꾼다. 추측 금지 규칙 자체는 그대로다.
        """
        import shared.platforms.eleven11.shipping as el
        called = []
        monkeypatch.setattr(el, "send_tracking", lambda **k: called.append(1))
        monkeypatch.setattr(om, "_live_enabled", lambda: True)
        monkeypatch.setattr(om, "_client_for", lambda market, alias: None)

        body = _send_body(live=True, market="eleven11")
        body["rows"][0]["courier"] = "우체국택배"
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


def test_ESM_주문_raw_진단창구는_고객정보를_안_담는다(client, monkeypatch):
    """🔴 진단 창구가 개인정보를 흘리면 안 된다 — 담을 필드를 「고르기」로 했는지 본다.

    ESM 응답에는 ReceiverName·HpNo·Addr 같은 칸이 같이 온다. 「빼기」 방식이면 새 칸이
    생길 때마다 샌다. 가짜 응답에 고객정보를 섞어 두고 응답에 안 나오는지 확인한다.
    """
    import datetime as _d
    from shared.platforms.esm import orders as _eo

    fake = [{
        "OrderNo": "A1", "GoodsName": "상품", "SalePrice": "50000.0000",
        "ContrAmount": 1, "OptSelPrice": "0", "OptAddPrice": "0",
        "ShippingFee": "0", "OrderAmount": "48000.0000", "AcntMoney": "47000.0000",
        "OrderStatus": "3",
        # 아래는 절대 응답에 나오면 안 되는 칸들
        "ReceiverName": "홍길동", "HpNo": "010-1234-5678", "Addr1": "서울시 어딘가",
        "BuyerName": "김구매",
    }]
    monkeypatch.setattr(_eo, "iter_orders", lambda *a, **k: iter(fake))
    import webapp.routes.orders as _r
    monkeypatch.setattr(_r, "_client_for_diag", lambda *a, **k: object())

    j = client.get("/orders/diag/esm-order-raw?market=auction&days=3").get_json()
    assert j["ok"] is True and j["조회건수"] == 1
    본문 = str(j)
    for 샘 in ("홍길동", "010-1234-5678", "서울시 어딘가", "김구매"):
        assert 샘 not in 본문, f"진단 응답에 고객정보가 샜다: {샘}"
    행 = j["행"][0]
    # 옥션 유도식이 값으로 나오는지 — 50,000 − 48,000 = 사이트할인 2,000,
    #   판매자부담 = 0 + 48,000 + 0 − 47,000 = 1,000
    assert 행["_사이트할인"] == 2000 and 행["_판매자부담_추정"] == 1000, 행


def test_ESM_주문_raw_는_주문번호_조회도_되고_실패사유를_보여준다(client, monkeypatch):
    """주문번호 조회는 호출 제한이 없어 실측은 이 길로 한다 — 반환이 (행, 사유) 튜플이다."""
    from shared.platforms.esm import orders as _eo
    호출 = []

    def fake(market, no, *, client, **kw):
        호출.append(no)
        if no == "GOOD":
            return ({"OrderNo": "GOOD", "SalePrice": "50000.0000", "ContrAmount": 1,
                     "OptSelPrice": "0", "OptAddPrice": "0", "ShippingFee": "0",
                     "OrderAmount": "48000.0000", "AcntMoney": "47000.0000",
                     "ReceiverName": "홍길동"}, None)
        return (None, "orderStatus=0:0건")

    monkeypatch.setattr(_eo, "fetch_by_order_no", fake)
    import webapp.routes.orders as _r
    monkeypatch.setattr(_r, "_client_for_diag", lambda *a, **k: object())
    j = client.get("/orders/diag/esm-order-raw?market=auction&orders=GOOD,BAD").get_json()
    assert 호출 == ["GOOD", "BAD"], 호출
    assert "홍길동" not in str(j), "주문번호 경로에서 고객정보가 샜다"
    행 = {r["OrderNo"]: r for r in j["행"]}
    assert 행["GOOD"]["_판매자부담_추정"] == 1000, 행["GOOD"]
    assert 행["BAD"]["_실패사유"] == "orderStatus=0:0건", "못 찾은 사유를 삼켰다"
