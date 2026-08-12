# -*- coding: utf-8 -*-
"""쿠팡 `orders=` 정산 진단 라우트 — 배송비 실값을 눈으로 대조하는 창구.

왜 이 시험이 있나: 이 라우트는 **판정의 증거를 만드는 도구**다. 조용히 0건이 나오면
「배송비 정산이 0원」과 「진단이 안 돈다」가 같은 얼굴이 된다(가장 위험한 실패).
"""
import datetime as _dt
import pathlib

import pytest

import webapp.routes.orders as om


@pytest.fixture
def client():
    from flask import Flask
    app = Flask(__name__, template_folder="webapp/templates",
                root_path=pathlib.Path(om.__file__).parents[2].as_posix())
    app.register_blueprint(om.bp)
    return app.test_client()


def _patch(monkeypatch, pages):
    """revenue-history 응답을 창 구분 없이 pages 그대로 준다."""
    monkeypatch.setattr(om, "_client_for_diag", lambda market, alias: object())
    calls = {"n": 0}

    def fake_page(rec_from, rec_to, token="", max_per_page=50, client=None):
        calls["n"] += 1
        return pages[0] if calls["n"] == 1 else {"data": [], "hasNext": False}

    import shared.platforms.coupang.settlements as cs
    monkeypatch.setattr(cs, "fetch_revenue_page", fake_page)
    return calls


_ORDER = {
    "orderId": "1100194049219", "saleType": "SALE",
    "recognitionDate": "2026-07-20", "settlementDate": "2026-08-14",
    "deliveryFee": {"settlementAmount": 3868},      # ← 고객배송비 4,000 − 수수료 132
    "items": [{"vendorItemId": "V1", "settlementAmount": 113924}],
}


def test_주문번호로_배송비_실값을_보여준다(client, monkeypatch):
    """🔴 ① 판정의 결정적 증거 — 엑셀 <기본배송료> 정산금액 3,868 과 같은 값이 오나."""
    _patch(monkeypatch, [{"data": [_ORDER], "hasNext": False}])
    r = client.get("/orders/diag/coupang-order-settle"
                   "?from=2026-07-01&to=2026-07-31&orders=1100194049219")
    assert r.status_code == 200
    d = r.get_json()
    ent = d["주문별"]["1100194049219"]
    assert ent["배송비정산"] == 3868          # 4,000 이 아니다
    assert ent["상품정산합"] == 113924
    assert ent["총정산"] == 117792
    assert d["못찾은주문"] == []


def test_환불은_부호가_갈린다(client, monkeypatch):
    """items 는 양수로 오고 deliveryFee 는 이미 음수 — 빌더와 같은 규칙이어야 한다."""
    refund = dict(_ORDER, saleType="REFUND",
                  deliveryFee={"settlementAmount": -3868},
                  items=[{"vendorItemId": "V1", "settlementAmount": 113924}])
    _patch(monkeypatch, [{"data": [refund], "hasNext": False}])
    r = client.get("/orders/diag/coupang-order-settle"
                   "?from=2026-07-01&to=2026-07-31&orders=1100194049219")
    ent = r.get_json()["주문별"]["1100194049219"]
    assert ent["상품정산합"] == -113924       # REFUND → 차감
    assert ent["배송비정산"] == -3868         # 이미 음수 → 그대로


def test_못찾은_주문을_숨기지_않는다(client, monkeypatch):
    """② 「우리에 없는 31건」의 출발점 — 안 나온 주문번호를 그대로 돌려줘야 한다."""
    _patch(monkeypatch, [{"data": [_ORDER], "hasNext": False}])
    r = client.get("/orders/diag/coupang-order-settle"
                   "?from=2026-07-01&to=2026-07-31&orders=1100194049219,없는번호")
    d = r.get_json()
    assert d["못찾은주문"] == ["없는번호"]
    assert d["찾은주문수"] == 1


def test_조회창은_25일로_쪼갠다(client, monkeypatch):
    """revenue-history 는 「1개월 미만」 제약 — 30일 창이면 매 요청 HTTP 400 이었다."""
    calls = _patch(monkeypatch, [{"data": [], "hasNext": False}])
    r = client.get("/orders/diag/coupang-order-settle?from=2026-06-01&to=2026-07-31")
    assert r.status_code == 200
    assert calls["n"] >= 3          # 61일 → 25일 창 3개

def test_from_to_없으면_400(client, monkeypatch):
    monkeypatch.setattr(om, "_client_for_diag", lambda market, alias: object())
    assert client.get("/orders/diag/coupang-order-settle").status_code == 400
