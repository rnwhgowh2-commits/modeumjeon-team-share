# -*- coding: utf-8 -*-
"""[TEST] /api/admin/price-integrity 읽기전용 점검 엔드포인트 (2026-06-13).

라이브에서 SSH/자격증명 없이 URL 한 번으로 불변식 위반을 확인하는 도구.
데이터 변경이 없어야 하고(SELECT only), HTML·JSON 둘 다 200 이어야 한다.
"""
import os

import pytest

os.environ.setdefault("ENVIRONMENT", "test")


@pytest.fixture
def client():
    # 점검이 '빈 테이블 대상'으로 실제 실행되도록 스키마 생성(없으면 OperationalError).
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
    from webapp.routes.api_pricing import bp
    app = Flask(__name__)
    app.register_blueprint(bp)
    app.config.update(TESTING=True)
    return app.test_client()


def test_json_shape(client):
    r = client.get("/api/admin/price-integrity?format=json")
    assert r.status_code == 200
    d = r.get_json()
    assert set(["ok", "db", "total_violations", "errored", "checks"]) <= set(d.keys())
    # 7개 불변식이 모두 실행(또는 에러처리)돼 반환돼야 함.
    assert len(d["checks"]) == 7
    for c in d["checks"]:
        assert set(["code", "title", "money_impact", "count", "ok", "errored", "samples"]) <= set(c.keys())


def test_html_renders(client):
    r = client.get("/api/admin/price-integrity")
    assert r.status_code == 200
    assert r.mimetype == "text/html"
    assert b"<table>" in r.data
