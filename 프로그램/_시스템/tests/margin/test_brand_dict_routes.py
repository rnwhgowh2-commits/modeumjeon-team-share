# -*- coding: utf-8 -*-
"""[TEST] /api/brand_dict(/suggest) — 브랜드 사전 조회·추가/삭제·미확정 자동추천.

바레 Flask + api_brand_dict 블루프린트만 검증. 브랜드 사전 파일은 tmp 로 격리해
실 brand_dict.json 을 건드리지 않는다. suggest 는 스테이징된 매입 엑셀(pending_store, DB 단일 행)을 사용.
"""
import io
import json

import pandas as pd
import pytest
from flask import Flask

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from lemouton.margin import brand_dict as bd
from lemouton.margin.models import MarginPendingUpload   # 테이블 등록
from webapp.routes.api_brand_dict import bp
from webapp.routes import api_margin


@pytest.fixture
def client(tmp_path, monkeypatch):
    # 실 사전 파일 격리 + 캐시 초기화
    p = tmp_path / "brand_dict.json"
    p.write_text(json.dumps({"라코스테": "라코스테"}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(bd, "_DEFAULT_PATH", str(p))
    monkeypatch.setattr(bd, "_CACHED_MAP", None)
    # 스테이징 저장소(DB) 격리 — 워커가 여럿이라 전역 dict 대신 DB 를 쓴다.
    eng = create_engine(f"sqlite:///{tmp_path / 'p.db'}", future=True)
    MarginPendingUpload.__table__.create(eng, checkfirst=True)
    monkeypatch.setattr(api_margin, "SessionLocal",
                        sessionmaker(bind=eng, future=True, expire_on_commit=False))

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
    # 실제 업로드처럼 **엑셀 바이트**를 스테이징한다(분석 때 다시 파싱하는 경로 그대로).
    from lemouton.margin import pending_store as _ps
    buf = io.BytesIO()
    full = df.assign(**{"마켓주문일자": "26.07.04", "마켓명": "쿠팡", "마켓주문번호": "1",
                        "수령인명": "홍", "옵션1": "", "구매가격": 1000})
    full.to_excel(buf, index=False)
    _s = api_margin.SessionLocal()
    try:
        _ps.stage_buy(_s, raw=buf.getvalue(), filename="더망고.xlsx",
                      period_from=None, period_to=None)
    finally:
        _s.close()
    j = client.get("/api/brand_dict/suggest").get_json()
    kws = {s["keyword"]: s for s in j["suggestions"]}
    assert kws["커버낫"]["count"] == 2          # 빈도 반영
    assert kws["CHAMPION"]["brand"] == "챔피언"  # 정규화 브랜드 채움
    assert "라코스테" not in kws                 # 이미 분류됨 → 제외
    assert j["unresolvable"] == 1               # 브랜드없는 상품명
