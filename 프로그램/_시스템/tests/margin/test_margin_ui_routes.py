# -*- coding: utf-8 -*-
"""margin 탭 화면 — C3: 원본 마진계산기 풀페이지를 same-origin iframe 으로 임베드.

구 재구현본(margin_app.js·margin_render.js·margin.css)은 폐기됨. 탭은 이제
/orders/margin-embed 를 가리키는 iframe 만 담는다.
"""
import pytest


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("DISABLE_AUTH", "1")
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config["TESTING"] = True
    return flask_app.test_client()


def test_margin_tab_renders(client):
    r = client.get("/orders/?tab=margin")
    assert r.status_code == 200


def test_margin_tab_embeds_iframe(client):
    """탭 = /orders/margin-embed 를 가리키는 iframe (원본 풀페이지 임베드)."""
    html = client.get("/orders/?tab=margin").get_data(as_text=True)
    assert "<iframe" in html
    assert 'id="margin-embed-frame"' in html
    # url_for('orders.margin_embed') 해석 경로
    assert "/orders/margin-embed" in html


def test_margin_tab_no_retired_reimplementation(client):
    """폐기된 재구현본 자산·마커가 탭 HTML 에 남아있지 않아야 한다."""
    html = client.get("/orders/?tab=margin").get_data(as_text=True)
    assert "margin_app.js" not in html
    assert "margin_render.js" not in html
    assert "margin.css" not in html
    assert 'id="margin-app"' not in html


def test_embed_route_reachable(client):
    """iframe src 가 실제로 200 을 반환(404 임베드 방지)."""
    r = client.get("/orders/margin-embed")
    assert r.status_code == 200
    assert r.headers.get("X-Frame-Options") == "SAMEORIGIN"
