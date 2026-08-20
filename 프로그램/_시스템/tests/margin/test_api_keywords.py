# -*- coding: utf-8 -*-
"""/api/keywords 라우트 — 카드별 분류 키워드 (팀 공유).

원본 계약(C:/dev/대량등록 마진계산기/app.py 1283–1310)을 그대로 이식하되
저장소만 단일 사용자 JSON → 팀 공유 DB 한 행으로 승격한다.

- GET  → 전체 설정 JSON (top-level `cards` 포함) 그대로 반환.
- POST {cards:{...}}       → cards dict 전체 교체.
- POST {card, data}        → 한 카드만 교체 (나머지 보존).
- POST 검증 실패 → 400 (거짓 성공 금지).
"""
import pytest
from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shared.db import Base
from lemouton.margin.models import CardKeywordConfig  # noqa: F401  # 테이블 등록
from webapp.routes import api_keywords


@pytest.fixture
def client(tmp_path, monkeypatch):
    eng = create_engine(f"sqlite:///{tmp_path/'t.db'}", future=True)
    CardKeywordConfig.__table__.create(eng, checkfirst=True)
    Session = sessionmaker(bind=eng, future=True, expire_on_commit=False)
    monkeypatch.setattr(api_keywords, "SessionLocal", Session)

    app = Flask(__name__)
    app.register_blueprint(api_keywords.bp)
    app.config["TESTING"] = True
    c = app.test_client()
    c._Session = Session  # 테스트에서 새 세션 확인용
    return c


def test_get_returns_seeded_cards(client):
    r = client.get("/api/keywords")
    assert r.status_code == 200
    body = r.get_json()
    assert isinstance(body.get("cards"), dict)
    assert "confirmed_blackspot" in body["cards"]
    assert body["cards"]["confirmed_blackspot"]["memo"] == ["블랙"]


def test_post_cards_full_replace_persists(client):
    new_cards = {"only": {"memo": ["단일"], "label": "온리"}}
    r = client.post("/api/keywords", json={"cards": new_cards})
    assert r.status_code == 200
    body = r.get_json()
    assert body["status"] == "ok"
    assert body["data"]["cards"] == new_cards
    # GET 이 반영
    g = client.get("/api/keywords").get_json()
    assert g["cards"] == new_cards


def test_post_single_card_update_keeps_others(client):
    before = client.get("/api/keywords").get_json()["cards"]
    assert "memo_settled" in before
    r = client.post("/api/keywords",
                    json={"card": "confirmed_blackspot",
                          "data": {"memo": ["새"], "label": "확인된 블랙스팟"}})
    assert r.status_code == 200
    g = client.get("/api/keywords").get_json()["cards"]
    assert g["confirmed_blackspot"]["memo"] == ["새"]
    # 다른 카드 보존
    assert g["memo_settled"] == before["memo_settled"]


def test_post_non_dict_body_400(client):
    r = client.post("/api/keywords", json=[1, 2, 3])
    assert r.status_code == 400
    assert r.get_json()["error"] == "invalid body"


def test_post_empty_card_name_400(client):
    r = client.post("/api/keywords", json={"card": "", "data": {"memo": ["x"]}})
    assert r.status_code == 400
    assert "error" in r.get_json()


def test_post_neither_shape_400(client):
    r = client.post("/api/keywords", json={"foo": "bar"})
    assert r.status_code == 400
    assert r.get_json()["error"] == "expected {cards: {...}} or {card, data}"


def test_persists_across_new_session(client):
    """저장 후 새 세션(새 커넥션)이 값을 본다 — DB 저장 증명(팀 공유)."""
    client.post("/api/keywords", json={"cards": {"kept": {"label": "K"}}})
    from lemouton.margin import keyword_store as KS
    s2 = client._Session()
    try:
        cfg = KS.get_config(s2)
        assert list(cfg["cards"].keys()) == ["kept"]
    finally:
        s2.close()
