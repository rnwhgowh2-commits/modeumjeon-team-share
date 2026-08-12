# -*- coding: utf-8 -*-
"""실매입가 **변경 이력**(B) + **여러 줄 한꺼번에 입력**(C) — 설계서 §9.

`test_purchase_price.py` 와 같은 방식(in-memory SQLite StaticPool 하나를 라우트와
테스트가 함께 본다). 여기선 소싱 계산이 필요 없어서 매트릭스·breakdown 은 안 쓴다.

🔴 이 시험이 지키는 것
 ① **바뀐 때만** 이력이 는다 — 같은 값을 다시 저장해도 행이 안 늘어야 한다.
 ② **지움도 이력이다** — new_price=None 으로 남아야 한다(그냥 사라지면 이력이 아니다).
 ③ **엑셀이 수기 값을 덮어쓴 사건**이 이력에 남는다(옛값·새값·경로가 다 보인다).
 ④ 일괄 저장은 **line_uid 로만** 움직인다 — 안 고른 줄은 그대로다.
 ⑤ 일괄에서 한 줄이 실패해도 나머지는 저장되고, 실패한 줄을 **돌려준다**(조용한 실패 금지).
"""
import pathlib

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from shared.db import Base

for _m in (
    "lemouton.markets.models_orders", "lemouton.markets.models_purchase",
    "lemouton.markets.models_purchase_history",
):
    try:
        __import__(_m)
    except ImportError:
        pass

import webapp.routes.orders as om
from lemouton.markets import purchase_price as PP

UID = "coupang|BOX1|V777"
UID2 = "coupang|BOX2|V777"


@pytest.fixture
def engine():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def db(engine):
    s = Session(engine)
    yield s
    s.close()


@pytest.fixture
def client(engine, monkeypatch):
    from flask import Flask
    monkeypatch.setattr(om, "SessionLocal", sessionmaker(bind=engine))
    app = Flask(__name__, template_folder="webapp/templates",
                root_path=pathlib.Path(om.__file__).parents[2].as_posix())
    app.register_blueprint(om.bp)
    return app.test_client()


# ══════════════════════════════════════════════════════════════════════
# B. 변경 이력
# ══════════════════════════════════════════════════════════════════════

def test_first_input_is_recorded_as_none_to_value(db):
    PP.upsert(db, line_uid=UID, price=88000, input_by="사장님")
    h = PP.history(db, UID)
    assert len(h) == 1
    assert h[0]["old_price"] is None and h[0]["new_price"] == 88000
    assert h[0]["reason"] == PP.SOURCE_MANUAL
    assert h[0]["changed_by"] == "사장님"


def test_same_value_again_does_not_grow_history(db):
    PP.upsert(db, line_uid=UID, price=88000)
    PP.upsert(db, line_uid=UID, price="88,000")     # 같은 값(쉼표만 다름)
    assert len(PP.history(db, UID)) == 1, "안 바뀌었는데 이력이 늘면 잡음이다"


def test_change_keeps_the_old_value(db):
    PP.upsert(db, line_uid=UID, price=88000)
    PP.upsert(db, line_uid=UID, price=91000)
    h = PP.history(db, UID)
    assert len(h) == 2
    # 최신이 먼저
    assert (h[0]["old_price"], h[0]["new_price"]) == (88000, 91000)
    assert (h[1]["old_price"], h[1]["new_price"]) == (None, 88000)


def test_delete_is_also_history(db):
    PP.upsert(db, line_uid=UID, price=88000)
    PP.upsert(db, line_uid=UID, price=0)            # 0 = 지움
    h = PP.history(db, UID)
    assert h[0]["old_price"] == 88000 and h[0]["new_price"] is None, \
        "지운 사실이 안 남으면 「왜 값이 사라졌지」를 영영 못 푼다"


def test_excel_overwriting_manual_value_is_visible(db):
    """🔴 실제로 겁나는 사건 — 사장님이 손으로 적은 값을 엑셀 재업로드가 덮어씀."""
    PP.upsert(db, line_uid=UID, price=88000, source=PP.SOURCE_MANUAL)
    PP.upsert(db, line_uid=UID, price=95000, source=PP.SOURCE_MANGO,
              mango_ref="buy.xlsx#12", reason="mango")
    h = PP.history(db, UID)[0]
    assert (h["old_price"], h["new_price"]) == (88000, 95000)
    assert h["old_source"] == PP.SOURCE_MANUAL and h["new_source"] == PP.SOURCE_MANGO
    assert h["ref"] == "buy.xlsx#12", "어느 파일 몇 번째 줄이 덮었는지 말해야 한다"


