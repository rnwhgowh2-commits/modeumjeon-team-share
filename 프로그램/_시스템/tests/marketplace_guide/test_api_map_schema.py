"""판매처 API 지도 데이터 — 스키마·완성게이트·참조무결성."""
import pytest
import pathlib
from flask import Flask
from webapp.routes import marketplace_guide as mg
from webapp.marketplace_api_map import load_map, validate_map


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

def test_load_map_returns_dict():
    data = load_map()
    assert isinstance(data, dict)
    assert data["schema_version"] == 1

def test_validate_clean_data_has_no_errors():
    errors = validate_map(load_map())
    assert errors == [], f"검증 오류: {errors}"

def test_completeness_gate_flags_ok_api_missing_response():
    bad = {
        "schema_version": 1, "markets": [], "unifiedStatuses": [],
        "transitions": [], "codes": [],
        "apis": [{"id":"x.y","market":"coupang","fnKey":"y","tabs":["상품 조회"],
                  "category":"상품","nm":"조회","dir":"recv","st":"ok",
                  "endpoint":"GET /x","req":{"p":1},"res":{},
                  "fields":[{"key":"a","meaning":"b","example":"c"}],"success":"code==200",
                  "idTraps":[],"persistIds":[],"codeRef":""}],
    }
    errors = validate_map(bad)
    assert any("res" in e and "x.y" in e for e in errors)

def test_transition_reference_must_exist_or_unsupported():
    bad = {
        "schema_version": 1, "markets": [], "unifiedStatuses": [],
        "transitions": [{"from":"a","to":"b","requires":[],
                         "perMarket":{"coupang":"ghost.api.id"}}],
        "codes": [], "apis": [],
    }
    errors = validate_map(bad)
    assert any("ghost.api.id" in e for e in errors)

def test_api_ids_are_unique():
    dup = {
        "schema_version": 1, "markets": [], "unifiedStatuses": [],
        "transitions": [], "codes": [],
        "apis": [
            {"id":"dup","market":"coupang","fnKey":"f","tabs":[],"category":"c","nm":"n","dir":"recv","st":"off","endpoint":"","req":{},"res":{},"fields":[],"success":"","idTraps":[],"persistIds":[],"codeRef":""},
            {"id":"dup","market":"coupang","fnKey":"f","tabs":[],"category":"c","nm":"n","dir":"recv","st":"off","endpoint":"","req":{},"res":{},"fields":[],"success":"","idTraps":[],"persistIds":[],"codeRef":""},
        ],
    }
    errors = validate_map(dup)
    assert any("dup" in e and "중복" in e for e in errors)

def test_map_data_route_serves_valid_json(client):
    resp = client.get("/marketplace-guide/map-data.json")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["schema_version"] == 1
    assert body.get("validation_errors") == []
