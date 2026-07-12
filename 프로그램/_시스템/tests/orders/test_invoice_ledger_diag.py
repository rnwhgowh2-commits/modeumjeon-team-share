# -*- coding: utf-8 -*-
"""[TEST] 송장 원장 진단 라우트 — 읽기 전용(저장이 실제로 되는지 육안 확인용).

마켓별 저장 건수 + 최근 저장 시각. `?order_no=` 로 특정 주문의 저장된 송장 조회.
"""
import pytest
from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from webapp.routes import orders as om


@pytest.fixture
def client():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(om.bp)
    return app.test_client()


@pytest.fixture
def ledger_db(monkeypatch):
    """원장 함수가 쓰는 SessionLocal 을 이 테스트 전용 인메모리로 교체."""
    from lemouton.sourcing.models_v2 import InvoiceLedger
    import lemouton.markets.invoice_ledger as led
    eng = create_engine("sqlite:///:memory:")
    InvoiceLedger.__table__.create(eng)
    Factory = sessionmaker(bind=eng, future=True)
    monkeypatch.setattr(led, "SessionLocal", Factory, raising=False)
    # _open_session 은 지연 import 하므로 shared.db.SessionLocal 도 교체
    import shared.db as sdb
    monkeypatch.setattr(sdb, "SessionLocal", Factory)
    return Factory


def _seed(factory, items):
    from lemouton.sourcing.models_v2 import InvoiceLedger
    s = factory()
    for market, order_no, inv in items:
        s.add(InvoiceLedger(market=market, order_no=order_no, invoice_no=inv))
    s.commit(); s.close()


def test_counts_per_market(client, ledger_db):
    _seed(ledger_db, [("11번가", "O1", "111"), ("11번가", "O2", "222"),
                      ("쿠팡", "O3", "333")])
    body = client.get("/orders/diag/invoice-ledger").get_json()
    assert body["ok"] is True
    assert body["counts"] == {"11번가": 2, "쿠팡": 1}
    assert body["total"] == 3


def test_lookup_one_order(client, ledger_db):
    _seed(ledger_db, [("11번가", "O1", "9988776655")])
    body = client.get("/orders/diag/invoice-ledger?order_no=O1").get_json()
    assert body["found"] is True
    assert body["invoice_no"] == "9988776655" and body["market"] == "11번가"


def test_lookup_miss_is_honest(client, ledger_db):
    _seed(ledger_db, [("11번가", "O1", "111")])
    body = client.get("/orders/diag/invoice-ledger?order_no=GHOST").get_json()
    assert body["found"] is False


def test_empty_ledger_reports_zero_not_error(client, ledger_db):
    body = client.get("/orders/diag/invoice-ledger").get_json()
    assert body["ok"] is True and body["total"] == 0
