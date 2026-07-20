"""백필 라우트 — 동시 실행 금지, 입력 검증, 상태 공유.

두 가지 계약:
  ① 백필은 겹쳐 돌면 안 된다(1년치 ≈ 800회 호출 → rate limit 으로 둘 다 죽는다)
  ② 상태는 **DB** 에 있어야 한다. 앱이 멀티워커라 모듈 전역에 두면 시작한 워커와
     상태를 묻는 워커가 달라 진행률이 0/0 으로 보인다(2026-07-20 라이브 실측).
"""
from __future__ import annotations

import flask
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import webapp.routes.order_ingest as R


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
    monkeypatch.setattr(R, "_session", Maker)
    monkeypatch.setattr("lemouton.markets.order_export.supported_markets",
                        lambda: ["coupang", "smartstore"])
    # 백필은 기본 잠금이라 테스트에선 열어둔다(잠금 자체는 전용 테스트에서 검증).
    monkeypatch.setenv("ORDER_BACKFILL_ARMED", "1")
    app = flask.Flask(__name__)
    app.register_blueprint(R.bp)
    return app.test_client()


def test_규모를_미리_알려준다(client):
    d = client.get("/api/orders-ingest/estimate?days=365").get_json()
    assert d["ok"] and d["per_market"]["smartstore"] == 365      # 1일 창


# ── 상태는 DB 에 있어야 한다 ────────────────────────────────────
def test_상태가_DB에_남아_다른_요청에서도_보인다(client, monkeypatch):
    """모듈 전역이면 워커가 다를 때 0/0 으로 보인다 — 그 회귀를 막는다."""
    import threading
    gate = threading.Event()
    monkeypatch.setattr("lemouton.markets.order_ingest.backfill",
                        lambda *a, **k: gate.wait(5) or [])
    client.post("/api/orders-ingest/backfill", json={"days": 30, "markets": ["coupang"]})
    st = client.get("/api/orders-ingest/status").get_json()
    assert st["running"] is True and st["total"] > 0 and st["markets"] == "coupang"
    gate.set()


def test_처음_물어도_상태행이_생긴다(client):
    st = client.get("/api/orders-ingest/status").get_json()
    assert st["ok"] and st["running"] is False


# ── 동시 실행 금지 ─────────────────────────────────────────────
def test_이미_돌고_있으면_409(client, monkeypatch):
    import threading
    gate = threading.Event()
    monkeypatch.setattr("lemouton.markets.order_ingest.backfill",
                        lambda *a, **k: gate.wait(5) or [])
    client.post("/api/orders-ingest/backfill", json={"days": 30})
    r = client.post("/api/orders-ingest/backfill", json={"days": 30})
    assert r.status_code == 409 and "이미" in r.get_json()["error"]
    gate.set()


def test_force로_막힌_상태를_풀_수_있다(client, monkeypatch):
    """앱이 죽어 running 이 1로 남으면 영영 못 돌린다 — 탈출구가 필요하다."""
    monkeypatch.setattr("lemouton.markets.order_ingest.backfill", lambda *a, **k: [])
    s = R._session()
    R._get_run(s).running = "1"
    s.commit()
    s.close()
    assert client.post("/api/orders-ingest/backfill",
                       json={"days": 30, "force": True}).status_code == 200


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
                        lambda m, s, e, session=None: {"fetched": 3, "orders_new": 3})
    d = client.post("/api/orders-ingest/run-sync",
                    json={"market": "coupang", "days": 7}).get_json()
    assert d["ok"] and d["fetched"] == 3 and d["orders_new"] == 3


def test_동기실행_실패는_사유를_숨기지_않는다(client, monkeypatch):
    """배경 스레드는 왜 실패했는지 보기 어렵다 — 진단 경로는 사유를 그대로 준다."""
    monkeypatch.setattr("lemouton.markets.order_ingest.ingest_window",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    r = client.post("/api/orders-ingest/run-sync", json={"market": "coupang"})
    assert r.status_code == 500
    d = r.get_json()
    assert "boom" in d["error"] and "Traceback" in d["trace"]


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


# ── 백필 잠금 (2026-07-20 라이브 502 재발 방지) ──────────────────
def test_백필은_기본_잠겨_있다(client, monkeypatch):
    """이 경로가 웹 프로세스 자원을 먹어 앱이 502 로 죽은 적이 있다.
    사람이 의도적으로 열 때만 돌아야 한다."""
    monkeypatch.delenv("ORDER_BACKFILL_ARMED", raising=False)
    r = client.post("/api/orders-ingest/backfill", json={"days": 365})
    assert r.status_code == 423 and "잠겨" in r.get_json()["error"]


def test_env를_켜면_백필이_열린다(client, monkeypatch):
    monkeypatch.setenv("ORDER_BACKFILL_ARMED", "1")
    monkeypatch.setattr("lemouton.markets.order_ingest.backfill", lambda *a, **k: [])
    assert client.post("/api/orders-ingest/backfill",
                       json={"days": 30, "markets": ["coupang"]}).status_code == 200


def test_증분_수집은_잠금과_무관하다(client, monkeypatch):
    """평소 신선도를 지키는 건 증분이다 — 그건 막으면 안 된다."""
    monkeypatch.delenv("ORDER_BACKFILL_ARMED", raising=False)
    monkeypatch.setattr("lemouton.markets.order_ingest.ingest_window",
                        lambda *a, **k: {"fetched": 1, "orders_new": 1})
    assert client.post("/api/orders-ingest/run-sync",
                       json={"market": "coupang", "days": 7}).status_code == 200
