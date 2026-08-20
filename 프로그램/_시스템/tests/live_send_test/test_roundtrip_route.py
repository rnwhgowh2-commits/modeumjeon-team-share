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


def test_옥션은_무거운_3축만_막고_이유를_밝힌다(client, monkeypatch):
    """[2026-08-12] 차단을 **마켓 단위 → 축 단위**로 좁혔다.

    원인은 마켓이 아니라 **어느 API 를 쓰느냐**였다. 전체 상품수정 PUT 이 재심사를
    불렀고, 가격·재고는 전용 API 라 브랜드 상품도 멀쩡히 왕복한다(라이브 실측).
    상품명·상세·이미지는 전용 API 가 없어 아직 막는다 — 이유를 그대로 말해야 한다.
    """
    monkeypatch.setenv("MOUM_LIVE_UPLOAD", "1")

    r = client.post("/api/live-send-test/roundtrip",
                    json={"market": "auction", "origin_product_no": 1, "arm": "1",
                          "axes": ["sale_price", "detail_html"]})

    body = r.get_json()
    assert body["ok"] is False
    refusal = body.get("refusal") or ""
    assert "재심사" in refusal, "왜 못 하는지가 없다"
    assert body.get("막힌축") == ["detail_html"], f"어느 축인지 안 짚었다: {body}"


def test_옥션_축을_안_주면_5축이라_막는다(client, monkeypatch):
    """기본값이 위험한 쪽으로 열리면 안 된다 — 축 미지정 = 5축 전부 = 무거운 축 포함."""
    monkeypatch.setenv("MOUM_LIVE_UPLOAD", "1")

    r = client.post("/api/live-send-test/roundtrip",
                    json={"market": "gmarket", "origin_product_no": 1, "arm": "1"})

    assert r.get_json()["ok"] is False


def test_옥션_가격재고는_이제_열려_있다(client):
    """전용 API(esm.186·esm.26)로 라이브 왕복 성공 — 더는 마켓 통째로 막지 않는다."""
    r = client.post("/api/live-send-test/roundtrip",
                    json={"market": "auction", "origin_product_no": 1, "arm": "1",
                          "axes": ["sale_price", "stock"]})

    refusal = r.get_json().get("refusal") or ""
    assert "MOUM_LIVE_UPLOAD" in refusal, f"가격·재고가 아직 막혀 있다: {refusal}"


def test_11번가는_이제_지원_마켓이다(client):
    """가격·재고 전용 API 가 우리 코드에 이미 있었다 — 어댑터만 없어서 막혀 있었다.

    🔴 「지도에 상품수정 API 가 없다」는 **5축(상품명·상세·이미지)** 얘기였다.
       한 축이 없다고 마켓 전체를 미지원으로 적으면, 되는 축까지 영영 안 쓴다.
    """
    r = client.post("/api/live-send-test/roundtrip",
                    json={"market": "eleven11", "origin_product_no": 1, "arm": "1"})

    refusal = r.get_json().get("refusal") or ""
    assert "MOUM_LIVE_UPLOAD" in refusal, f"11번가가 미지원으로 막혔다: {refusal}"


def test_스스_쿠팡_롯데온은_지원_마켓이다(client):
    """서버키가 꺼져 있어도 「미지원 마켓」이 아니라 「서버키 꺼짐」으로 거부돼야 한다.

    ⚠️ [2026-08-13] 축을 지정한다 — 축을 안 주면 5축 전부라 무거운 축 잠금에 먼저 걸린다
    (쿠팡 3축은 가격·재고를 되감아서 막았다). 여기서 보려는 건 「마켓 지원 여부」다.
    """
    for mk in ("smartstore", "coupang", "lotteon"):
        r = client.post("/api/live-send-test/roundtrip",
                        json={"market": mk, "origin_product_no": 1, "arm": "1",
                              "axes": ["sale_price", "stock"]})
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


def test_옥션_G마켓은_사고로_차단돼_있다(client, monkeypatch):
    """🔴 [2026-08-07 사고 2건] ESM 상품수정 PUT 자체가 재심사를 유발해 상품이 잠긴다.
    옥션 6390703083(5축) · G마켓 6390711573(**가격 한 축만**) 둘 다 같은 결과 —
    원복도 손복구도 거부돼 되돌릴 수 없는 변경이 남았다.

    원인이 규명되기 전까지 전송을 막는다. 조회(프로브)는 계속 되어야 한다.
    """
    monkeypatch.setenv("MOUM_LIVE_UPLOAD", "1")

    for mk in ("auction", "gmarket"):
        r = client.post("/api/live-send-test/roundtrip",
                        json={"market": mk, "origin_product_no": 1, "arm": "1"})
        body = r.get_json()
        assert body["ok"] is False
        assert body.get("sent") in (0, None), f"{mk} 전송이 나갔다"
        assert "재심사" in (body.get("refusal") or ""), body.get("refusal")


def test_전송이_막힌_마켓도_후보조회는_된다(client):
    """🔴 차단은 **전송**에만 걸어야 한다. 후보조회는 GET 만 해서 마켓에 아무것도
    안 쓴다 — 같이 막으면 원인 진단조차 못 한다(2026-08-07 실제로 막혔다)."""
    for mk in ("auction", "gmarket"):
        r = client.get(f"/api/live-send-test/roundtrip-candidates?market={mk}")
        assert r.status_code == 200, f"{mk} 후보조회가 막혔다"
        body = r.get_json()
        assert "지원하지 않아요" not in str(body.get("error") or "")


def test_막힌_마켓도_명시적으로_풀면_보낸다(client, monkeypatch):
    """차단은 실수 방지용이다 — 원인을 규명하려면 **의도적으로** 풀 수 있어야 한다.
    다만 기본은 계속 막힘(unblock 없이는 전송 0건)."""
    monkeypatch.setenv("MOUM_LIVE_UPLOAD", "1")

    blocked = client.post("/api/live-send-test/roundtrip",
                          json={"market": "auction", "origin_product_no": 1, "arm": "1"})
    assert "재심사" in (blocked.get_json().get("refusal") or "")

    opened = client.post("/api/live-send-test/roundtrip",
                         json={"market": "auction", "origin_product_no": 1,
                               "arm": "1", "unblock": "1"})
    assert "재심사" not in (opened.get_json().get("refusal") or ""), "명시적으로 풀었는데 막혔다"
