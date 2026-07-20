"""주문 적재 라우트 — 웹은 **요청만** 남긴다.

라이브 장애 2건에서 나온 계약: 긴 백필을 gunicorn 워커에서 돌리면 워커가 점유돼
앱이 502 가 되고, 워커 재활용(`--timeout 60`·`--max-requests`) 때 작업이 통째로
죽는다. 그래서 이 라우트는 DB 에 요청을 적고 즉시 돌아와야 한다 — 여기서 마켓을
때리면 안 된다.
"""
from __future__ import annotations

import flask
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import webapp.routes.order_ingest as R
from lemouton.markets import backfill_runner as BR


@pytest.fixture
def client(monkeypatch):
    from shared.db import Base
    import lemouton.markets.models_orders  # noqa: F401
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng, tables=[
        Base.metadata.tables["market_order_lines"],
        Base.metadata.tables["market_claim_events"],
        Base.metadata.tables["order_ingest_runs"],
    ])
    Maker = sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(BR, "_session", Maker)
    monkeypatch.setattr(R, "_session", Maker)
    monkeypatch.setattr("lemouton.markets.order_export.supported_markets",
                        lambda: ["coupang", "smartstore"])
    app = flask.Flask(__name__)
    app.register_blueprint(R.bp)
    return app.test_client()


def test_규모를_미리_알려준다(client):
    d = client.get("/api/orders-ingest/estimate?days=365").get_json()
    assert d["ok"] and d["per_market"]["smartstore"] == 365      # 1일 창


# ── 웹은 요청만 남긴다 ──────────────────────────────────────────
def test_백필_요청은_202로_즉시_돌아온다(client, monkeypatch):
    """워커에서 긴 작업을 하면 앱이 502 가 된다 — 여기서 마켓을 때리면 안 된다."""
    hit = []
    monkeypatch.setattr(BR, "ingest_window", lambda *a, **k: hit.append(1))
    r = client.post("/api/orders-ingest/backfill", json={"days": 365})
    assert r.status_code == 202 and r.get_json()["requested"] is True
    assert hit == [], "요청 처리 중에 마켓을 조회했다"


def test_요청하면_상태에_남는다(client):
    client.post("/api/orders-ingest/backfill",
                json={"days": 30, "markets": ["coupang"]})
    st = client.get("/api/orders-ingest/status").get_json()
    assert st["requested"] is True and st["markets"] == "coupang" and st["total"] > 0


def test_처음_물어도_상태를_돌려준다(client):
    st = client.get("/api/orders-ingest/status").get_json()
    assert st["ok"] and st["requested"] is False and st["running"] is False


def test_이미_예약돼_있으면_409(client):
    client.post("/api/orders-ingest/backfill", json={"days": 30})
    r = client.post("/api/orders-ingest/backfill", json={"days": 30})
    assert r.status_code == 409 and "이미" in r.get_json()["error"]


def test_force면_다시_예약할_수_있다(client):
    client.post("/api/orders-ingest/backfill", json={"days": 30})
    assert client.post("/api/orders-ingest/backfill",
                       json={"days": 60, "force": True}).status_code == 202


def test_중단하면_요청이_사라진다(client):
    client.post("/api/orders-ingest/backfill", json={"days": 30})
    assert client.post("/api/orders-ingest/cancel").status_code == 200
    assert client.get("/api/orders-ingest/status").get_json()["requested"] is False


# ── 입력 검증 ─────────────────────────────────────────────────
def test_모르는_마켓은_400(client):
    r = client.post("/api/orders-ingest/backfill", json={"markets": ["shopmine"]})
    assert r.status_code == 400 and "shopmine" in r.get_json()["error"]


def test_days가_숫자가_아니면_400(client):
    assert client.post("/api/orders-ingest/backfill",
                       json={"days": "일년"}).status_code == 400


# ── 동기 실행(진단용) ──────────────────────────────────────────
def test_동기실행은_결과를_바로_돌려준다(client, monkeypatch):
    monkeypatch.setattr("lemouton.markets.order_ingest.ingest_window",
                        lambda m, s, e, **k: {"fetched": 3, "orders_new": 3})
    d = client.post("/api/orders-ingest/run-sync",
                    json={"market": "coupang", "days": 7}).get_json()
    assert d["ok"] and d["fetched"] == 3


def test_동기실행_실패는_사유를_숨기지_않는다(client, monkeypatch):
    monkeypatch.setattr("lemouton.markets.order_ingest.ingest_window",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    r = client.post("/api/orders-ingest/run-sync", json={"market": "coupang"})
    assert r.status_code == 500
    assert "boom" in r.get_json()["error"] and "Traceback" in r.get_json()["trace"]


def test_동기실행도_마켓을_검증한다(client):
    assert client.post("/api/orders-ingest/run-sync",
                       json={"market": "shopmine"}).status_code == 400


# ── 현황 ──────────────────────────────────────────────────────
def test_현황을_돌려준다(client, monkeypatch):
    monkeypatch.setattr("lemouton.markets.order_store.coverage",
                        lambda: [{"market": "coupang", "rows": 5,
                                  "oldest": "2026-01-01", "newest": "2026-07-01"}])
    d = client.get("/api/orders-ingest/coverage").get_json()
    assert d["ok"] and d["coverage"][0]["rows"] == 5
