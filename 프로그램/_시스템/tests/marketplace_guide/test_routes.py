# -*- coding: utf-8 -*-
"""판매처 가이드 라우트 — 200 + bare 시 X-Frame-Options SAMEORIGIN."""
import pathlib

import pytest
from flask import Flask

from webapp.routes import marketplace_guide as mg


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "test")   # _admin_only 우회
    app = Flask(
        __name__,
        template_folder="webapp/templates",
        root_path=pathlib.Path(mg.__file__).parents[2].as_posix(),
    )
    app.register_blueprint(mg.bp)
    return app.test_client()


def test_add_bare_sets_sameorigin(client):
    r = client.get("/marketplace-guide/add?bare=1")
    assert r.status_code == 200
    assert r.headers.get("X-Frame-Options") == "SAMEORIGIN"


def test_map_bare_sets_sameorigin(client):
    r = client.get("/marketplace-guide/map?bare=1")
    assert r.status_code == 200
    assert r.headers.get("X-Frame-Options") == "SAMEORIGIN"


def test_routes_registered(client):
    # 전체 페이지(base.html) 렌더는 앱 컨텍스트 프로세서가 필요 → 라우트 등록만 검증.
    rules = {r.rule for r in client.application.url_map.iter_rules()}
    assert "/marketplace-guide/add" in rules
    assert "/marketplace-guide/map" in rules
