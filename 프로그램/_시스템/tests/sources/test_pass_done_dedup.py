# -*- coding: utf-8 -*-
"""[TEST] /api/crawl/pass-done 20초 디듀프 — 짧은 간격 중복 통보는 바퀴 1개만.

'오늘 N바퀴' 로그(CrawlLapRun)는 pass-done 만 만든다. 다탭·확장+페이지 이중 경로로
같은 패스 완료가 여러 번 와도 20초 안이면 CrawlLapRun 이 1행만 늘어야 한다(서버 방어선).
클라이언트 쪽 '실행당 1회' 수정(tests/js/test_pass_done_once_per_lap.js)과 이중 안전.
"""
import os
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from flask import Flask

os.environ.setdefault("ENVIRONMENT", "test")

for _m in (
    "lemouton.sourcing.models", "lemouton.sourcing.models_pricing",
    "lemouton.sourcing.models_v2", "lemouton.pricing.settings",
    "lemouton.uploader.models", "lemouton.templates.models",
    "lemouton.inventory.models", "lemouton.sources.models",
    "lemouton.multitenancy.models", "lemouton.audit.models",
    "lemouton.mapping.models",
):
    try:
        __import__(_m)
    except ImportError:
        pass

from lemouton.sources.models import CrawlLapRun
from shared.db import Base


@pytest.fixture
def client(monkeypatch):
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    import webapp.routes.api as _api
    monkeypatch.setattr(_api, "SessionLocal", lambda: Session(eng))
    app = Flask(__name__)
    app.register_blueprint(_api.bp)
    app.config.update(TESTING=True)
    return app.test_client(), eng


def _laps(eng):
    s = Session(eng)
    try:
        return s.query(CrawlLapRun).count()
    finally:
        s.close()


def test_first_pass_done_records_one_lap(client):
    c, eng = client
    r = c.post("/api/crawl/pass-done")
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json().get("reset") is not None
    assert _laps(eng) == 1


def test_rapid_duplicate_pass_done_deduped_to_one(client):
    c, eng = client
    for _ in range(5):                       # 같은 패스가 다탭·이중경로로 5번 통보
        assert c.post("/api/crawl/pass-done").status_code == 200
    assert _laps(eng) == 1, "20초 내 중복 통보는 바퀴 1개만 기록해야"
