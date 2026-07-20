"""프로브 라우트 게이트 — env 없이 열리면 안 된다(마켓 API 무인증 노출)."""
from __future__ import annotations

import flask
import pytest

from webapp.routes.period_probe import bp


@pytest.fixture
def client():
    app = flask.Flask(__name__)
    app.register_blueprint(bp)
    return app.test_client()


def test_env_없으면_404_로_닫힌다(client, monkeypatch):
    monkeypatch.delenv("PERIOD_PROBE", raising=False)
    assert client.get("/api/period-probe?market=coupang&kind=orders").status_code == 404
    assert client.get("/api/period-probe/sweep?market=coupang&kind=orders").status_code == 404


def test_env_켜면_열린다(client, monkeypatch):
    monkeypatch.setenv("PERIOD_PROBE", "1")
    r = client.get("/api/period-probe?market=shopmine&kind=orders")
    assert r.status_code == 400          # 게이트는 통과, 마켓명이 틀려 400
    assert "지원하지 않는 마켓" in r.get_json()["error"]


def test_axis_오타는_400(client, monkeypatch):
    monkeypatch.setenv("PERIOD_PROBE", "1")
    r = client.get("/api/period-probe/sweep?market=coupang&kind=orders&axis=wrong")
    assert r.status_code == 400
