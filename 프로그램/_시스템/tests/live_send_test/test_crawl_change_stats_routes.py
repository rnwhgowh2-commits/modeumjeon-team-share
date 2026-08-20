# -*- coding: utf-8 -*-
"""[Phase 1B M5] 랩 보고서 라우트 + 계수 화면 렌더.

빈 DB 에서도 200 이어야 한다 — 기록이 아직 없는 것과 화면이 깨진 것은 다르다.
(디렉터리명 주의는 test_live_send_test_routes.py 상단 설명과 같은 이유.)
"""
import pytest


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("DISABLE_AUTH", "1")
    monkeypatch.delenv("MOUM_LIVE_UPLOAD", raising=False)   # 실전송 무장 방지
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config["TESTING"] = True
    return flask_app.test_client()


def test_change_stats_empty_db_ok(client):
    r = client.get("/api/crawl/change-stats")
    assert r.status_code == 200
    b = r.get_json()
    assert b["ok"] is True
    assert isinstance(b["rows"], list)
    assert b["totals"]["observed"] == 0


def test_change_stats_exposes_min_observations(client):
    """표본 기준을 화면이 그대로 문구에 쓴다 — 숫자가 두 곳에서 갈리면 안 된다."""
    from lemouton.sources.crawl_change_stats import MIN_OBSERVATIONS
    b = client.get("/api/crawl/change-stats").get_json()
    assert b["window"]["min_observations"] == MIN_OBSERVATIONS


def test_change_stats_laps_param_clamped(client):
    assert client.get("/api/crawl/change-stats?laps=0").get_json(
        )["window"]["laps_requested"] == 1
    assert client.get("/api/crawl/change-stats?laps=99999").get_json(
        )["window"]["laps_requested"] == 200
    # 숫자가 아니면 기본 10 (500 금지)
    assert client.get("/api/crawl/change-stats?laps=abc").get_json(
        )["window"]["laps_requested"] == 10


def test_change_stats_declares_metric_origins(client):
    """★지표마다 기준선이 다르다는 것을 응답이 스스로 말한다(화면이 지어내지 않게)."""
    from lemouton.sources.crawl_change_stats import SOURCE_FIELDS, GATE_FIELDS
    b = client.get("/api/crawl/change-stats").get_json()
    src = b["sources"]
    assert set(src["crawl_delta"]["fields"]) == set(SOURCE_FIELDS)
    assert src["gate_decision"]["fields"] == list(GATE_FIELDS) == ["p2_skipped"]


def test_change_stats_laps_cap_matches_retention(client):
    """구간 상한이 보관 기간을 넘으면 '있지도 않은 바퀴'를 요청하게 된다."""
    from lemouton.sources.crawl_change_stats import STATS_RETENTION_LAPS
    b = client.get("/api/crawl/change-stats?laps=99999").get_json()
    assert b["window"]["laps_requested"] == STATS_RETENTION_LAPS
    assert b["window"]["retention_laps"] == STATS_RETENTION_LAPS


def test_weights_page_renders_lap_report_section(client):
    r = client.get("/automation/weights")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "랩 보고서" in html
    assert "/api/crawl/change-stats" in html
    assert "크롤 계수 드릴다운" in html      # 기존 화면이 살아 있다


def test_weights_page_separates_the_two_baselines(client):
    """★화면에서 두 숫자의 출처가 달라 보여야 한다 — 섞어 놓으면 나중에 오독한다."""
    html = client.get("/automation/weights").get_data(as_text=True)
    assert "소싱처 기준 (크롤 변동 기록)" in html
    assert "마켓 기준 (업로드 판정)" in html
    assert "기준선이 둘입니다" in html
