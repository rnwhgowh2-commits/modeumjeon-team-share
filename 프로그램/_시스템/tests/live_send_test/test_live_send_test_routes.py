# -*- coding: utf-8 -*-
"""실전송 테스트 화면 라우트 — 페이지 200 · 검색/미리보기 200(실전송 없음) ·
전송 게이트(서버키 off → use_real False + 거부사유, 실제 전송 0).

실데이터·실마켓 없이 로컬에서 검증 가능한 범위: 라우트 응답·드라이런 경로·게이트.
빈 결과(0건)는 정상 — 스키마만 있고 구성 데이터가 없어도 통과해야 한다.

디렉터리명 주의: 최상위 `webapp` 패키지와 충돌하지 않도록 `tests/live_send_test/`.
(tests/ 는 __init__ 없음 → pytest 가 tests/ 를 sys.path 에 올림 → tests/webapp 가
있으면 실 webapp 패키지를 가려 create_app import 가 깨진다. 그래서 다른 이름 사용.)
"""
import pytest


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("DISABLE_AUTH", "1")
    # 서버키 확실히 OFF — 실전송 무장 방지(테스트 환경 불변식)
    monkeypatch.delenv("MOUM_LIVE_UPLOAD", raising=False)
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config["TESTING"] = True
    return flask_app.test_client()


def test_page_renders(client):
    r = client.get("/live-send-test")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "실전송 테스트" in html


def test_search_returns_json_list(client):
    r = client.get("/api/live-send-test/search?q=__없는검색어__zzz")
    assert r.status_code == 200
    body = r.get_json()
    assert isinstance(body.get("results"), list)


def test_preview_no_send_empty_ok(client):
    r = client.post("/api/live-send-test/preview",
                    json={"set_id": 999999, "markets": []})
    assert r.status_code == 200
    body = r.get_json()
    assert isinstance(body.get("rows"), list)
    # 없는 구성 → 빈 미리보기 (0건 정상)
    assert body["rows"] == []


def test_send_refused_without_confirm(client):
    """confirmed 없음 → use_real False + '확인' 거부사유. 실제 전송 0."""
    r = client.post("/api/live-send-test/send",
                    json={"set_id": 999999, "markets": [], "confirmed": False})
    assert r.status_code == 200
    body = r.get_json()
    assert body["use_real"] is False
    assert body["refusal"] and "확인" in body["refusal"]
    assert body["result"]["uploaded"] == 0


def test_send_refused_without_server_key(client):
    """confirmed=True 라도 서버키 off → use_real False + MOUM_LIVE_UPLOAD 거부. 전송 0."""
    r = client.post("/api/live-send-test/send",
                    json={"set_id": 999999, "markets": [], "confirmed": True})
    assert r.status_code == 200
    body = r.get_json()
    assert body["use_real"] is False
    assert body["refusal"] and "MOUM_LIVE_UPLOAD" in body["refusal"]
    assert body["result"]["uploaded"] == 0
