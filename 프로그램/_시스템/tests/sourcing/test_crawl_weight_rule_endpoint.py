# -*- coding: utf-8 -*-
"""[TEST] GET /api/crawl/weight-rules · POST /api/crawl/weight-rule — 계층 계수 규칙."""
import os

import pytest

os.environ.setdefault("ENVIRONMENT", "test")


@pytest.fixture
def client():
    for _m in (
        "lemouton.sourcing.models", "lemouton.sourcing.models_pricing",
        "lemouton.sources.models", "lemouton.templates.models",
        "lemouton.inventory.models", "lemouton.pricing.settings",
        "lemouton.multitenancy.models",
    ):
        try:
            __import__(_m)
        except ImportError:
            pass
    from shared.db import Base, engine
    Base.metadata.create_all(engine)

    from flask import Flask
    from webapp.routes.api import bp
    app = Flask(__name__)
    app.register_blueprint(bp)
    app.config.update(TESTING=True)
    return app.test_client()


def test_post_set_rule_ok(client):
    r = client.post("/api/crawl/weight-rule",
                    json={"scope_type": "source", "scope_key": "musinsa", "weight": 3})
    assert r.status_code == 200
    d = r.get_json()
    assert d["ok"] is True and d["weight"] == 3

    from shared.db import SessionLocal
    from lemouton.sources.crawl_schedule import list_weight_rules
    s = SessionLocal()
    try:
        assert list_weight_rules(s)["source"]["musinsa"] == 3
    finally:
        s.close()


def test_post_no_weight_clears_rule(client):
    client.post("/api/crawl/weight-rule",
                json={"scope_type": "brand", "scope_key": "해제나이키", "weight": 4})
    r = client.post("/api/crawl/weight-rule",
                    json={"scope_type": "brand", "scope_key": "해제나이키"})  # weight 생략 → 해제
    assert r.status_code == 200
    assert r.get_json()["ok"] is True

    from shared.db import SessionLocal
    from lemouton.sources.crawl_schedule import list_weight_rules
    s = SessionLocal()
    try:
        assert "해제나이키" not in list_weight_rules(s)["brand"]
    finally:
        s.close()


def test_post_bad_scope_type_400(client):
    r = client.post("/api/crawl/weight-rule",
                    json={"scope_type": "지역", "scope_key": "x", "weight": 3})
    assert r.status_code == 400
    assert r.get_json()["ok"] is False


def test_get_weight_rules_dict(client):
    client.post("/api/crawl/weight-rule",
                json={"scope_type": "source", "scope_key": "조회ssf", "weight": 5})
    r = client.get("/api/crawl/weight-rules")
    assert r.status_code == 200
    d = r.get_json()
    assert d["source"]["조회ssf"] == 5
