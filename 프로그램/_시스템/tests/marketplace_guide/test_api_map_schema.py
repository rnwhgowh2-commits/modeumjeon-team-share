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


# ── 📘 API 문서 수집법 = 정본 JSON 단일 원천 (하드코딩 사본 금지) ──
def test_ingest_paths_route_serves_valid_json(client):
    resp = client.get("/marketplace-guide/ingest-paths.json")
    assert resp.status_code == 200
    d = resp.get_json()
    for k in ("routes", "grades", "matrix", "hier", "play", "snippet_rules", "decide", "measured_at"):
        assert d.get(k), f"수집법 정본 키 누락/빈값: {k}"
    codes = [r[0] for r in d["routes"]]
    assert "I" in codes, "경로 I(로그인 콘솔 스니펫) 누락"
    assert "A-2" in codes, "경로 A-2(신규 정적 이관본) 누락"
    # 매트릭스 = 6대 마켓 전부, 각 행 8칸(마켓+4셀+채택+접수+등급)
    assert len(d["matrix"]) == 6, "마켓 6개가 아님"
    for row in d["matrix"]:
        assert len(row) == 8, f"매트릭스 행 형식 불일치: {row[0]}"


def test_map_template_reads_ingest_paths_and_has_no_hardcoded_copy():
    """화면이 정본을 fetch 하고, 하드코딩 사본을 갖지 않는지 = 중복·모순 0 증명."""
    import os
    p = os.path.join(os.path.dirname(__file__), "..", "..", "webapp", "templates", "marketplace_guide", "map.html")
    html = open(os.path.abspath(p), encoding="utf-8").read()
    assert "/marketplace-guide/ingest-paths.json" in html, "수집법 탭이 정본을 fetch 하지 않음"
    # 과거 하드코딩 배열이 되살아나면 실패
    assert "const HW_ROUTES=[" not in html, "HW_ROUTES 하드코딩 사본 부활(정본 JSON만 써야 함)"
    assert "const HW_MX=[" not in html, "HW_MX 하드코딩 사본 부활"
    assert "const HW_HIER=[" not in html, "HW_HIER 하드코딩 사본 부활"
    assert "const HW_PLAY=[" not in html, "HW_PLAY 하드코딩 사본 부활"


def test_generated_doc_matches_source_of_truth():
    """docs/markets/_API문서수집법.md 가 정본에서 생성된 그대로인지(수동편집·표류 감지)."""
    import subprocess, sys, os
    script = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "api_ingest", "gen_doc.py"))
    r = subprocess.run([sys.executable, script, "--check"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    assert r.returncode == 0, f"문서가 정본과 다름 — gen_doc.py 재실행 필요\n{r.stdout}{r.stderr}"


def test_autoconfirm_sot():
    from webapp.marketplace_api_map import load_map, validate_map
    d = load_map()
    ac = d.get("autoConfirm")
    assert isinstance(ac, dict), "autoConfirm 누락"
    assert len(ac.get("markets", [])) == 4
    assert set(ac.get("calls", {})) == {"coupang", "smartstore", "lotteon", "eleven11"}
    # 기존 기준선 오류 2건(esm.140 fields — 다른 세션 작업영역)만 허용, 신규 오류 0
    errs_all = validate_map(d)
    esm140 = [e for e in errs_all if "esm.140" in e]
    non_esm = [e for e in errs_all if "esm.140" not in e]
    assert non_esm == []
    assert len(esm140) <= 2, f"esm.140 기준선 2건 초과: {esm140}"


def test_settlecalc_sot():
    from webapp.marketplace_api_map import load_map, validate_map
    d = load_map()
    sc = d.get("settleCalc")
    assert isinstance(sc, dict), "settleCalc 누락"
    n = len(sc["markets"])
    assert n == 4
    for r in sc["rows"]:
        assert len(r["cells"]) == n, r["item"]
    assert len(sc["total"]) == n
    assert len(sc["formulas"]) == n
    errs_all = validate_map(d)
    esm140 = [e for e in errs_all if "esm.140" in e]
    non_esm = [e for e in errs_all if "esm.140" not in e]
    assert non_esm == []
    assert len(esm140) <= 2, f"esm.140 기준선 2건 초과: {esm140}"


def test_ingest_paths_has_snippet_templates(client):
    """스니펫 템플릿 3종+판별 프로브가 정본에 있고 복붙 가능한 코드를 담고 있는지."""
    d = client.get("/marketplace-guide/ingest-paths.json").get_json()
    snips = {s["id"]: s for s in d.get("snippets", [])}
    for need in ("probe", "static", "server", "spa"):
        assert need in snips, f"스니펫 템플릿 누락: {need}"
        assert snips[need].get("code"), f"스니펫 코드 비어있음: {need}"
        assert snips[need].get("when"), f"스니펫 사용조건 비어있음: {need}"
    # 실측으로 확정된 핵심 규칙이 코드/설명에 남아 있어야 함(회귀 방지)
    assert "TextDecoder" in snips["server"]["code"], "EUC-KR 디코더 규칙 소실"
    assert "100000" in snips["static"]["code"], "캡 10만 규칙 소실(30k는 대형페이지 절단)"
    assert "실크롬" in snips["spa"]["reads"] or "실크롬" in snips["spa"]["code"], "SPA=실크롬 규칙 소실"
