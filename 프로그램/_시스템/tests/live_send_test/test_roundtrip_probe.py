# -*- coding: utf-8 -*-
"""축 조회 프로브 — **읽기 전용**. 「이 마켓이 5축 중 무엇을 실제로 주는가」를 실호출로 확인.

왜 필요한가:
    롯데온 상세조회는 지도에 필드가 10개뿐이고 `res.note = "전체 스펙 롯데ON apiNo=94"`
    (미확보)다. 상세 HTML·이미지가 응답에 있는지 **문서로는 알 수 없다**.
    추측해서 어댑터를 짜면 「없는 필드를 읽어 None → 확인불가」로 조용히 굳는다.
    consult-market-map §3(갭 선순환) 절차: 실호출로 확보 → 지도에 되채움.

안전: GET/조회만 한다. 잠금(arm·서버키) 없이 되지만 **마켓에 아무것도 쓰지 않는다.**
"""
import pytest


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("DISABLE_AUTH", "1")
    monkeypatch.delenv("MOUM_LIVE_UPLOAD", raising=False)
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config["TESTING"] = True
    return flask_app.test_client()


def test_상품번호가_없으면_거부한다(client):
    r = client.get("/api/live-send-test/roundtrip-probe?market=lotteon")

    assert r.status_code == 400
    assert "상품번호" in (r.get_json().get("error") or "")


def test_어느_마켓이든_받는다_지원마켓이_아니어도(client):
    """프로브는 「아직 어댑터가 없는 마켓」을 조사하려고 만든 것이다 —
    지원 마켓만 받으면 쓸모가 없다."""
    r = client.get("/api/live-send-test/roundtrip-probe"
                   "?market=lotteon&product_id=1&env_prefix=LOTTEON_MAIN")

    assert r.status_code == 200
    body = r.get_json()
    assert body.get("market") == "lotteon"
    assert "axes" in body or "error" in body


def test_모르는_마켓은_거부한다(client):
    r = client.get("/api/live-send-test/roundtrip-probe"
                   "?market=없는마켓&product_id=1")

    assert r.status_code == 400


def test_응답에_원본_열쇠목록을_담는다(client):
    """어떤 필드가 오는지 이름만이라도 봐야 지도에 되채울 수 있다."""
    r = client.get("/api/live-send-test/roundtrip-probe"
                   "?market=eleven11&product_id=1&env_prefix=ELEVEN11_MAIN")

    body = r.get_json()
    assert "raw_keys" in body or "error" in body
