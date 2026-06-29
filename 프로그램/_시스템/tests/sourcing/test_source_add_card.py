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
