# -*- coding: utf-8 -*-
"""[TEST] GET /api/crawl/due-bundles — 확장 폴링용 번들 코드(읽기 전용)."""
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


def _seed(enabled: bool):
    """실행/정지 + 번들(코드+URL) + 그 URL 로 due 한 SourceProduct 1건 시드."""
    from shared.db import SessionLocal
    from lemouton.pricing.settings import get_or_init
    from lemouton.sourcing.models import Model, BundleSourceUrl
    from lemouton.sources.models import SourceProduct
    from lemouton.sources.service import normalize_url
    s = SessionLocal()
    try:
        gs = get_or_init(s)
        gs.crawl_auto_enabled = enabled
        gs.crawl_interval_hours = 6
        gs.crawl_interval_minutes = 0
        code = "DUEB001"
        url = "https://example.test/due-bundle-seed"
        if not s.query(Model).filter_by(model_code=code).first():
            s.add(Model(model_code=code, model_name_raw=code))
            s.flush()
            s.add(BundleSourceUrl(model_code=code, source_key="musinsa",
                                  url=url, url_type="단품"))
        if not s.query(SourceProduct).filter_by(url=normalize_url(url)).first():
            s.add(SourceProduct(site="musinsa", url=normalize_url(url),
                                crawl_weight=1, no_change_streak=0,
                                last_fetched_at=None))  # 미크롤=반드시 due
        s.commit()
    finally:
        s.close()


def test_enabled_returns_codes(client):
    _seed(enabled=True)
    r = client.get("/api/crawl/due-bundles")
    assert r.status_code == 200
    d = r.get_json()
    assert d["enabled"] is True
    assert d["count"] >= 1
    assert "DUEB001" in d["codes"]


def test_disabled_returns_empty(client):
    _seed(enabled=False)
    r = client.get("/api/crawl/due-bundles")
    assert r.status_code == 200
    d = r.get_json()
    assert d["enabled"] is False
    assert d["codes"] == []
