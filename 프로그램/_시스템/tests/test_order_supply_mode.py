# -*- coding: utf-8 -*-
"""주문 라인 공급방식(무재고/사입) 저장소·API 시험 (사장님 확정 2026-08-06).

규칙
 · 기본값 무재고 — 지정 안 한 줄은 무재고이고, 그 상태를 행으로 만들지 않는다.
 · 열쇠는 line_uid — 주문번호로 묶으면 다품목 주문의 형제 줄이 같이 바뀐다.
 · 🔴 표시만으로 재고를 깎지 않는다(차감은 포장 스캔 시점) — 이 시험이 그걸 고정한다.
"""
import os

import pytest


@pytest.fixture(scope="module")
def client():
    saved = {k: os.environ.get(k) for k in ("ENVIRONMENT", "DISABLE_AUTH")}
    os.environ["ENVIRONMENT"] = "team-share-dev"
    os.environ["DISABLE_AUTH"] = "1"
    from app import create_app
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


@pytest.fixture(autouse=True)
def clean():
    # 저장소 시험은 create_app 을 안 거치므로 스키마를 여기서 보장한다
    # (conftest 가 모든 모델을 import 해 둬서 create_all 이 완전하다).
    from shared.db import Base, SessionLocal, engine
    from lemouton.markets.models_supply import OrderLineSupply
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        s.query(OrderLineSupply).delete()
        s.commit()
    yield


# ── 저장소 ────────────────────────────────────────────────────────────────

def test_지정_안_하면_무재고다():
    from shared.db import SessionLocal
    from lemouton.markets import supply_mode as sm
    with SessionLocal() as s:
        got = sm.get_many_with_default(s, ["L-1", "L-2"])
    assert got == {"L-1": "dropship", "L-2": "dropship"}


def test_사입으로_지정하면_저장된다():
    from shared.db import SessionLocal
    from lemouton.markets import supply_mode as sm
    with SessionLocal() as s:
        sm.set_mode(s, line_uid="L-1", mode="사입")
        assert sm.get_many_with_default(s, ["L-1"])["L-1"] == "stock"


def test_무재고로_되돌리면_행을_지운다():
    """기본값을 행으로 남기지 않는다."""
    from shared.db import SessionLocal
    from lemouton.markets import supply_mode as sm
    from lemouton.markets.models_supply import OrderLineSupply
    with SessionLocal() as s:
        sm.set_mode(s, line_uid="L-1", mode="사입")
        sm.set_mode(s, line_uid="L-1", mode="무재고")
        assert s.get(OrderLineSupply, "L-1") is None
        assert sm.get_many_with_default(s, ["L-1"])["L-1"] == "dropship"


def test_형제_라인은_서로_안_바뀐다():
    """같은 주문번호라도 line_uid 가 다르면 독립이다."""
    from shared.db import SessionLocal
    from lemouton.markets import supply_mode as sm
    with SessionLocal() as s:
        sm.set_mode(s, line_uid="ORD-9|1", mode="사입")
        got = sm.get_many_with_default(s, ["ORD-9|1", "ORD-9|2"])
    assert got == {"ORD-9|1": "stock", "ORD-9|2": "dropship"}


def test_일괄_지정():
    from shared.db import SessionLocal
    from lemouton.markets import supply_mode as sm
    with SessionLocal() as s:
        res = sm.set_many(s, line_uids=["A", "B", "C"], mode="사입")
        assert res["saved"] == 3 and res["failed"] == []
        assert sm.get_many_with_default(s, ["A", "B", "C"]) == {
            "A": "stock", "B": "stock", "C": "stock"}


def test_모르는_값은_거부된다():
    from shared.db import SessionLocal
    from lemouton.markets import supply_mode as sm
    with SessionLocal() as s:
        with pytest.raises(ValueError):
            sm.set_mode(s, line_uid="L-1", mode="위탁판매")


def test_빈_line_uid_는_거부된다():
    from shared.db import SessionLocal
    from lemouton.markets import supply_mode as sm
    with SessionLocal() as s:
        with pytest.raises(ValueError):
            sm.set_mode(s, line_uid="", mode="사입")


def test_표시만으로는_재고를_깎지_않는다():
    """🔴 차감은 포장 스캔 시점이다 — 여기서 InventoryTx 가 생기면 안 된다."""
    from shared.db import SessionLocal
    from lemouton.markets import supply_mode as sm
    from lemouton.inventory.models import InventoryTx
    with SessionLocal() as s:
        before = s.query(InventoryTx).count()
        sm.set_mode(s, line_uid="L-1", mode="사입")
        assert s.query(InventoryTx).count() == before


# ── API ───────────────────────────────────────────────────────────────────

def test_api_저장과_조회(client):
    r = client.post("/orders/api/supply-mode",
                    json={"line_uid": "L-9", "mode": "사입"})
    assert r.status_code == 200, r.get_data(as_text=True)
    j = r.get_json()
    assert j["ok"] is True and j["mode"] == "stock" and j["label"] == "사입"

    r2 = client.post("/orders/api/supply-mode/resolve",
                     json={"rows": [{"_line_uid": "L-9"}, {"_line_uid": "L-8"}]})
    modes = r2.get_json()["modes"]
    assert modes == {"L-9": "stock", "L-8": "dropship"}


def test_api_일괄(client):
    r = client.post("/orders/api/supply-mode/bulk",
                    json={"line_uids": ["X1", "X2"], "mode": "사입"})
    j = r.get_json()
    # 🔴 ok 는 성공 플래그여야 한다 — 처리 건수(saved)가 덮어쓰면 안 된다(실제로 겪은 버그)
    assert j["ok"] is True and j["saved"] == 2 and j["label"] == "사입"
    r2 = client.post("/orders/api/supply-mode/resolve",
                     json={"rows": [{"_line_uid": "X1"}, {"_line_uid": "X2"}]})
    assert r2.get_json()["modes"] == {"X1": "stock", "X2": "stock"}


def test_api_잘못된_값은_400(client):
    r = client.post("/orders/api/supply-mode",
                    json={"line_uid": "L-9", "mode": "몰라요"})
    assert r.status_code == 400
    assert r.get_json()["ok"] is False


def test_api_line_uid_없으면_400(client):
    r = client.post("/orders/api/supply-mode", json={"mode": "사입"})
    assert r.status_code == 400
