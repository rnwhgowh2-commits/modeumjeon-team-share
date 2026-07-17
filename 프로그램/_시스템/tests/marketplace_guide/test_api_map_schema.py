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


# ── 과거이력(incidents) ──
def _base_map(incidents):
    return {
        "schema_version": 1, "markets": [{"id": "lotteon", "label": "롯데온"}],
        "unifiedStatuses": [], "transitions": [], "codes": [], "apis": [],
        "incidents": incidents,
    }


def test_incidents_seeded_and_ids_unique():
    data = load_map()
    incs = data.get("incidents")
    assert isinstance(incs, list) and len(incs) >= 6
    ids = [i["id"] for i in incs]
    assert len(ids) == len(set(ids)), "incident id 중복"


def test_incident_empty_fix_is_flagged():
    """기록 지침: 해결(fix) 칸이 비면 조용히 통과하지 않고 검증 오류."""
    bad = _base_map([{
        "id": "x", "date": "2026-07-17", "markets": ["lotteon"], "area": "가격/재고",
        "title": "t", "symptom": "s", "cause": "c", "fix": "   ",
        "commit": "", "severity": "high", "status": "resolved", "lesson": "l",
    }])
    errors = validate_map(bad)
    assert any("fix" in e and "x" in e for e in errors)


def test_incident_bad_severity_is_flagged():
    bad = _base_map([{
        "id": "y", "date": "2026-07-17", "markets": ["lotteon"], "area": "가격/재고",
        "title": "t", "symptom": "s", "cause": "c", "fix": "f",
        "commit": "", "severity": "critical", "status": "resolved", "lesson": "l",
    }])
    errors = validate_map(bad)
    assert any("severity" in e and "y" in e for e in errors)


def test_incident_unknown_market_is_flagged():
    bad = _base_map([{
        "id": "z", "date": "2026-07-17", "markets": ["ghostmarket"], "area": "가격/재고",
        "title": "t", "symptom": "s", "cause": "c", "fix": "f",
        "commit": "", "severity": "med", "status": "resolved", "lesson": "l",
    }])
    errors = validate_map(bad)
    assert any("ghostmarket" in e for e in errors)
