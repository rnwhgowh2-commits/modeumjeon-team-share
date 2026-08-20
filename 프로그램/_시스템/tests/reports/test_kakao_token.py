# -*- coding: utf-8 -*-
"""카카오 토큰 수명 관리 — 갱신·보존·만료 임박 판정."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from shared import kakao_token as kt


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(kt, "_TOKEN_PATH", str(tmp_path / "tok.json"))
    monkeypatch.setenv("KAKAO_REST_KEY", "restkey")
    monkeypatch.delenv("KAKAO_REFRESH_TOKEN", raising=False)
    monkeypatch.delenv("KAKAO_CLIENT_SECRET", raising=False)
    yield


class _Resp:
    def __init__(self, status, payload=None, text=""):
        self.status_code = status
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


def _seed(access="old-access", refresh="REFRESH-1", expires_in=21600,
          refresh_expires_at=None):
    data = {
        "access_token": access,
        "refresh_token": refresh,
        "expires_at": (datetime.now(timezone.utc)
                       + timedelta(seconds=expires_in)).isoformat(),
    }
    if refresh_expires_at:
        data["refresh_expires_at"] = refresh_expires_at
    kt._save(data)


# ──────────────────────────────────────────────────────────────
def test_유효한_토큰이면_갱신하지_않는다(monkeypatch):
    _seed(expires_in=21600)
    called = []
    monkeypatch.setattr(kt.requests, "post",
                        lambda *a, **k: called.append(1) or _Resp(200, {}))
    assert kt.get_access_token() == "old-access"
    assert called == []


def test_만료_임박이면_갱신한다(monkeypatch):
    _seed(expires_in=60)   # 여유 600초보다 짧다
    monkeypatch.setattr(kt.requests, "post", lambda *a, **k: _Resp(
        200, {"access_token": "new-access", "expires_in": 21600}))
    assert kt.get_access_token() == "new-access"


def test_갱신응답에_refresh_token_없으면_기존것을_지키다(monkeypatch):
    """★함정 — 덮어쓰면 다음 갱신이 통째로 불가능해진다(재로그인 강제)."""
    _seed(expires_in=60, refresh="REFRESH-1")
    monkeypatch.setattr(kt.requests, "post", lambda *a, **k: _Resp(
        200, {"access_token": "new-access", "expires_in": 21600}))

    kt.get_access_token()
    saved = json.load(open(kt._TOKEN_PATH, encoding="utf-8"))
    assert saved["refresh_token"] == "REFRESH-1"


def test_갱신응답에_refresh_token_오면_갈아끼운다(monkeypatch):
    """잔여 1개월 미만이면 카카오가 새 갱신 토큰을 준다 — 이걸 받아야 영구 유지된다."""
    _seed(expires_in=60, refresh="REFRESH-1")
    monkeypatch.setattr(kt.requests, "post", lambda *a, **k: _Resp(200, {
        "access_token": "new-access", "expires_in": 21600,
        "refresh_token": "REFRESH-2", "refresh_token_expires_in": 5184000}))

    kt.get_access_token()
    saved = json.load(open(kt._TOKEN_PATH, encoding="utf-8"))
    assert saved["refresh_token"] == "REFRESH-2"
    assert saved["refresh_expires_at"]


def test_환경변수_갱신토큰이_최초_씨앗이_된다(monkeypatch):
    """파일이 아직 없을 때 fly secret 으로 넣어둔 값으로 첫 갱신을 탄다."""
    monkeypatch.setenv("KAKAO_REFRESH_TOKEN", "SEED-REFRESH")
    captured = {}

    def _post(url, data=None, timeout=None):
        captured.update(data or {})
        return _Resp(200, {"access_token": "a", "expires_in": 21600})

    monkeypatch.setattr(kt.requests, "post", _post)
    kt.get_access_token()
    assert captured["refresh_token"] == "SEED-REFRESH"
    assert captured["grant_type"] == "refresh_token"


def test_갱신토큰_없으면_명확한_에러():
    with pytest.raises(kt.KakaoTokenError, match="최초 카카오 로그인"):
        kt.get_access_token()


def test_REST키_없으면_명확한_에러(monkeypatch):
    monkeypatch.delenv("KAKAO_REST_KEY", raising=False)
    _seed(expires_in=60)
    with pytest.raises(kt.KakaoTokenError, match="KAKAO_REST_KEY"):
        kt.get_access_token()


def test_갱신_실패는_예외로_올린다(monkeypatch):
    _seed(expires_in=60)
    monkeypatch.setattr(kt.requests, "post",
                        lambda *a, **k: _Resp(400, text="invalid_grant"))
    with pytest.raises(kt.KakaoTokenError, match="400"):
        kt.get_access_token()


def test_인가코드_교환시_refresh_token_없으면_거부(monkeypatch):
    """동의항목(talk_message)을 안 켜면 여기서 걸린다 — 조용히 넘기면 안 된다."""
    monkeypatch.setattr(kt.requests, "post", lambda *a, **k: _Resp(
        200, {"access_token": "a", "expires_in": 21600}))
    with pytest.raises(kt.KakaoTokenError, match="talk_message"):
        kt.exchange_code("CODE")


def test_인가코드_교환_성공시_저장된다(monkeypatch):
    monkeypatch.setattr(kt.requests, "post", lambda *a, **k: _Resp(200, {
        "access_token": "A", "refresh_token": "R", "expires_in": 21600,
        "refresh_token_expires_in": 5184000}))
    kt.exchange_code("CODE")
    saved = json.load(open(kt._TOKEN_PATH, encoding="utf-8"))
    assert saved["access_token"] == "A" and saved["refresh_token"] == "R"


def test_손상된_토큰파일은_환경변수로_폴백(monkeypatch):
    with open(kt._TOKEN_PATH, "w", encoding="utf-8") as f:
        f.write("{깨진")
    monkeypatch.setenv("KAKAO_REFRESH_TOKEN", "SEED")
    assert kt._load()["refresh_token"] == "SEED"


def test_authorize_url_에_동의항목이_들어간다():
    url = kt.authorize_url()
    assert "talk_message" in url and "restkey" in url and "response_type=code" in url


def test_status_는_설정_공백을_드러낸다():
    st = kt.status()
    assert st["rest_key_set"] is True
    assert st["refresh_token_set"] is False       # 아직 로그인 전
    assert st["access_token_cached"] is False


# ──────────────────────────────────────────────────────────────
# 발송 — 실패 사유를 삼키지 않는다
# ──────────────────────────────────────────────────────────────
def test_실패하면_사유를_돌려준다(monkeypatch):
    """「서버 로그를 확인하세요」는 사장님께 쓸모없다 — 원문이 화면까지 가야 한다."""
    import shared.notifier as sn

    _seed(expires_in=21600)
    monkeypatch.setattr(sn.requests, "post", lambda *a, **k: _Resp(
        403, text='{"msg":"insufficient scopes.","code":-402}'))

    res = sn.send_kakao_memo_detailed("본문")
    assert res["ok"] is False
    assert res["status"] == 403
    assert "insufficient scopes" in res["error"]


def test_링크_거부되면_링크만_빼고_다시_보낸다(monkeypatch):
    """등록 안 된 도메인 링크 때문에 보고 자체가 안 나가면 본말전도다."""
    import shared.notifier as sn

    _seed(expires_in=21600)
    seen = []

    def _post(url, headers=None, data=None, timeout=None):
        seen.append(data["template_object"])
        return _Resp(200) if '"link": {}' in data["template_object"] \
            else _Resp(400, text='{"msg":"invalid link","code":-2}')

    monkeypatch.setattr(sn.requests, "post", _post)
    res = sn.send_kakao_memo_detailed("본문", link_url="https://www.notion.so/x",
                                      button_title="노션에서 보기")
    assert res["ok"] is True
    assert res["dropped_link"] is True
    assert len(seen) == 2                     # 링크 붙여 1회 → 빼고 1회


def test_성공하면_재시도하지_않는다(monkeypatch):
    import shared.notifier as sn

    _seed(expires_in=21600)
    calls = []
    monkeypatch.setattr(sn.requests, "post",
                        lambda *a, **k: calls.append(1) or _Resp(200))
    assert sn.send_kakao_memo("본문", link_url="https://x.com") is True
    assert len(calls) == 1
