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


def test_서버키_판정은_시스템_정본과_같아야_한다(client, monkeypatch):
    """다른 경로는 live_upload_enabled() 로 'true'·'yes' 도 켜짐으로 본다.
    이 라우트만 '1' 만 인정하면, 서버가 무장됐는데 여기만 거부해 「왜 안 되지」로 헤맨다."""
    monkeypatch.setenv("MOUM_LIVE_UPLOAD", "true")

    r = client.post("/api/live-send-test/roundtrip",
                    json={"market": "smartstore", "origin_product_no": 1, "arm": "1"})

    body = r.get_json()
    assert "MOUM_LIVE_UPLOAD" not in (body.get("refusal") or ""), \
        "시스템은 무장인데 이 라우트만 서버키가 꺼졌다고 본다"


def test_지원하지_않는_마켓은_이유를_밝히고_거부한다(client, monkeypatch):
    """「지원 안 함」만 말하면 사장님은 왜인지 모른다 — 지도 근거를 그대로 말한다."""
    monkeypatch.setenv("MOUM_LIVE_UPLOAD", "1")

    r = client.post("/api/live-send-test/roundtrip",
                    json={"market": "coupang", "origin_product_no": 1, "arm": "1"})

    body = r.get_json()
    assert body["ok"] is False
    assert "쿠팡" in (body.get("refusal") or "")
    assert "승인" in (body.get("refusal") or ""), "왜 못 하는지가 없다"


def test_옥션과_G마켓은_지원_마켓이다(client):
    """서버키가 꺼져 있어도 「미지원 마켓」이 아니라 「서버키 꺼짐」으로 거부돼야 한다."""
    for mk in ("auction", "gmarket"):
        r = client.post("/api/live-send-test/roundtrip",
                        json={"market": mk, "origin_product_no": 1, "arm": "1"})
        refusal = r.get_json().get("refusal") or ""
        assert "MOUM_LIVE_UPLOAD" in refusal, f"{mk} 가 미지원으로 막혔다: {refusal}"


def test_상품번호가_없으면_거부한다(client, monkeypatch):
    monkeypatch.setenv("MOUM_LIVE_UPLOAD", "1")

    r = client.post("/api/live-send-test/roundtrip",
                    json={"market": "smartstore", "arm": "1"})

    body = r.get_json()
    assert body["ok"] is False
    assert "상품번호" in (body.get("refusal") or "")


def test_후보조회는_계정을_env_prefix_로_지정할_수_있다(client):
    """UploadAccount.account_key 는 표시명과 달라 화면에서 알 수 없다.
    env_prefix(SMARTSTORE_2 등)는 계정 목록 API 가 그대로 주므로 그걸로 지정한다."""
    r = client.get("/api/live-send-test/roundtrip-candidates"
                   "?market=smartstore&env_prefix=SMARTSTORE_2")

    body = r.get_json()
    # 키가 없어 조회 자체는 실패해도, **어느 계정을 쓰려 했는지**는 되돌려줘야 한다
    assert body.get("env_prefix") == "SMARTSTORE_2"


def test_전계정_스캔은_계정별로_따로_보고한다(client):
    """한 계정에 판매중지 상품이 없을 수 있다 — 전 계정을 훑되 계정을 섞지 않는다."""
    r = client.get("/api/live-send-test/roundtrip-candidates?market=smartstore&all=1")

    body = r.get_json()
    assert isinstance(body.get("accounts"), list)
    for row in body["accounts"]:
        assert "env_prefix" in row


def test_후보조회는_읽기전용이라_잠금없이_된다(client):
    """판매중지 후보 찾기는 GET 만 한다 — 마켓에 아무것도 안 쓴다."""
    r = client.get("/api/live-send-test/roundtrip-candidates?market=smartstore")

    assert r.status_code == 200
    body = r.get_json()
    assert "candidates" in body or "error" in body
