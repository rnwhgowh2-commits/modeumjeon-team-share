# -*- coding: utf-8 -*-
"""ESM 주문조회 5초/1회 — 스로틀은 '계정' 단위여야 한다(클라이언트 인스턴스 아님).

백필이 창마다 새 클라이언트를 만들자 창 사이 간격 0 → ResultCode 3000 연발
(2026-07-22 재백필 실측: G마켓 30창 실패). 같은 계정이면 인스턴스가 달라도
직전 호출 시각을 공유해야 한다.
"""
import time

from shared.platforms.esm.client import EsmClient


def _cfg(interval=0.3):
    return {"master_id": "M1", "secret_key": "S", "site_id": "2", "seller_id": "SEL",
            "order_min_interval_sec": interval, "max_retries": 1,
            "paths": {"orders": "/x"}}


def test_같은_계정이면_새_인스턴스도_간격을_지킨다(monkeypatch):
    calls = []

    class _Resp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"ResultCode": 0, "Data": {}}

    import requests
    monkeypatch.setattr(requests, "post",
                        lambda *a, **k: calls.append(time.monotonic()) or _Resp())
    monkeypatch.setattr(EsmClient, "_headers", lambda self: {})
    EsmClient(_cfg()).post("/x", {}, is_order=True)
    EsmClient(_cfg()).post("/x", {}, is_order=True)   # 새 인스턴스, 같은 계정
    assert len(calls) == 2
    assert calls[1] - calls[0] >= 0.28, "새 인스턴스가 간격을 무시하면 3000이 난다"


def test_다른_계정은_기다리지_않는다(monkeypatch):
    calls = []

    class _Resp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"ResultCode": 0, "Data": {}}

    import requests
    monkeypatch.setattr(requests, "post",
                        lambda *a, **k: calls.append(time.monotonic()) or _Resp())
    monkeypatch.setattr(EsmClient, "_headers", lambda self: {})
    EsmClient(_cfg(interval=5)).post("/x", {}, is_order=True)
    other = _cfg(interval=5); other["seller_id"] = "OTHER"
    t0 = time.monotonic()
    EsmClient(other).post("/x", {}, is_order=True)
    assert time.monotonic() - t0 < 1.0, "계정이 다르면 병렬 안전(기존 규약 유지)"


def test_동시_두_스레드도_간격을_지킨다(monkeypatch):
    """스로틀 경쟁 — 두 스레드가 동시에 들어오면 하나는 기다려야 한다.

    기존 코드는 '응답을 받은 뒤' 시각을 기록해서, 첫 호출이 끝나기 전에 들어온
    두 번째 스레드가 간격 0 으로 통과했다(주문화면·배송검사·자동전환이 같은 계정을
    동시에 부르는 실사례 → ResultCode 3000). 발사 시점에 자리를 예약해야 한다.
    """
    import threading
    calls = []

    class _Resp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self):
            time.sleep(0.15)          # 응답이 오래 걸리는 동안 두 번째 스레드가 진입
            return {"ResultCode": 0, "Data": {}}

    import requests
    monkeypatch.setattr(requests, "post",
                        lambda *a, **k: calls.append(time.monotonic()) or _Resp())
    monkeypatch.setattr(EsmClient, "_headers", lambda self: {})
    ts = [threading.Thread(target=lambda: EsmClient(_cfg()).post("/x", {}, is_order=True))
          for _ in range(2)]
    for t in ts: t.start()
    for t in ts: t.join()
    assert len(calls) == 2
    assert abs(calls[1] - calls[0]) >= 0.28, "동시 진입 스레드가 간격을 무시하면 3000이 난다"


def test_호출제한_3000은_재시도후_성공한다(monkeypatch):
    """ESM 이 HTTP 200 + ResultCode 3000(호출 제한)을 주면 기다렸다 재시도한다.

    다른 프로세스(gunicorn 워커)·자동전환과 겹쳐 3000 이 나는 건 일시 현상 —
    즉시 실패로 굳히면 그 계정만 화면에서 통째로 빠진다(간헐 실패의 원인).
    """
    n = {"i": 0}

    class _Resp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self):
            n["i"] += 1
            if n["i"] == 1:
                return {"ResultCode": 3000, "Message": "호출 제한"}
            return {"ResultCode": 0, "Data": {"ok": True}}

    import requests
    monkeypatch.setattr(requests, "post", lambda *a, **k: _Resp())
    monkeypatch.setattr(EsmClient, "_headers", lambda self: {})
    monkeypatch.setattr(time, "sleep", lambda s: None)   # 대기 생략(단위테스트 속도)
    cfg = _cfg(); cfg["max_retries"] = 3
    out = EsmClient(cfg).post("/x", {}, is_order=True)
    assert out.get("ResultCode") == 0
    assert n["i"] == 2, "3000 을 받고 재시도하지 않으면 계정이 화면에서 빠진다"


def test_호출제한_3000이_계속되면_예외로_전파(monkeypatch):
    class _Resp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"ResultCode": 3000, "Message": "호출 제한"}

    import requests
    import pytest
    monkeypatch.setattr(requests, "post", lambda *a, **k: _Resp())
    monkeypatch.setattr(EsmClient, "_headers", lambda self: {})
    monkeypatch.setattr(time, "sleep", lambda s: None)
    cfg = _cfg(); cfg["max_retries"] = 2
    with pytest.raises(RuntimeError, match="3000"):
        EsmClient(cfg).post("/x", {}, is_order=True)
