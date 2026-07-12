# -*- coding: utf-8 -*-
"""[TEST] /api/brand_dict(/suggest) — 브랜드 사전 조회·추가/삭제·미확정 자동추천.

바레 Flask + api_brand_dict 블루프린트만 검증. 브랜드 사전 파일은 tmp 로 격리해
실 brand_dict.json 을 건드리지 않는다. suggest 는 무상태(_PENDING['buy']) 매입 DF 사용.
"""
import json

import pandas as pd
import pytest
from flask import Flask

from lemouton.margin import brand_dict as bd
from webapp.routes.api_brand_dict import bp
from webapp.routes import api_margin


@pytest.fixture
def client(tmp_path, monkeypatch):
    # 실 사전 파일 격리 + 캐시 초기화
    p = tmp_path / "brand_dict.json"
    p.write_text(json.dumps({"라코스테": "라코스테"}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(bd, "_DEFAULT_PATH", str(p))
    monkeypatch.setattr(bd, "_CACHED_MAP", None)
    monkeypatch.setattr(api_margin, "_PENDING", {})

    app = Flask(__name__)
    app.register_blueprint(bp)
    app.config.update(TESTING=True)
    return app.test_client()


def test_get_returns_brands(client):
    r = client.get("/api/brand_dict")
    assert r.status_code == 200
    assert r.get_json()["brands"].get("라코스테") == "라코스테"


def test_post_single_adds_and_persists(client):
    r = client.post("/api/brand_dict", json={"keyword": "커버낫", "brand": "커버낫"})
    assert r.status_code == 200 and r.get_json()["ok"] is True
    # 재조회 반영
    assert client.get("/api/brand_dict").get_json()["brands"]["커버낫"] == "커버낫"


def test_post_items_bulk_add(client):
    r = client.post("/api/brand_dict", json={"items": [
        {"keyword": "CHAMPION", "brand": "챔피언"},
        {"keyword": "KEEN", "brand": "킨"},
        {"keyword": "", "brand": "무시"},          # 빈 키워드는 무시
    ]})
    j = r.get_json()
    assert j["added"] == 2
    assert j["brands"]["CHAMPION"] == "챔피언" and j["brands"]["KEEN"] == "킨"


def test_post_delete_removes(client):
    client.post("/api/brand_dict", json={"keyword": "커버낫", "brand": "커버낫"})
    client.post("/api/brand_dict", json={"keyword": "커버낫", "delete": True})
    assert "커버낫" not in client.get("/api/brand_dict").get_json()["brands"]


def test_post_requires_keyword_or_brand(client):
    assert client.post("/api/brand_dict", json={}).status_code == 400
    assert client.post("/api/brand_dict", json={"keyword": "X"}).status_code == 400  # brand 없음


def test_suggest_empty_when_no_upload(client):
    r = client.get("/api/brand_dict/suggest")
    assert r.status_code == 200
    assert r.get_json()["suggestions"] == []


def test_suggest_from_staged_buy_df(client, monkeypatch):
    # 사전엔 '라코스테'만 → 커버낫/CHAMPION 은 미확정 → 후보로 추천
    df = pd.DataFrame({"마켓상품명": [
        "매장정품 커버낫 반팔 A", "매장정품 커버낫 반팔 B",   # 커버낫 2건 (미확정)
        "매장정품 CHAMPION 반팔 C",                          # 챔피언 1건 (미확정)
        "매장정품 라코스테 반팔 D",                          # 라코스테는 사전에 있음 → 제외
        "브랜드없는 상품명 E",                                # unresolvable
    ]})
    monkeypatch.setitem(api_margin._PENDING, "buy", {"df": df})
    j = client.get("/api/brand_dict/suggest").get_json()
    kws = {s["keyword"]: s for s in j["suggestions"]}
    assert kws["커버낫"]["count"] == 2          # 빈도 반영
    assert kws["CHAMPION"]["brand"] == "챔피언"  # 정규화 브랜드 채움
    assert "라코스테" not in kws                 # 이미 분류됨 → 제외
    assert j["unresolvable"] == 1               # 브랜드없는 상품명
