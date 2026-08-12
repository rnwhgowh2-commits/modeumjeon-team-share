# -*- coding: utf-8 -*-
"""스마트스토어 연결 테스트 — 네이버가 준 실패 사유가 화면 문구까지 살아 오는지.

2026-08-12 실측: 브랜드타임(스스)이 네이버에서 HTTP 400
`auth.eapp-application.status.invalid`(어플리케이션 상태가 유효하지 않습니다)를 받는데,
화면에는 「HTTP 400」 숫자만 떠서 사장님이 무엇을 해야 할지 알 수 없었다.
숫자가 아니라 **사유와 할 일**이 나와야 한다.
"""
import json

import pytest
from flask import Flask


_NAVER_APP_STATUS_400 = (
    '{"code":"BadRequest","message":"입력한 데이터가 유효하지 않습니다.",'
    '"invalidInputs":[{"type":"auth.eapp-application.status.invalid",'
    '"message":"어플리케이션 상태가 유효하지 않습니다."}]}'
)


class _Creds:
    client_id = "TESTCLIENTID"
    # 네이버 Client Secret = bcrypt salt 형식($2a$04$ + 22자). 형식 검사를 통과하고
    # bcrypt.hashpw 까지 실제로 돌아야 우리가 보려는 400 처리 분기에 닿는다.
    #  ★ 손으로 지어낸 22자는 bcrypt 가 거부한다(마지막 글자가 2비트만 담아서).
    #    gensalt 로 진짜 salt 를 만든다.
    client_secret = __import__("bcrypt").gensalt(4).decode()


def _resp(status: int, text: str):
    class _R:
        status_code = status

        def __init__(self):
            self.text = text

        def json(self):
            return json.loads(text)

    return _R()


@pytest.fixture
def ctx():
    return Flask(__name__).test_request_context()


def _call(monkeypatch, ctx, status, text):
    import requests
    import webapp.routes.accounts as A

    monkeypatch.setattr(requests, "post", lambda *a, **k: _resp(status, text))
    with ctx:
        resp, code = A._test_smartstore(_Creds(), "브랜드타임(스스)", "SMARTSTORE_X")
        return json.loads(resp.get_data(as_text=True)), code


def test_앱상태_400_은_사유와_할일이_문구에_나온다(monkeypatch, ctx):
    body, code = _call(monkeypatch, ctx, 400, _NAVER_APP_STATUS_400)

    assert body["ok"] is False
    assert body["status_code"] == 400
    # ① 숫자만 있으면 안 된다 — 네이버가 준 말이 error 에 붙어 있어야 한다.
    assert "어플리케이션 상태가 유효하지 않습니다" in body["error"], body["error"]
    # ② 무엇을 해야 하는지 — '앱 상태'이지 '키'가 아니라는 것이 hint 에 있어야 한다.
    assert "애플리케이션" in body["hint"]
    assert "키를 다시 넣어도" in body["hint"], "키 재입력 헛수고를 막는 문장이 빠졌다"


def test_401_은_키_안내가_유지된다(monkeypatch, ctx):
    body, _ = _call(monkeypatch, ctx, 401, '{"message":"Unauthorized"}')
    assert "Client ID/Secret" in body["hint"]
    assert "Unauthorized" in body["error"]


def test_사유를_못_꺼내도_판정은_그대로(monkeypatch, ctx):
    """네이버가 JSON 이 아닌 것을 줘도 실패 판정·본문 보존은 유지된다."""
    body, _ = _call(monkeypatch, ctx, 500, "<html>naver down</html>")
    assert body["ok"] is False
    assert body["status_code"] == 500
    assert "naver down" in body["body_snippet"]
