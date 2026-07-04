# -*- coding: utf-8 -*-
"""[TEST] GET /api/crawl/queue — 로컬 크롤러가 폴링하는 due 목록(읽기 전용)."""
import os
from datetime import datetime, timezone

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
    """SessionLocal 로 실행/정지 상태 + due 한 SourceProduct 1건 시드."""
    from shared.db import SessionLocal
    from lemouton.pricing.settings import get_or_init
    from lemouton.sources.models import SourceProduct
    s = SessionLocal()
    try:
        gs = get_or_init(s)
        gs.crawl_auto_enabled = enabled
        gs.crawl_interval_hours = 6
        gs.crawl_interval_minutes = 0
        # 미크롤(=반드시 due) URL 1건 (유니크 url 로 중복 시드 방지)
        url = "https://example.test/crawl-queue-seed"
        if not s.query(SourceProduct).filter_by(url=url).first():
            s.add(SourceProduct(site="musinsa", url=url, crawl_weight=1,
                                no_change_streak=0, last_fetched_at=None))
        s.commit()
    finally:
        s.close()


def test_enabled_returns_items(client):
    _seed(enabled=True)
    r = client.get("/api/crawl/queue")
    assert r.status_code == 200
    d = r.get_json()
    assert d["enabled"] is True
    assert d["count"] >= 1
    assert any(it["url"].endswith("crawl-queue-seed") for it in d["items"])


def test_disabled_returns_empty(client):
    _seed(enabled=False)
    r = client.get("/api/crawl/queue")
    assert r.status_code == 200
    d = r.get_json()
    assert d["enabled"] is False
    assert d["items"] == []
