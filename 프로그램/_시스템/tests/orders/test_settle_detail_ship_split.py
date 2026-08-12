# -*- coding: utf-8 -*-
"""정산예정금액 드릴다운의 「상품정산 / 배송비정산」 쪼개기 — 실값 기준.

🔴 왜 (2026-08-13): N열(`정산예정금(배송비포함)`)이 마켓 실값(`_ship_settle`)을 쓰게
   바뀌었다. 그런데 드릴다운은 여전히 **고객배송비**로 쪼개고 있었다:
     상품정산예정 = N − 고객배송비 = (M + 3,868) − 4,000 = M − 132   ← 상품분이 132 모자람
     배송비정산예정 = 고객배송비 4,000                                ← 실제 받는 건 3,868
   합계(총정산예정)는 맞는데 **두 칸이 다 틀린다.** 이 화면은 사장님이 마켓 정산 화면과
   한 건씩 맞대 보는 자리라, 여기가 틀리면 대조 자체가 못 쓰게 된다.
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


def _line(**row_extra):
    row = {"주문상태": "구매확정", "정산예정금(배송비포함)": 117792,
           "정산예정금액": 113924, "_settle_source": "real",
           "주문일": "2026-08-01 10:00", "정산예정일": "2099-08-20",
           "오픈마켓주문번호": "1100194049219", "상품명": "가방", "옵션": "블랙",
           "수량": 1, "배송비": 4000}
    row.update(row_extra)
    return {"row": row, "market": "coupang", "account": "계정A",
            "status_at": _dt.datetime(2026, 8, 1, 12, 0)}


def _patch(monkeypatch, lines):
    monkeypatch.setattr(om, "_settle_plan_lines", lambda markets=None: [
        ln for ln in lines if not markets or ln["market"] in markets])


def test_실값이_있으면_그_값으로_쪼갠다(client, monkeypatch):
    _patch(monkeypatch, [_line(_ship_settle=3868)])
    r = client.get("/orders/api/settle-plan/detail?category=confirmed&market=coupang")
    assert r.status_code == 200
    row = r.get_json()["rows"][0]
    assert row["배송비정산예정"] == 3868          # 고객배송비 4,000 이 아니다
    assert row["상품정산예정"] == 113924          # M 그대로 (113,792 아님)
    assert row["총정산예정"] == 117792
    # 두 칸의 합이 총액과 어긋나면 화면에서 바로 들킨다 — 그 불변식을 못 박는다
    assert row["상품정산예정"] + row["배송비정산예정"] == row["총정산예정"]


def test_실값이_없으면_고객배송비로_쪼갠다(client, monkeypatch):
    """실값을 안 주는 마켓(롯데온·11번가·ESM)은 예전 그대로."""
    _patch(monkeypatch, [_line(**{"정산예정금(배송비포함)": 117924})])
    r = client.get("/orders/api/settle-plan/detail?category=confirmed&market=coupang")
    row = r.get_json()["rows"][0]
    assert row["배송비정산예정"] == 4000
    assert row["상품정산예정"] == 113924
    assert row["상품정산예정"] + row["배송비정산예정"] == row["총정산예정"]


def test_orders_필터는_그_주문만_준다(client, monkeypatch):
    """🔴 마켓 명세와 주문 단위로 맞대는 창구 — 부류를 안 줘도 되고 2,000행 상한에 안 걸린다.

    라이브 실측(2026-08-13): 쿠팡은 `paid` 한 부류만으로 상한 2,000행에 걸려 잘렸다.
    부류로 훑는 대조는 그래서 전수가 될 수 없다.
    """
    _patch(monkeypatch, [
        _line(_ship_settle=3868),
        _line(**{"오픈마켓주문번호": "다른주문"}),
    ])
    r = client.get("/orders/api/settle-plan/detail"
                   "?market=coupang&orders=1100194049219,없는번호")
    d = r.get_json()
    assert [x["주문번호"] for x in d["rows"]] == ["1100194049219"]
    assert d["못찾은주문"] == ["없는번호"]     # 못 준 것을 숨기지 않는다
    assert d["요청주문수"] == 2 and d["찾은주문수"] == 1


def test_실값_0도_0으로_쪼갠다(client, monkeypatch):
    """무료배송이라 배송비 정산이 0 이면 0 — 고객배송비로 메우지 않는다."""
    _patch(monkeypatch, [_line(_ship_settle=0,
                               **{"정산예정금(배송비포함)": 113924})])
    r = client.get("/orders/api/settle-plan/detail?category=confirmed&market=coupang")
    row = r.get_json()["rows"][0]
    assert row["배송비정산예정"] == 0
    assert row["상품정산예정"] == 113924
