# -*- coding: utf-8 -*-
"""직접 값 지정 테스트 라우트 — /current(현재값 읽기) · /send-explicit(명시값 전송).

서버키 OFF 불변식: send-explicit 는 use_real False(드라이런), 실제 마켓 호출 0.
price_guard(0원) 차단, 미매칭 옵션 정직 실패. 네트워크 실호출 없음(존재하지 않는
구성/옵션이라 fetch·전송 모두 로컬 경로로만 검증).
"""
import pytest


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("DISABLE_AUTH", "1")
    monkeypatch.delenv("MOUM_LIVE_UPLOAD", raising=False)   # 서버키 확실히 OFF
    import app as appmod
    flask_app = appmod.create_app()
    flask_app.config["TESTING"] = True
    return flask_app.test_client()


def test_current_requires_params(client):
    r = client.get("/api/live-send-test/current")
    assert r.status_code == 400


def test_current_unknown_set_no_channel(client):
    """없는 구성 → 채널 없음(404). 마켓 실호출 없이 안전 표면화."""
    r = client.get("/api/live-send-test/current?set_id=999999&market=smartstore")
    assert r.status_code == 404
    body = r.get_json()
    assert body["ok"] is False


def test_send_explicit_requires_fields(client):
    r = client.post("/api/live-send-test/send-explicit",
                    json={"set_id": 1, "market": "smartstore"})
    assert r.status_code == 400


def test_send_explicit_unknown_channel(client):
    """없는 구성/상품번호 → 404. 실제 전송 없음."""
    r = client.post("/api/live-send-test/send-explicit",
                    json={"set_id": 999999, "market": "smartstore",
                          "market_option_id": "opt1", "price": 10000,
                          "stock": 5, "confirmed": True})
    assert r.status_code == 404
    body = r.get_json()
    assert body["ok"] is False


@pytest.fixture
def seeded_client(monkeypatch):
    """매칭된 채널·옵션이 있는 in-memory DB 를 라우트에 주입(dev DB 오염 없음).

    라우트 모듈의 SessionLocal 만 in-memory 로 바꿔치기 — run_explicit 는 주입된
    세션을 그대로 쓰고 select_adapters(live=False)=DryRunAdapter 라 네트워크 실호출 0.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from shared.db import Base
    from lemouton.sets.models import ProductSet, SetChannel, SetChannelOption

    monkeypatch.setenv("DISABLE_AUTH", "1")
    monkeypatch.delenv("MOUM_LIVE_UPLOAD", raising=False)   # 서버키 OFF

    eng = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(eng)
    TestSession = sessionmaker(bind=eng, future=True, expire_on_commit=False)
    seed = TestSession()
    seed.add_all([
        ProductSet(id=1, model_code="M1", name="세트1"),
        SetChannel(id=5, set_id=1, market="smartstore",
                   account_key="default", market_product_id="P1"),
        SetChannelOption(channel_id=5, canonical_sku="SKU_A",
                         market_option_id="opt1", status="matched"),
    ])
    seed.commit()
    seed.close()

    import app as appmod
    import webapp.routes.live_send_test as route_mod
    monkeypatch.setattr(route_mod, "SessionLocal", TestSession)
    flask_app = appmod.create_app()
    flask_app.config["TESTING"] = True
    return flask_app.test_client()


def test_send_explicit_dryrun_when_server_key_off(seeded_client):
    """매칭 옵션 + 서버키 OFF → use_real False(드라이런), 실전송 0. price_error 없음."""
    r = seeded_client.post("/api/live-send-test/send-explicit",
                           json={"set_id": 1, "market": "smartstore",
                                 "market_option_id": "opt1", "price": 15000,
                                 "stock": 9, "confirmed": True})
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    assert body["use_real"] is False        # 서버키 OFF → 드라이런
    assert body["price_error"] is None
    # 서버키 off 라 거부사유(MOUM_LIVE_UPLOAD) 표면화
    assert body["refusal"] and "MOUM_LIVE_UPLOAD" in body["refusal"]
    # 드라이런 어댑터로 '전송'(외부 호출 없음) — force 로 신규 등록도 전송 대상
    assert body["result"]["uploaded"] == 1
    assert body["result"]["failed"] == 0


def test_send_explicit_price_guard_blocks_zero(seeded_client):
    """0원 → price_guard 차단(price_error), 전송 result 없음."""
    r = seeded_client.post("/api/live-send-test/send-explicit",
                           json={"set_id": 1, "market": "smartstore",
                                 "market_option_id": "opt1", "price": 0,
                                 "stock": 9, "confirmed": True})
    assert r.status_code == 200
    body = r.get_json()
    assert body["price_error"]
    assert body["result"] is None
