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


# ── 워커 보호 (2026-07-20 라이브 502 재발 방지) ─────────────────
def test_동기실행이_오래_걸리면_워커를_죽이지_않고_504(client, monkeypatch):
    """🔴 이 라우트는 gunicorn 워커에서 돈다(--timeout 60). 오래 걸리는 창을 그냥
    돌리면 워커가 죽고 앱이 502 가 된다(실제로 냈다). 워커보다 먼저 우리가 끊는다."""
    import time
    monkeypatch.setattr(R, "SYNC_TIMEOUT_SEC", 0.2)
    monkeypatch.setattr("lemouton.markets.order_ingest.ingest_window",
                        lambda *a, **k: time.sleep(10))
    t0 = time.monotonic()
    r = client.post("/api/orders-ingest/run-sync",
                    json={"market": "coupang", "days": 29, "backfill": True})
    assert r.status_code == 504
    assert time.monotonic() - t0 < 5, "타임아웃 후에도 기다렸다 — 워커가 같이 죽는다"
    assert "웹에서 재기엔" in r.get_json()["error"]


def test_백필_플래그가_전달된다(client, monkeypatch):
    """백필 전용 경로(롯데온=정산 API)를 실측할 통로가 없으면 조용한 유실을 못 잡는다."""
    seen = {}
    monkeypatch.setattr("lemouton.markets.order_ingest.ingest_window",
                        lambda m, s, e, **k: seen.update(k) or {"fetched": 1})
    # fixture 의 supported_markets 는 coupang·smartstore 만 준다(lotteon 은 400).
    client.post("/api/orders-ingest/run-sync",
                json={"market": "coupang", "days": 7, "backfill": True})
    assert seen.get("backfill") is True


def test_back_파라미터로_과거_창을_지정한다(client, monkeypatch):
    """100% 채우려면 과거 창을 하나씩 정확히 지정해 재시도 제어해야 한다."""
    seen = {}
    def cap(m, since, until, **k):
        seen['since'], seen['until'] = since, until
        return {"fetched": 1}
    monkeypatch.setattr("lemouton.markets.order_ingest.ingest_window", cap)
    r = client.post("/api/orders-ingest/run-sync",
                    json={"market": "coupang", "days": 7, "back": 30})
    d = r.get_json()
    assert d["ok"] and d["back"] == 30
    # until = 30일 전, since = 37일 전 → 두 날짜 간격 7일
    assert (seen['until'] - seen['since']).days == 7


def test_back_음수는_0으로(client, monkeypatch):
    monkeypatch.setattr("lemouton.markets.order_ingest.ingest_window",
                        lambda *a, **k: {"fetched": 0})
    r = client.post("/api/orders-ingest/run-sync",
                    json={"market": "coupang", "days": 7, "back": -5})
    assert r.get_json()["back"] == 0
