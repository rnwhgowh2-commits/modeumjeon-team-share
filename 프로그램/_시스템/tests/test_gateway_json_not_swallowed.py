# -*- coding: utf-8 -*-
"""앞단(Cloudflare/Caddy)이 502·504 본문을 오류 HTML 로 갈아치우는 문제 회귀 방지.

라이브 실측(2026-08-12): 앱이 `jsonify({...}), 502` 를 내면 브라우저에는 Cloudflare
"Bad gateway" HTML 이 도착하고 앱 헤더(X-Server-Time-Ms)까지 사라진다. 그래서 화면은
사유 대신 「Unexpected token '<'」 만 본다. → JSON 응답의 502·504 는 424 로 바꿔 내보낸다.
"""
import pytest


@pytest.fixture(scope="module")
def app():
    from app import create_app
    a = create_app()
    a.config["TESTING"] = True

    # 테스트 전용 라우트 — 실제 마켓 호출 없이 상태코드 변환만 검증한다.
    from flask import jsonify

    @a.route("/__t/json502")
    def _json502():
        return jsonify({"ok": False, "error": "마켓이 거절함", "hint": "키 확인"}), 502

    @a.route("/__t/json504")
    def _json504():
        return jsonify({"ok": False, "error": "마켓 응답 없음"}), 504

    @a.route("/__t/json500")
    def _json500():
        return jsonify({"ok": False, "error": "우리 서버 잘못"}), 500

    @a.route("/__t/html502")
    def _html502():
        return "<h1>bad gateway</h1>", 502

    return a


def test_json_502_becomes_424_with_body_intact(app):
    """502 JSON → 424. 사유·hint 가 그대로 살아 있어야 한다."""
    r = app.test_client().get("/__t/json502")
    assert r.status_code == 424, "502 그대로면 앞단이 본문을 갈아치운다"
    assert r.headers.get("X-Upstream-Status") == "502"
    body = r.get_json()
    assert body["ok"] is False
    assert body["error"] == "마켓이 거절함"
    assert body["hint"] == "키 확인"


def test_json_504_becomes_424(app):
    r = app.test_client().get("/__t/json504")
    assert r.status_code == 424
    assert r.headers.get("X-Upstream-Status") == "504"
    assert r.get_json()["error"] == "마켓 응답 없음"


def test_json_500_untouched(app):
    """500 은 앞단이 통과시키므로 건드리지 않는다(의미 보존)."""
    r = app.test_client().get("/__t/json500")
    assert r.status_code == 500
    assert "X-Upstream-Status" not in r.headers


def test_html_502_untouched(app):
    """JSON 이 아닌 응답은 손대지 않는다."""
    r = app.test_client().get("/__t/html502")
    assert r.status_code == 502
    assert "X-Upstream-Status" not in r.headers
