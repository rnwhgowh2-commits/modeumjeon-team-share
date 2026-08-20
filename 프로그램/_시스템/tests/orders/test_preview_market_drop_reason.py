# -*- coding: utf-8 -*-
"""마켓을 지정했는데 「선택된 마켓이 없어요」로 튕기던 것 — 사유를 말하게 한다.

라이브 실측(2026-08-12): `/orders/preview.json?market=auction` 이 간헐적으로
`{"ok":false,"error":"선택된 마켓이 없어요."}` 400 을 냈다. 마켓을 분명히 지정했는데도.
화면에는 「불러오지 못했어요」만 떠서 무엇을 손봐야 하는지 알 수 없었다.

「아무 마켓도 안 골랐다」와 「고른 마켓이 아직 안 열렸다」는 완전히 다른 말이다.
"""
import pytest

from lemouton.markets import order_export as oe


@pytest.fixture
def client(monkeypatch):
    from app import create_app
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def _get(client, url):
    r = client.get(url)
    return r.status_code, (r.get_json() or {})


def test_안_열린_마켓을_고르면_그_마켓_이름을_말한다(client, monkeypatch):
    monkeypatch.setattr(oe, "supported_markets", lambda: {"smartstore"})
    code, body = _get(client, '/orders/preview.json?market=auction')
    assert code == 400
    assert "옥션" in (body.get("error") or ""), \
        "어느 마켓이 막혔는지 안 말함: %s" % body.get("error")
    assert "선택된 마켓이 없어요" != (body.get("error") or ""), "옛 뭉뚱그린 문구 그대로"


def test_정말_아무것도_안_골랐으면_옛_문구_그대로다(client, monkeypatch):
    """빈 값은 기본 마켓으로 떨어지므로, 「고른 게 없다」는 쉼표만 준 경우다.
    이때는 걸러진 이름이 없으니 옛 문구가 맞다 — 두 경우를 갈라 말하는 게 핵심."""
    monkeypatch.setattr(oe, "supported_markets", lambda: {"smartstore"})
    code, body = _get(client, '/orders/preview.json?markets=,')
    assert code == 400
    assert body.get("error") == "선택된 마켓이 없어요."
    assert not body.get("dropped")


def test_열린_마켓은_400이_아니다(client, monkeypatch):
    monkeypatch.setattr(oe, "supported_markets", lambda: {"auction"})
    monkeypatch.setattr(oe, "new_order_rows",
                        lambda *a, **k: [])
    code, body = _get(client, '/orders/preview.json?market=auction')
    assert code == 200 and body.get("ok") is True
