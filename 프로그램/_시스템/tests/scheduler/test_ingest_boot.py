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
