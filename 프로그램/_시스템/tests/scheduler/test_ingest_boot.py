# -*- coding: utf-8 -*-
"""증분 수집 첫 실행 시점 — 부팅 직후에 잡혀야 한다.

interval 잡은 '부팅 후 6시간'에 처음 돈다. 배포가 잦은 날은 매 배포가 타이머를
리셋해 증분이 거의 안 돌았다(2026-07-21 실측: 옥션 8일 공백·G마켓 최근 12건 누락).
"""


def test_증분수집은_부팅_직후_첫_실행이_잡힌다(monkeypatch):
    import scheduler.main as SM
    captured = {}

    class FakeSched:
        running = True

        def get_job(self, jid):
            return None

        def add_job(self, *a, **k):
            captured[k.get("id")] = k

        def start(self):
            pass

    monkeypatch.setattr(SM, "get_scheduler", lambda: FakeSched())
    SM.start_order_ingest_scheduler()
    assert "order_ingest" in captured
    nrt = captured["order_ingest"].get("next_run_time")
    assert nrt is not None, "첫 실행이 '부팅+6시간'이면 잦은 배포에 증분이 영영 안 돈다"


def test_고속틱이_등록된다_비ESM_20분(monkeypatch):
    """취소요청→완료가 6시간 틱 사이에 끝나면 구매자 정보를 영영 못 잡는다
    (2026-07-22 실측: 롯데온 취소완료 93건 중 17건 = 그 구멍). 고속 틱(기본 20분,
    1일 창, 비ESM)이 취소요청 단계에서 낚아챈다. ESM 은 5초/1콜 제한이라 제외."""
    import scheduler.main as SM
    captured = {}

    class FakeSched:
        running = True

        def get_job(self, jid):
            return None

        def add_job(self, *a, **k):
            captured[k.get("id")] = k

        def start(self):
            pass

    monkeypatch.setattr(SM, "get_scheduler", lambda: FakeSched())
    SM.start_order_ingest_scheduler()
    assert "order_ingest_fast" in captured
    assert captured["order_ingest_fast"].get("minutes") == 20


def test_고속틱은_ESM을_뺀_마켓만_돈다(monkeypatch):
    import scheduler.main as SM
    called = {}

    def fake_ingest(markets, days):
        called["markets"] = list(markets)
        called["days"] = days
        return []

    monkeypatch.setattr("lemouton.markets.order_ingest.ingest_recent", fake_ingest)
    monkeypatch.setattr("lemouton.markets.order_export.supported_markets",
                        lambda: ["lotteon", "coupang", "auction", "gmarket",
                                 "smartstore", "eleven11"])
    SM._order_ingest_tick_fast()
    assert "auction" not in called["markets"] and "gmarket" not in called["markets"]
    assert "lotteon" in called["markets"]
    assert called["days"] == 1
