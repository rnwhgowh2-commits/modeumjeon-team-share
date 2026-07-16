# -*- coding: utf-8 -*-
"""CS 클레임 라우트 — claims.json/ack/memo."""
import json
import pathlib

import webapp.routes.orders as om


def _make_client():
    from flask import Flask
    app = Flask(__name__, template_folder="webapp/templates",
                root_path=pathlib.Path(om.__file__).parents[2].as_posix())
    app.register_blueprint(om.bp)
    return app.test_client()


def test_claims_json_shape(monkeypatch):
    monkeypatch.setattr("webapp.routes.orders._claim_svc.list_claims",
                        lambda markets, **kw: {"groups": {"신규요청": [{"오픈마켓주문번호": "A", "claim_key": "k"}], "대응필요": [], "대응완료": []},
                                               "market_counts": {"전체": 1}, "warnings": []})
    c = _make_client()
    r = c.get("/orders/cs/claims.json?markets=lotteon&range=today")
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data["ok"] is True and data["groups"]["신규요청"][0]["오픈마켓주문번호"] == "A"


def test_ack_and_memo_post(monkeypatch):
    calls = {}
    monkeypatch.setattr("webapp.routes.orders._claim_svc.acknowledge", lambda ck, **kw: calls.__setitem__("ack", ck))
    monkeypatch.setattr("webapp.routes.orders._claim_svc.save_memo", lambda ck, memo, **kw: calls.__setitem__("memo", (ck, memo)))
    c = _make_client()
    r1 = c.post("/orders/cs/claims/ack", json={"claim_key": "롯데온:LO1:반품", "market": "롯데온", "order_no": "LO1", "claim_type": "반품"})
    r2 = c.post("/orders/cs/claims/memo", json={"claim_key": "롯데온:LO1:반품", "memo": "메모"})
    assert r1.status_code == 200 and calls["ack"] == "롯데온:LO1:반품"
    assert r2.status_code == 200 and calls["memo"] == ("롯데온:LO1:반품", "메모")