def test_history_is_per_line_not_per_order(db):
    """열쇠는 line_uid — 다품목 주문의 형제 줄 이력이 섞이면 안 된다."""
    PP.upsert(db, line_uid=UID, price=10000)
    PP.upsert(db, line_uid=UID2, price=20000)
    assert len(PP.history(db, UID)) == 1
    assert PP.history(db, UID)[0]["new_price"] == 10000
    assert PP.history(db, UID2)[0]["new_price"] == 20000


def test_history_route(client, db):
    PP.upsert(db, line_uid=UID, price=88000)
    r = client.get(f"/orders/api/purchase-price/history?line_uid={UID}")
    j = r.get_json()
    assert r.status_code == 200 and j["ok"] is True
    assert len(j["items"]) == 1 and j["items"][0]["new_price"] == 88000

    # line_uid 없이 부르면 400 — 어느 줄인지 모른 채 뭔가를 돌려주지 않는다
    assert client.get("/orders/api/purchase-price/history").status_code == 400


def test_history_empty_for_untouched_line(client):
    j = client.get("/orders/api/purchase-price/history?line_uid=nope").get_json()
    assert j["ok"] is True and j["items"] == []


# ══════════════════════════════════════════════════════════════════════
# C. 여러 줄 한꺼번에
# ══════════════════════════════════════════════════════════════════════

def test_bulk_saves_only_selected_lines(client, db):
    PP.upsert(db, line_uid=UID2, price=50000)       # 안 고른 줄
    j = client.post("/orders/api/purchase-price/bulk",
                    json={"line_uids": [UID], "price": 77000}).get_json()
    assert j["ok"] is True and j["saved"] == 1 and j["deleted"] == 0
    assert j["tier"] == PP.TIER_REAL and j["price"] == 77000
    db.expire_all()
    got = PP.get_many(db, [UID, UID2])
    assert got[UID].purchase_price == 77000
    assert got[UID2].purchase_price == 50000, "안 고른 줄이 바뀌면 안 된다"


def test_bulk_blank_deletes(client, db):
    PP.upsert(db, line_uid=UID, price=77000)
    PP.upsert(db, line_uid=UID2, price=88000)
    j = client.post("/orders/api/purchase-price/bulk",
                    json={"line_uids": [UID, UID2], "price": None}).get_json()
    assert j["ok"] is True and j["deleted"] == 2 and j["saved"] == 0
    assert j["price"] is None and j["tier"] is None
    db.expire_all()
    assert PP.get_many(db, [UID, UID2]) == {}


def test_bulk_records_history_for_every_line(client, db):
    client.post("/orders/api/purchase-price/bulk",
                json={"line_uids": [UID, UID2], "price": 60000})
    db.expire_all()
    assert PP.history(db, UID)[0]["new_price"] == 60000
    assert PP.history(db, UID2)[0]["new_price"] == 60000


def test_bulk_rejects_non_numeric(client):
    r = client.post("/orders/api/purchase-price/bulk",
                    json={"line_uids": [UID], "price": "만원쯤"})
    assert r.status_code == 400, "숫자가 아닌 값이 조용히 0(=삭제)으로 흘러선 안 된다"


def test_bulk_rejects_empty_selection(client):
    assert client.post("/orders/api/purchase-price/bulk",
                       json={"line_uids": [], "price": 1000}).status_code == 400


def test_bulk_one_failure_does_not_stop_the_rest(client, db, monkeypatch):
    """한 줄이 터져도 나머지는 저장되고, 실패한 줄을 **돌려준다**(조용한 실패 금지)."""
    real = PP.upsert

    def flaky(session, *, line_uid, **kw):
        if line_uid == UID2:
            raise RuntimeError("일부러 터뜨림")
        return real(session, line_uid=line_uid, **kw)

    monkeypatch.setattr(om, "_who", lambda: None)
    monkeypatch.setattr(PP, "upsert", flaky)
    j = client.post("/orders/api/purchase-price/bulk",
                    json={"line_uids": [UID, UID2], "price": 33000}).get_json()
    assert j["ok"] is True and j["saved"] == 1
    assert [f["line_uid"] for f in j["failed"]] == [UID2]


def test_bulk_guards_absurd_batch(client):
    uids = [f"u{i}" for i in range(2001)]
    r = client.post("/orders/api/purchase-price/bulk",
                    json={"line_uids": uids, "price": 1000})
    assert r.status_code == 400
