# -*- coding: utf-8 -*-
"""/api/product-counts 라우트 — 계층 분석 경로별 등록수 (팀 공유).

원본 계약(C:/dev/대량등록 마진계산기/app.py 1335–1359)을 그대로 이식하되 저장소만
단일 사용자 product_counts.json → 팀 공유 DB 한 행(ProductCountConfig)으로 승격한다.

- GET  → {"counts": {경로키: 등록수}}
- POST {key, count}   → 저장 후 {"ok": True, "counts": {...}}
- POST {key, delete}  → 삭제
- POST 검증 실패(key 없음·count 비정수) → 400 (거짓 성공 금지).
"""
import pytest
from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from lemouton.margin.models import ProductCountConfig  # noqa: F401  # 테이블 등록
from webapp.routes import api_product_counts


@pytest.fixture
def client(tmp_path, monkeypatch):
    eng = create_engine(f"sqlite:///{tmp_path/'t.db'}", future=True)
    ProductCountConfig.__table__.create(eng, checkfirst=True)
    Session = sessionmaker(bind=eng, future=True, expire_on_commit=False)
    monkeypatch.setattr(api_product_counts, "SessionLocal", Session)

    app = Flask(__name__)
    app.register_blueprint(api_product_counts.bp)
    app.config["TESTING"] = True
    return app.test_client()


def test_get_empty_initially(client):
    r = client.get("/api/product-counts")
    assert r.status_code == 200
    assert r.get_json() == {"counts": {}}


def test_post_saves_and_get_reflects(client):
    r = client.post("/api/product-counts", json={"key": "마켓|스마트스토어", "count": 42})
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    assert body["counts"] == {"마켓|스마트스토어": 42}
    # 별도 요청(=별도 세션)에서도 영속 확인
    assert client.get("/api/product-counts").get_json()["counts"] == {"마켓|스마트스토어": 42}


def test_post_multiple_keys_merge(client):
    client.post("/api/product-counts", json={"key": "A", "count": 1})
    client.post("/api/product-counts", json={"key": "B", "count": 2})
    assert client.get("/api/product-counts").get_json()["counts"] == {"A": 1, "B": 2}


def test_post_delete_removes_key(client):
    client.post("/api/product-counts", json={"key": "A", "count": 5})
    r = client.post("/api/product-counts", json={"key": "A", "delete": True})
    assert r.status_code == 200
    assert "A" not in r.get_json()["counts"]


def test_post_requires_key(client):
    r = client.post("/api/product-counts", json={"count": 3})
    assert r.status_code == 400


def test_post_rejects_non_integer_count(client):
    r = client.post("/api/product-counts", json={"key": "A", "count": "abc"})
    assert r.status_code == 400
    # 거짓 성공 금지 — 저장 안 됨
    assert client.get("/api/product-counts").get_json()["counts"] == {}
