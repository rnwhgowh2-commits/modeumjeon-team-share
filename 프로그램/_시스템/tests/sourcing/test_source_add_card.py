import json

import pytest

from lemouton.sourcing import crawl_guide as cg
from shared.db import SessionLocal
from lemouton.sourcing.models_pricing import SourceRegistry


# ─────────────────────────────────────────────────────────────────
#  Task 2 — 신규 소싱처 생성 API  /sourcing-guide/api/add-source
# ─────────────────────────────────────────────────────────────────

@pytest.fixture
def client(monkeypatch):
    """sourcing_guide 블루프린트만 띄운 테스트 클라이언트. ENVIRONMENT=test 로 admin 게이트 우회.
    로컬 SQLite 에 테이블이 없는 워크트리 환경을 위해 Base.metadata.create_all() 선행."""
    monkeypatch.setenv("ENVIRONMENT", "test")
    # 모든 모델을 먼저 등록해야 create_all() 이 테이블을 생성한다
    for _m in (
        "lemouton.sourcing.models",
        "lemouton.sourcing.models_pricing",
        "lemouton.sources.models",
        "lemouton.templates.models",
        "lemouton.inventory.models",
        "lemouton.mapping.models",
        "webapp.icon_store_model",
    ):
        try:
            __import__(_m)
        except ImportError:
            pass
    from shared.db import Base, engine
    Base.metadata.create_all(engine)

    from flask import Flask
    from webapp.routes import sourcing_guide as sg
    app = Flask(__name__)
    app.register_blueprint(sg.bp)
    app.config.update(TESTING=True)
    return app.test_client()


def _cleanup(name):
    s = SessionLocal()
    try:
        for r in s.query(SourceRegistry).filter_by(name=name).all():
            s.delete(r)
        s.commit()
    finally:
        s.close()


def test_add_source_creates_registry_and_urls(client):
    _cleanup("테스트29")
    resp = client.post("/sourcing-guide/api/add-source", json={
        "name": "테스트29",
        "urls": ["https://example.com/p/1", "https://example.com/p/2"],
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    s = SessionLocal()
    try:
        row = s.query(SourceRegistry).filter_by(name="테스트29").first()
        assert row is not None
        guide = json.loads(row.crawl_guide)
        assert [u["url"] for u in guide["sample_urls"]] == \
            ["https://example.com/p/1", "https://example.com/p/2"]
        assert guide["sample_urls"][0]["is_lead"] is True
    finally:
        s.close()
    _cleanup("테스트29")


def test_add_source_rejects_empty_name(client):
    resp = client.post("/sourcing-guide/api/add-source", json={"name": "", "urls": []})
    assert resp.status_code == 400


# ─────────────────────────────────────────────────────────────────
#  Task 1 — update_requested 필드 검증 (기존 테스트)
# ─────────────────────────────────────────────────────────────────

def test_skeleton_has_update_requested_none():
    sk = cg.empty_skeleton()
    assert sk["update_requested"] is None


def test_validate_keeps_update_requested():
    g = cg.empty_skeleton()
    g["update_requested"] = {"at": "2026-06-29T00:00:00+00:00", "note": "재고 둔갑"}
    out = cg.validate_guide(g)
    assert out["update_requested"]["note"] == "재고 둔갑"
    assert out["update_requested"]["at"] == "2026-06-29T00:00:00+00:00"


def test_validate_rejects_bad_update_requested():
    g = cg.empty_skeleton()
    g["update_requested"] = "nope"          # dict 아님 → None 으로 정제
    out = cg.validate_guide(g)
    assert out["update_requested"] is None


def test_validate_caps_note_at_200():
    g = cg.empty_skeleton()
    g["update_requested"] = {"at": "2026-06-29T00:00:00+00:00", "note": "x" * 250}
    out = cg.validate_guide(g)
    assert len(out["update_requested"]["note"]) == 200


def test_validate_update_requested_missing_at_becomes_none():
    g = cg.empty_skeleton()
    g["update_requested"] = {"note": "사유만 있음"}
    out = cg.validate_guide(g)
    assert out["update_requested"]["at"] is None
    assert out["update_requested"]["note"] == "사유만 있음"


def test_add_source_invalid_url_returns_400(client):
    _cleanup("테스트나쁜URL")
    resp = client.post("/sourcing-guide/api/add-source", json={
        "name": "테스트나쁜URL", "urls": ["not-a-real-url"]})
    assert resp.status_code == 400
    # 잘못된 URL 이면 행이 커밋되지 않아야 함(롤백)
    s = SessionLocal()
    try:
        assert s.query(SourceRegistry).filter_by(name="테스트나쁜URL").first() is None
    finally:
        s.close()
    _cleanup("테스트나쁜URL")


def test_add_source_empty_urls_ok(client):
    _cleanup("테스트빈URL")
    resp = client.post("/sourcing-guide/api/add-source", json={
        "name": "테스트빈URL", "urls": []})
    assert resp.status_code == 200
    assert resp.get_json()["url_count"] == 0
    _cleanup("테스트빈URL")


# ─────────────────────────────────────────────────────────────────
#  Task 3 — URL 편집 + 기존 업데이트 요청 API
# ─────────────────────────────────────────────────────────────────

def _make_source(name, urls):
    s = SessionLocal()
    try:
        src = SourceRegistry(name=name, sort_order=999)
        s.add(src); s.flush()
        g = cg.empty_skeleton()
        g["sample_urls"] = [{"url": u, "is_lead": i == 0} for i, u in enumerate(urls)]
        src.crawl_guide = cg.dumps(g)
        s.commit()
        return src.id
    finally:
        s.close()


def test_save_urls_replaces_list(client):
    _cleanup("테스트URL")
    sid = _make_source("테스트URL", ["https://a.com/1"])
    resp = client.post(f"/sourcing-guide/api/{sid}/save-urls", json={
        "urls": ["https://a.com/2", "https://a.com/3"]})
    assert resp.status_code == 200
    s = SessionLocal()
    try:
        g = json.loads(s.query(SourceRegistry).get(sid).crawl_guide)
        assert [u["url"] for u in g["sample_urls"]] == ["https://a.com/2", "https://a.com/3"]
    finally:
        s.close()
    _cleanup("테스트URL")


def test_request_update_sets_flag(client):
    _cleanup("테스트UPD")
    sid = _make_source("테스트UPD", ["https://a.com/1"])
    resp = client.post(f"/sourcing-guide/api/{sid}/request-update", json={"note": "재고 둔갑"})
    assert resp.status_code == 200
    s = SessionLocal()
    try:
        g = json.loads(s.query(SourceRegistry).get(sid).crawl_guide)
        assert g["update_requested"]["note"] == "재고 둔갑"
    finally:
        s.close()
    _cleanup("테스트UPD")


# ─────────────────────────────────────────────────────────────────
#  Task 4 — 분석 대기 큐 식별 헬퍼 + API  /sourcing-guide/api/queue
# ─────────────────────────────────────────────────────────────────

def test_queue_lists_pending(client):
    _cleanup("테스트큐")
    sid = _make_source("테스트큐", ["https://a.com/1"])   # 카드 빈 + URL 있음 = 신규 대기
    resp = client.get("/sourcing-guide/api/queue")
    assert resp.status_code == 200
    items = resp.get_json()["items"]
    hit = [it for it in items if it["id"] == sid]
    assert hit and hit[0]["kind"] == "new"
    _cleanup("테스트큐")
