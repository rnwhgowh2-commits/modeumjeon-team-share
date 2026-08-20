# -*- coding: utf-8 -*-
"""무거운 3축(상품명·상세·이미지) 잠금 — 조사에서 드러난 구멍 3개를 막는다.

[2026-08-13 전수 조사] 「옥션·G마켓만 막으면 된다」고 봤는데 아니었다.

🔴 구멍 ① 쿠팡 3축에 **잠금이 아예 없다.**
   게다가 쿠팡 apply 는 3축을 보낼 때 **전송 시작 시점에 뜬 낡은 사본**을 그대로 실어
   보낸다(markets/coupang.py — detail 을 먼저 뜨고, 가격·재고를 바꾼 뒤, 그 낡은
   body 를 보낸다). 승인이 나는 순간 **가격·재고가 옛 값으로 되감긴다.**
   이 프로젝트 1원칙(가격·재고 오류 = 금전 손실) 정면 위반이라 막는다.

🔴 구멍 ② **손복구 경로엔 잠금이 없다.**
   전송(roundtrip)만 막고 되돌리기(roundtrip-restore)를 안 막았다. 되돌리려다
   2026-08-07 에 상품을 잠근 그 전송이 그대로 나간다.

🔴 구멍 ③ **판매중 상품 + 무거운 3축**을 동시에 막는 코드가 없다.
   사장님이 판매중 상품에 허락하신 것은 가격 +100원·재고 +1 뿐이다(2026-08-07).
   상품명·상세·사진은 손님과 검색 목록에 그대로 보인다.
"""
from __future__ import annotations

import pytest

from webapp.routes import live_send_test as R


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("DISABLE_AUTH", "1")
    monkeypatch.delenv("MOUM_LIVE_UPLOAD", raising=False)   # 서버키 OFF 가 기본
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config["TESTING"] = True
    return flask_app.test_client()


@pytest.fixture()
def armed(monkeypatch):
    monkeypatch.setenv("MOUM_LIVE_UPLOAD", "1")


# ── ① 쿠팡 3축 ───────────────────────────────────────────────────────────────
def test_쿠팡_무거운축은_거부한다(client, armed):
    """3축 전송이 **가격·재고를 되감는다** — 돈이 걸린 문제라 막는다."""
    r = client.post("/api/live-send-test/roundtrip",
                    json={"market": "coupang", "origin_product_no": 1, "arm": "1",
                          "axes": ["detail_html"]})

    body = r.get_json()
    assert body["ok"] is False
    assert "가격" in (body.get("refusal") or ""), \
        f"왜 막는지(가격·재고 되감김)를 안 말한다: {body.get('refusal')}"


def test_쿠팡_축을_안_주면_5축이라_막힌다(client, armed):
    """🔴 축 미지정 = 5축 전부 = 무거운 축 포함. 기본값이 위험한 쪽으로 열리면 안 된다."""
    r = client.post("/api/live-send-test/roundtrip",
                    json={"market": "coupang", "origin_product_no": 1, "arm": "1"})

    assert r.get_json()["ok"] is False


def test_쿠팡_가격재고는_계속_열려_있다(client):
    """라이브로 왕복 성공한 축까지 막으면 안 된다(2026-08-12 실측)."""
    r = client.post("/api/live-send-test/roundtrip",
                    json={"market": "coupang", "origin_product_no": 1, "arm": "1",
                          "axes": ["sale_price", "stock"]})

    assert "MOUM_LIVE_UPLOAD" in (r.get_json().get("refusal") or "")


# ── ② 손복구 경로 ────────────────────────────────────────────────────────────
def test_손복구도_같은_잠금을_받는다():
    """전송만 막고 되돌리기를 안 막으면, 되돌리려다 사고 전송이 그대로 나간다."""
    import inspect
    src = inspect.getsource(R.api_roundtrip_restore)

    assert "_heavy_axis_refusal" in src, \
        "손복구 경로에 무거운 축 잠금이 없다 — 2026-08-07 사고 전송이 그대로 나간다"


# ── ③ 판매중 + 무거운 축 ─────────────────────────────────────────────────────
def test_판매중_허용과_무거운축을_같이_켤_수_없다(client, armed):
    """사장님이 판매중 상품에 허락한 것은 가격 +100·재고 +1 뿐이다(2026-08-07).

    상품명·상세·사진은 손님과 검색 목록에 그대로 보인다. 몇 초 만에 되돌려도
    검색 목록 사진은 한동안 남는다.
    """
    r = client.post("/api/live-send-test/roundtrip",
                    json={"market": "smartstore", "origin_product_no": 1, "arm": "1",
                          "axes": ["detail_html"], "allow_on_sale": "1"})

    body = r.get_json()
    assert body["ok"] is False
    assert "판매중" in (body.get("refusal") or ""), \
        f"왜 막는지를 안 말한다: {body.get('refusal')}"


def test_판매중지_상품에는_무거운축이_열려_있다(client):
    """판매중지 상품은 손님에게 안 보인다 — 여기서 시험한다(사장님 최초 지시)."""
    r = client.post("/api/live-send-test/roundtrip",
                    json={"market": "smartstore", "origin_product_no": 1, "arm": "1",
                          "axes": ["detail_html"]})

    assert "MOUM_LIVE_UPLOAD" in (r.get_json().get("refusal") or "")
