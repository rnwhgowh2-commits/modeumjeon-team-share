# -*- coding: utf-8 -*-
"""[TEST] POST /api/sources/crawl-weight — URL 계수(1~5) 저장."""
import os

import pytest

os.environ.setdefault("ENVIRONMENT", "test")


@pytest.fixture
def client():
    for _m in (
        "lemouton.sourcing.models", "lemouton.sourcing.models_pricing",
        "lemouton.sources.models", "lemouton.templates.models",
        "lemouton.inventory.models", "lemouton.pricing.settings",
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


def _seed(url: str) -> int:
    """SessionLocal 로 SourceProduct 1건 시드하고 id 반환."""
    from shared.db import SessionLocal
    from lemouton.sources.models import SourceProduct
    s = SessionLocal()
    try:
        sp = s.query(SourceProduct).filter_by(url=url).first()
        if sp is None:
            sp = SourceProduct(site="musinsa", url=url, crawl_weight=1)
            s.add(sp)
            s.commit()
        return sp.id
    finally:
        s.close()


def test_set_weight_ok(client):
    spid = _seed("https://example.test/crawl-weight-ok")
    r = client.post("/api/sources/crawl-weight",
                    json={"source_product_id": spid, "weight": 4})
    assert r.status_code == 200
    d = r.get_json()
    assert d["ok"] is True and d["weight"] == 4


def test_weight_clamped(client):
    spid = _seed("https://example.test/crawl-weight-clamp")
    r = client.post("/api/sources/crawl-weight",
                    json={"source_product_id": spid, "weight": 9})
    assert r.status_code == 200
    assert r.get_json()["weight"] == 5


def test_missing_id_404(client):
    r = client.post("/api/sources/crawl-weight",
                    json={"source_product_id": 999999, "weight": 3})
    assert r.status_code == 404
    assert r.get_json()["ok"] is False
