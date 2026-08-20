# -*- coding: utf-8 -*-
"""롯데온 과거 209 백필 창 — 창 안만(스캔범위 폭발 방지)·계정 라우팅 계약."""
import datetime as dt

import flask
import pytest

import lemouton.markets.models_orders  # noqa: F401


def test_orders_to_now_false_does_not_extend_window(monkeypatch):
    """orders_to_now=False 면 209 조회 끝을 now 로 넓히지 않는다(창 안만)."""
    from lemouton.markets import order_export as oe

    captured = {}

    def fake_iter(since, until, client=None):
        captured["until"] = until
        return []

    monkeypatch.setattr("shared.platforms.lotteon.orders.iter_delivery_orders",
                        fake_iter)
    monkeypatch.setattr("shared.platforms.lotteon.claims.iter_all_claims",
                        lambda *a, **k: [], raising=False)
    until = dt.datetime(2026, 4, 20, tzinfo=oe.KST)
    since = until - dt.timedelta(days=5)
    oe.lotteon_order_rows(since, until, include_settlement=False,
                          claim_to_now=False, orders_to_now=False)
    assert captured["until"] == until          # now 확장 없음

    oe.lotteon_order_rows(since, until, include_settlement=False,
                          claim_to_now=False, orders_to_now=True)
    assert captured["until"] > until           # 기본값은 기존 동작(now 확장) 유지


@pytest.fixture
def client(monkeypatch):
    import webapp.routes.order_ingest as R
    app = flask.Flask(__name__)
    app.register_blueprint(R.bp)
    monkeypatch.setattr("lemouton.markets.order_export._active_accounts",
                        lambda m: [("LOTTEON_MAIN", "브랜드위시(롯데온)"),
                                   ("LOTTEON_2", "브랜드박스(롯데온)")])
    calls = []
    monkeypatch.setattr(
        "lemouton.markets.order_ingest.ingest_lotteon_orders_window",
        lambda since, until, prefix=None, alias=None:
            calls.append((prefix, alias, since, until)) or
            {"fetched": 3, "orders_new": 1, "orders_updated": 2,
             "claims_new": 0, "claims_updated": 0, "skipped_no_uid": 0})
    return app.test_client(), calls


def test_route_runs_one_account_one_window(client):
    c, calls = client
    j = c.post("/api/orders-ingest/lotteon-orders-window",
               json={"back": 30, "days": 5, "account_index": 1}).get_json()
    assert j["ok"] and j["account"] == "브랜드박스(롯데온)" and j["fetched"] == 3
    assert len(calls) == 1 and calls[0][0] == "LOTTEON_2"
    assert (calls[0][3] - calls[0][2]).days == 5


def test_route_days_capped_at_7_and_done_accounts(client):
    c, calls = client
    j = c.post("/api/orders-ingest/lotteon-orders-window",
               json={"days": 30, "account_index": 0}).get_json()
    assert (calls[0][3] - calls[0][2]).days == 7      # 상한 7일(209=1일창 순회)
    j2 = c.post("/api/orders-ingest/lotteon-orders-window",
                json={"account_index": 9}).get_json()
    assert j2["ok"] and j2["done_accounts"] is True   # 계정 소진 신호
