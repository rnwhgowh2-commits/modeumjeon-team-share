# -*- coding: utf-8 -*-
"""[TEST] 11번가 택배사 코드 확인 도구 — 읽기 전용.

11번가 발송처리에 쓸 택배사 코드(dlvEtprsCd)는 출처마다 값이 달라 추측할 수 없다.
정답은 **사장님이 실제로 발송한 11번가 주문**이 갖고 있다(배송중 목록의 dlvEtprsCd).
이 라우트는 그 코드만 세어서 돌려준다 — 주문번호·송장번호·고객정보는 내보내지 않는다.
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


def test_counts_courier_codes_from_shipped_orders(client, monkeypatch):
    import shared.platforms.eleven11.orders as eo
    monkeypatch.setattr(om, "_client_for", lambda market, alias: object())
    monkeypatch.setattr(eo, "iter_shipping", lambda *a, **k: iter([
        {"ordNo": "1", "dlvEtprsCd": "00002", "invcNo": "111"},
        {"ordNo": "2", "dlvEtprsCd": "00002", "invcNo": "222"},
        {"ordNo": "3", "dlvEtprsCd": "00034", "invcNo": "333"},
    ]))

    body = client.get("/orders/diag/eleven11-couriers").get_json()
    assert body["ok"] is True
    assert body["codes"] == {"00002": 2, "00034": 1}


def test_reports_send_dates_per_code(client, monkeypatch):
    """코드가 여러 개면 건수만으론 어느 게 로젠인지 못 가린다 → 발송일을 함께 보여준다."""
    import shared.platforms.eleven11.orders as eo
    monkeypatch.setattr(om, "_client_for", lambda market, alias: object())
    monkeypatch.setattr(eo, "iter_shipping", lambda *a, **k: iter([
        {"dlvEtprsCd": "00002", "sndEndDt": "2026-07-08 11:20:00"},
        {"dlvEtprsCd": "00011", "sndEndDt": "2026-07-03 09:00:00"},
    ]))
    body = client.get("/orders/diag/eleven11-couriers").get_json()
    assert body["dates"] == {"00002": ["2026-07-08"], "00011": ["2026-07-03"]}


def test_does_not_leak_order_or_customer_data(client, monkeypatch):
    """코드·건수만. 송장번호·주문번호가 응답에 섞이면 안 된다."""
    import shared.platforms.eleven11.orders as eo
    monkeypatch.setattr(om, "_client_for", lambda market, alias: object())
    monkeypatch.setattr(eo, "iter_shipping", lambda *a, **k: iter([
        {"ordNo": "202607100001", "dlvEtprsCd": "00002", "invcNo": "9988776655",
         "rcvrNm": "홍길동"},
    ]))
    raw = client.get("/orders/diag/eleven11-couriers").get_data(as_text=True)
    assert "9988776655" not in raw and "202607100001" not in raw and "홍길동" not in raw


def test_empty_result_is_reported_not_faked(client, monkeypatch):
    """발송 이력이 없으면 빈 결과로 정직하게 알린다(임의 코드 채우기 금지)."""
    import shared.platforms.eleven11.orders as eo
    monkeypatch.setattr(om, "_client_for", lambda market, alias: object())
    monkeypatch.setattr(eo, "iter_shipping", lambda *a, **k: iter([]))

    body = client.get("/orders/diag/eleven11-couriers").get_json()
    assert body["ok"] is True and body["codes"] == {}
    assert "없" in body["note"]


def test_no_key_is_error_not_empty(client, monkeypatch):
    """키 미등록을 '코드 없음'으로 뭉개지 않는다."""
    monkeypatch.setattr(om, "_client_for", lambda market, alias: None)
    r = client.get("/orders/diag/eleven11-couriers")
    assert r.status_code == 400
    assert "키" in r.get_json()["error"]
