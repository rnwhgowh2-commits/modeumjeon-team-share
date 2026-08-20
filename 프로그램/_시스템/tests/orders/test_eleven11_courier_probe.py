# -*- coding: utf-8 -*-
"""[TEST] 11번가 택배사 코드 확인 도구 — 읽기 전용.

11번가 발송처리에 쓸 택배사 코드(dlvEtprsCd)는 출처마다 값이 달라 추측할 수 없다.
정답은 **사장님이 실제로 발송한 11번가 주문**이 갖고 있다(배송중·배송완료 목록의 dlvEtprsCd).
이 라우트는 그 코드만 세어서 돌려준다 — 주문번호·고객정보는 내보내지 않는다.

송장번호를 알면(셀러오피스 화면에 택배사가 같이 보인다) `?invoice=` 로 곧장 코드를 물을 수 있다.
"""
import pytest
from flask import Flask

from webapp.routes import orders as om


@pytest.fixture
def client():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(om.bp)
    return app.test_client()


@pytest.fixture
def one_account(monkeypatch):
    monkeypatch.setattr(om._oe, "_active_accounts", lambda m: [("ELEVEN11_MAIN", "본계정")])
    monkeypatch.setattr(om, "_client_for", lambda market, alias: object())


def _stub(monkeypatch, shipping=(), delivered=()):
    import shared.platforms.eleven11.orders as eo
    monkeypatch.setattr(eo, "iter_shipping", lambda *a, **k: iter(list(shipping)))
    monkeypatch.setattr(eo, "iter_delivered", lambda *a, **k: iter(list(delivered)))


# ── 코드 집계 ────────────────────────────────────────────────
def test_counts_courier_codes_from_shipped_orders(client, monkeypatch, one_account):
    _stub(monkeypatch, shipping=[
        {"ordNo": "1", "dlvEtprsCd": "00002", "invcNo": "111"},
        {"ordNo": "2", "dlvEtprsCd": "00002", "invcNo": "222"},
        {"ordNo": "3", "dlvEtprsCd": "00034", "invcNo": "333"},
    ])
    body = client.get("/orders/diag/eleven11-couriers").get_json()
    assert body["ok"] is True
    assert body["codes"] == {"00002": 2, "00034": 1}


def test_reports_send_dates_per_code(client, monkeypatch, one_account):
    """코드가 여러 개면 건수만으론 어느 게 로젠인지 못 가린다 → 발송일을 함께 보여준다."""
    _stub(monkeypatch, shipping=[
        {"dlvEtprsCd": "00002", "sndEndDt": "2026-07-08 11:20:00"},
        {"dlvEtprsCd": "00011", "sndEndDt": "2026-07-03 09:00:00"},
    ])
    body = client.get("/orders/diag/eleven11-couriers").get_json()
    assert body["dates"] == {"00002": ["2026-07-08"], "00011": ["2026-07-03"]}


def test_does_not_leak_order_or_customer_data(client, monkeypatch, one_account):
    """코드·건수만. 주문번호·고객정보가 응답에 섞이면 안 된다."""
    _stub(monkeypatch, shipping=[
        {"ordNo": "202607100001", "dlvEtprsCd": "00002", "invcNo": "9988776655",
         "rcvrNm": "홍길동"},
    ])
    raw = client.get("/orders/diag/eleven11-couriers").get_data(as_text=True)
    assert "202607100001" not in raw and "홍길동" not in raw


def test_empty_result_is_reported_not_faked(client, monkeypatch, one_account):
    """발송 이력이 없으면 빈 결과로 정직하게 알린다(임의 코드 채우기 금지)."""
    _stub(monkeypatch)
    body = client.get("/orders/diag/eleven11-couriers").get_json()
    assert body["ok"] is True and body["codes"] == {}
    assert "없" in body["note"]


def test_no_key_is_error_not_empty(client, monkeypatch):
    """키 미등록을 '코드 없음'으로 뭉개지 않는다."""
    monkeypatch.setattr(om._oe, "_active_accounts", lambda m: [])
    monkeypatch.setattr(om, "_client_for", lambda market, alias: None)
    r = client.get("/orders/diag/eleven11-couriers")
    assert r.status_code == 400
    assert "키" in r.get_json()["error"]


# ── 계정 ────────────────────────────────────────────────────
def test_reports_which_accounts_were_read(client, monkeypatch):
    """11번가 계정이 여러 개면 전부 훑고, 어느 계정에서 나온 코드인지 알려준다."""
    monkeypatch.setattr(om._oe, "_active_accounts",
                        lambda m: [("ELEVEN11_MAIN", "본계정"), ("ELEVEN11_2", "second")])
    monkeypatch.setattr(om, "_client_for", lambda market, alias: object())
    _stub(monkeypatch, shipping=[{"dlvEtprsCd": "00002", "invcNo": "1"}])

    body = client.get("/orders/diag/eleven11-couriers").get_json()
    aliases = [a["alias"] for a in body["accounts"]]
    assert aliases == ["본계정", "second"]
    assert body["accounts"][0]["codes"] == {"00002": 1}


# ── 송장번호로 직접 조회 ─────────────────────────────────────
def test_lookup_code_by_invoice_number(client, monkeypatch, one_account):
    """셀러오피스 화면에서 택배사·송장번호를 같이 볼 수 있다 → 송장번호로 코드를 곧장 묻는다."""
    _stub(monkeypatch,
          shipping=[{"dlvEtprsCd": "00011", "invcNo": "317651308380"}],
          delivered=[{"dlvEtprsCd": "00002", "invcNo": "92816272404"}])

    body = client.get("/orders/diag/eleven11-couriers?invoice=92816272404").get_json()
    assert body["match"] == {"alias": "본계정", "code": "00002"}


def test_lookup_miss_is_null_not_guess(client, monkeypatch, one_account):
    _stub(monkeypatch, shipping=[{"dlvEtprsCd": "00011", "invcNo": "999"}])
    body = client.get("/orders/diag/eleven11-couriers?invoice=92816272404").get_json()
    assert body["match"] is None
    assert "찾지" in body["note"]
