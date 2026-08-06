# -*- coding: utf-8 -*-
"""왕복 실전송 라우트 — 2중 잠금(arm + 서버키)이 실제로 잠겨 있는지.

이 라우트는 마켓에 **진짜로 값을 쓴다.** 그래서 잠금이 하나라도 풀려 있으면
실수 한 번에 마켓 상품이 바뀐다. 잠금이 걸린 상태에서 전송이 0건인지를 못 박는다.
"""
import pytest


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("DISABLE_AUTH", "1")
    monkeypatch.delenv("MOUM_LIVE_UPLOAD", raising=False)   # 서버키 OFF
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config["TESTING"] = True
    return flask_app.test_client()


def test_서버키가_꺼져_있으면_전송하지_않는다(client):
    r = client.post("/api/live-send-test/roundtrip",
                    json={"market": "smartstore", "origin_product_no": 1, "arm": "1"})

    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is False
    assert body["armed"] is False
    assert "MOUM_LIVE_UPLOAD" in (body.get("refusal") or "")
    assert body.get("sent") in (0, None)


def test_arm_이_없으면_서버키가_켜져도_전송하지_않는다(client, monkeypatch):
    monkeypatch.setenv("MOUM_LIVE_UPLOAD", "1")

    r = client.post("/api/live-send-test/roundtrip",
                    json={"market": "smartstore", "origin_product_no": 1})

    body = r.get_json()
    assert body["ok"] is False
    assert body["armed"] is False
    assert "arm" in (body.get("refusal") or "")


def test_지원하지_않는_마켓은_거부한다(client, monkeypatch):
    monkeypatch.setenv("MOUM_LIVE_UPLOAD", "1")

    r = client.post("/api/live-send-test/roundtrip",
                    json={"market": "coupang", "origin_product_no": 1, "arm": "1"})

    body = r.get_json()
    assert body["ok"] is False
    assert "coupang" in (body.get("refusal") or "")


def test_상품번호가_없으면_거부한다(client, monkeypatch):
    monkeypatch.setenv("MOUM_LIVE_UPLOAD", "1")

    r = client.post("/api/live-send-test/roundtrip",
                    json={"market": "smartstore", "arm": "1"})

    body = r.get_json()
    assert body["ok"] is False
    assert "상품번호" in (body.get("refusal") or "")


def test_후보조회는_읽기전용이라_잠금없이_된다(client):
    """판매중지 후보 찾기는 GET 만 한다 — 마켓에 아무것도 안 쓴다."""
    r = client.get("/api/live-send-test/roundtrip-candidates?market=smartstore")

    assert r.status_code == 200
    body = r.get_json()
    assert "candidates" in body or "error" in body
