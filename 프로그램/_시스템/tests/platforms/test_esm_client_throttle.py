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
