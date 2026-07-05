# -*- coding: utf-8 -*-
"""[TEST] GET /api/crawl/failures — 크롤 실패 유형별(읽기 전용)."""
import os

import pytest

os.environ.setdefault("ENVIRONMENT", "test")


@pytest.fixture
def client():
    for _m in (
        "lemouton.sourcing.models", "lemouton.sourcing.models_pricing",
        "lemouton.sources.models", "lemouton.templates.models",
        "lemouton.inventory.models",
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


def _seed_failure():
    from shared.db import SessionLocal
    from lemouton.sources.models import SourceProduct
    s = SessionLocal()
    try:
        url = "https://example.test/failures-seed-403"
        if not s.query(SourceProduct).filter_by(url=url).first():
            s.add(SourceProduct(site="musinsa", url=url,
                                last_status="error", last_error_msg="403 차단"))
        s.commit()
    finally:
        s.close()


def test_failures_grouped_by_type(client):
    _seed_failure()
    r = client.get("/api/crawl/failures")
    assert r.status_code == 200
    d = r.get_json()
    block = [g for g in d["groups"] if g["type"] == "block"]
    assert block and block[0]["label"] == "차단"
    assert any(it["url"].endswith("failures-seed-403") for it in block[0]["items"])
