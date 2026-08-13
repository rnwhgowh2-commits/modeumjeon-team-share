# -*- coding: utf-8 -*-
"""옥션·G마켓 조회가 어디서 시간을 쓰는지 재는 창구.

2026-08-13: 클레임 49회를 동시에 보내도록 고쳤는데 오히려 느려 보였다. 그런데
「클레임에 몇 초 썼는지」를 재는 줄이 서버 기록에만 있어, 화면에서는 원인을
가릴 수 없었다. 되돌릴지 유지할지 정하려면 이 숫자가 필요하다.
"""
import pytest


@pytest.fixture
def client():
    from app import create_app
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def test_모르는_마켓은_거절한다(client):
    r = client.get('/orders/diag/esm-timing?market=coupang')
    assert r.status_code == 400
    assert "옥션" in (r.get_json() or {}).get("error", "")


def test_클레임_초와_건수를_돌려준다(client, monkeypatch):
    from lemouton.markets import order_export as oe

    def fake(market, since, until, **kw):
        d = kw.get("diag")
        if d is not None:
            d.setdefault("counts", {})["주문조회"] = 7
            d["counts"]["클레임조회초"] = 3.4
        return [{"판매처": "옥션"}]

    monkeypatch.setattr(oe, "_account_client", lambda m, *a, **k: "가짜클라이언트")
    monkeypatch.setattr(oe, "esm_order_rows", fake)
    r = client.get('/orders/diag/esm-timing?market=auction&days=1')
    assert r.status_code == 200, r.get_data(as_text=True)
    j = r.get_json()
    assert j["ok"] is True
    assert j["counts"]["클레임조회초"] == 3.4, j
    assert j["counts"]["주문조회"] == 7
    assert j["행수"] == 1
    assert isinstance(j["총초"], (int, float)) and j["총초"] >= 0


def test_자격증명을_붙여_부른다(client, monkeypatch):
    """🔴 라이브에서 바로 터진 구멍 — client 를 안 넘겨
    `AttributeError: 'NoneType' object has no attribute 'request_orders'` 가 났다.
    주문 조회는 계정 키로 만든 클라이언트가 있어야 돈다. 창구가 그걸 붙여야 한다."""
    from lemouton.markets import order_export as oe
    본 = {}

    monkeypatch.setattr(oe, "_account_client", lambda m, *a, **k: "가짜클라이언트")

    def fake(market, since, until, **kw):
        본["client"] = kw.get("client")
        return []

    monkeypatch.setattr(oe, "esm_order_rows", fake)
    r = client.get('/orders/diag/esm-timing?market=auction&days=1')
    assert r.status_code == 200, r.get_data(as_text=True)
    assert 본.get("client") == "가짜클라이언트", "클라이언트를 안 넘겼다: %s" % 본


def test_키가_없으면_사유를_말한다(client, monkeypatch):
    """조용히 터지지 말고 무엇이 없는지 말한다."""
    from lemouton.markets import order_export as oe
    monkeypatch.setattr(oe, "_account_client", lambda m, *a, **k: None)
    r = client.get('/orders/diag/esm-timing?market=auction')
    j = r.get_json()
    assert j["ok"] is False
    assert "키" in j["error"] or "자격증명" in j["error"], j
