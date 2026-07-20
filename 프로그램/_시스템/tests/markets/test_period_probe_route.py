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


# ── 건수 절벽 탐지 — 11번가처럼 상한을 '빈 응답'으로 알리는 마켓 ──────────
from webapp.routes.period_probe import _find_cliff   # noqa: E402


def _step(win, cnt, verdict="accepted"):
    return {"window_days": win, "back_days": 0, "count": cnt, "verdict": verdict}


def _win(s):
    return s["window_days"]


def test_건수가_0으로_떨어지면_절벽으로_경고한다():
    """11번가 실측: 7일 15건 → 8일 0건. 에러가 없어 verdict 는 계속 accepted."""
    steps = [_step(6, 14), _step(7, 15), _step(8, 0), _step(31, 0)]
    c = _find_cliff(steps, _win)
    assert c and c["from"] == 7 and c["to"] == 8 and c["from_count"] == 15


def test_계속_0건이면_절벽이_아니다():
    """처음부터 데이터가 없는 계정 — 절벽으로 오인하면 없는 상한을 만든다."""
    assert _find_cliff([_step(7, 0), _step(8, 0)], _win) is None


def test_건수가_유지되면_절벽이_아니다():
    assert _find_cliff([_step(7, 15), _step(31, 40)], _win) is None


def test_거부_스텝은_절벽_연결을_끊는다():
    """rejected 를 사이에 두고 0 이 되는 건 상한이지 조용한 유실이 아니다."""
    steps = [_step(7, 15), _step(8, 0, "rejected"), _step(9, 0)]
    assert _find_cliff(steps, _win) is None
