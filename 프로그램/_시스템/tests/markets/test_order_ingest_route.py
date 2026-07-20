"""백필 라우트 — 동시 실행 금지와 입력 검증.

백필은 마켓 API 를 1년치 기준 약 1,760회 두드린다. 두 번 겹쳐 돌면 rate limit 에
걸려 둘 다 실패한다. 그래서 '이미 돌고 있으면 거절'이 핵심 계약이다.
"""
from __future__ import annotations

import flask
import pytest

import webapp.routes.order_ingest as R


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr("lemouton.markets.order_export.supported_markets",
                        lambda: ["coupang", "smartstore"])
    R._state.update({"running": False, "done": 0, "total": 0, "results": [], "error": ""})
    app = flask.Flask(__name__)
    app.register_blueprint(R.bp)
    return app.test_client()


def test_규모를_미리_알려준다(client):
    r = client.get("/api/orders-ingest/estimate?days=365")
    d = r.get_json()
    assert d["ok"] and d["total_windows"] > 0
    assert d["per_market"]["smartstore"] == 365      # 1일 창


def test_이미_돌고_있으면_409로_거절한다(client):
    """두 번 겹쳐 돌면 rate limit 으로 둘 다 죽는다."""
    R._state["running"] = True
    r = client.post("/api/orders-ingest/backfill", json={"days": 365})
    assert r.status_code == 409
    assert "이미" in r.get_json()["error"]


def test_모르는_마켓은_400(client):
    r = client.post("/api/orders-ingest/backfill", json={"markets": ["shopmine"]})
    assert r.status_code == 400
    assert "shopmine" in r.get_json()["error"]


def test_days가_숫자가_아니면_400(client):
    r = client.post("/api/orders-ingest/backfill", json={"days": "일년"})
    assert r.status_code == 400


def test_백필을_시작하면_상태가_running(client, monkeypatch):
    import threading
    gate = threading.Event()
    monkeypatch.setattr("lemouton.markets.order_ingest.backfill",
                        lambda *a, **k: gate.wait(5) or [])
    r = client.post("/api/orders-ingest/backfill", json={"days": 30})
    assert r.status_code == 200 and r.get_json()["started"] is True
    assert client.get("/api/orders-ingest/status").get_json()["running"] is True
    gate.set()


def test_백필_실패는_상태에_남는다(client, monkeypatch):
    """조용히 끝난 것처럼 보이면 구멍이 난 걸 아무도 모른다."""
    import time
    monkeypatch.setattr("lemouton.markets.order_ingest.backfill",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    client.post("/api/orders-ingest/backfill", json={"days": 30})
    for _ in range(50):
        st = client.get("/api/orders-ingest/status").get_json()
        if not st["running"]:
            break
        time.sleep(0.05)
    assert "boom" in st["error"] and st["finished_at"]


def test_현황을_돌려준다(client, monkeypatch):
    monkeypatch.setattr("lemouton.markets.order_store.coverage",
                        lambda: [{"market": "coupang", "rows": 5,
                                  "oldest": "2026-01-01", "newest": "2026-07-01"}])
    d = client.get("/api/orders-ingest/coverage").get_json()
    assert d["ok"] and d["coverage"][0]["rows"] == 5
