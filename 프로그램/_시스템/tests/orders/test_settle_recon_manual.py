# -*- coding: utf-8 -*-
"""마켓 화면 합계 직접 입력 대조 (노션 주문관리 ③ — 쿠팡 미구매확정).

🔴 왜 손입력인가(2026-08-13 실측) — 쿠팡 「미구매확정」 상세 엑셀엔 **수수료 열이 없다.**
   판매금액 293,000 + 판매배송비 24,000 = 317,000 만 있고, 우리가 배운 상품별 실요율
   (11.55%)과 배송비 3.3% 로 계산하면 **282,366**. 화면 값 268,840 과 **13,526** 이
   설명되지 않고, 화면은 「5건」인데 엑셀엔 주문이 9건이라 같은 묶음인지도 불확실하다.
   추측으로 계수를 맞추면 대조가 자기 자신을 증명하는 거짓말이 된다.

🔴 이 숫자는 **대조 상대**일 뿐 우리 정산액이 되지 않는다 — 사람이 적은 값이 금액
   계산에 섞이면 돈의 원천이 둘로 갈린다.
"""
import datetime as _dt
import pathlib

import pytest

import webapp.routes.orders as om


@pytest.fixture
def client(monkeypatch, tmp_path):
    from flask import Flask
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import lemouton.margin.models_settle_recon  # noqa: F401 — 표 등록
    import shared.db as db

    eng = create_engine(f"sqlite:///{tmp_path / 'recon.db'}")
    db.Base.metadata.create_all(eng)
    SL = sessionmaker(bind=eng, autoflush=False, autocommit=False, future=True,
                      expire_on_commit=False)
    monkeypatch.setattr(db, "SessionLocal", SL)
    monkeypatch.setattr(om, "SessionLocal", SL)
    monkeypatch.setattr(om, "_settle_plan_lines", lambda markets=None: [])

    app = Flask(__name__, template_folder="webapp/templates",
                root_path=pathlib.Path(om.__file__).parents[2].as_posix())
    app.register_blueprint(om.bp)
    return app.test_client()


def test_화면_합계를_받아_대조하고_저장한다(client):
    r = client.post("/orders/settle-recon/run-manual", data={
        "item": "coupang_unconfirmed", "market_total": "268,840",
        "market_count": "5", "screen_basis": "결제일 2026-07-12~2026-08-12",
        "memo": "정산현황 > 정산예정 > 미구매확정"})
    assert r.status_code == 200, r.get_data(as_text=True)
    d = r.get_json()
    assert d["ok"] is True
    assert d["result"]["마켓값"] == 268840        # 쉼표가 있어도 읽는다
    assert d["result"]["손입력"] is True
    assert d["result"]["화면기준"] == "결제일 2026-07-12~2026-08-12"


def test_숫자가_아니면_거절한다(client):
    """🔴 빈칸을 0 으로 받으면 「대조했는데 일치」라는 가장 나쁜 거짓말이 된다."""
    r = client.post("/orders/settle-recon/run-manual",
                    data={"item": "coupang_unconfirmed", "market_total": ""})
    assert r.status_code == 400
    assert "거짓말" in r.get_json()["error"]


def test_모르는_항목은_거절한다(client):
    r = client.post("/orders/settle-recon/run-manual",
                    data={"item": "없는항목", "market_total": "100"})
    assert r.status_code == 400


def test_주문단위_대조는_못한다고_말한다(client):
    """주문번호가 없는 입력이라 주문 단위로는 못 맞댄다 — 숨기지 않는다."""
    r = client.post("/orders/settle-recon/run-manual", data={
        "item": "coupang_unconfirmed", "market_total": "268840"})
    assert r.get_json()["result"]["주문단위"]["가능"] is False


def test_이력에_남아_지난번과_이어진다(client):
    for v in ("100000", "268840"):
        client.post("/orders/settle-recon/run-manual",
                    data={"item": "coupang_unconfirmed", "market_total": v})
    r = client.get("/orders/settle-recon/latest")
    assert r.status_code == 200
    latest = r.get_json()["latest"]["coupang_unconfirmed"]
    assert latest["result"]["마켓값"] == 268840        # 마지막 것이 남는다
    assert latest["filename"] == "(마켓 화면 값 직접 입력)"   # 손입력임을 이력이 말한다
