# -*- coding: utf-8 -*-
"""「주문 관리」 상태 열 — 항목 CRUD · 삭제 안전장치 · 줄마다 지정 · 기본 항목.

사장님 확정(2026-08-06)
· 처음엔 **빈 목록**(기본 항목을 심지 않는다)
· 이름 중복 금지 · 색은 우리 7색만
· 쓰는 중인 항목 삭제는 **409 + 건수**, force 면 그 줄들이 「지정 안 함」이 된다
· 기본 항목은 **전체에서 하나** · **표시만**(행을 만들지 않는다)
· 🔴 주문 재수집(`order_store.save`)에도 안 지워진다

in-memory SQLite(StaticPool) 하나를 라우트와 테스트가 함께 본다.
"""
import json
import pathlib

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from shared.db import Base

for _m in (
    "lemouton.sourcing.models", "lemouton.sourcing.models_pricing",
    "lemouton.sourcing.models_v2", "lemouton.pricing.settings",
    "lemouton.uploader.models", "lemouton.templates.models",
    "lemouton.inventory.models", "lemouton.sources.models",
    "lemouton.sets.models", "lemouton.multitenancy.models",
    "lemouton.audit.models", "lemouton.mapping.models",
    "lemouton.markets.models_orders", "lemouton.markets.models_purchase",
    "lemouton.markets.models_order_status",
):
    try:
        __import__(_m)
    except ImportError:
        pass

import webapp.routes.orders as om
from lemouton.markets import order_status as ST
from lemouton.markets import order_store as OS
from lemouton.markets.models_order_status import (STATUS_COLORS,
                                                  OrderLineStatus,
                                                  OrderStatusOption)

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
    """라우트가 같은 in-memory DB 를 보게 한다."""
    from flask import Flask
    monkeypatch.setattr(om, "SessionLocal", sessionmaker(bind=engine))
    app = Flask(__name__, template_folder="webapp/templates",
                root_path=pathlib.Path(om.__file__).parents[2].as_posix())
    app.register_blueprint(om.bp)
    return app.test_client()


def _row(uid=UID, *, order_no="O1", name="운동화 12345", opt="블랙 / 260"):
    return {"_line_uid": uid, "판매처": "쿠팡", "오픈마켓주문번호": order_no,
            "상품명": name, "옵션": opt, "단가": 139000, "배송비": 0, "수량": 1,
            "주문일": "2026-08-01 10:00:00"}


def _j(resp):
    return json.loads(resp.data)


# ══════════════════════════════════════════════════════════════════════
# ⑦ 빈 목록으로 시작 — 기본 항목을 미리 심지 않는다 (사장님 확정 a)
# ══════════════════════════════════════════════════════════════════════

def test_starts_empty_no_seeded_options(db):
    """표를 만들자마자 항목이 0개여야 한다. 하나라도 있으면 우리가 심은 것이다."""
    assert ST.list_options(db) == []
    assert db.query(OrderStatusOption).count() == 0
    assert ST.get_default(db) is None


def test_list_endpoint_is_empty_at_first(client):
    r = client.get("/orders/api/status-options")
    assert r.status_code == 200
    j = _j(r)
    assert j["ok"] is True and j["options"] == []
    # 고를 수 있는 색은 **우리 7색뿐**이다(자유 색 금지)
    assert j["colors"] == list(STATUS_COLORS)
    assert len(j["colors"]) == 7


# ══════════════════════════════════════════════════════════════════════
# ① 항목 CRUD
# ══════════════════════════════════════════════════════════════════════

def test_create_update_reorder(db):
    a = ST.create_option(db, name="주문접수", color="gray")
    b = ST.create_option(db, name="배송완료", color="green")
    assert [o["name"] for o in ST.list_options(db)] == ["주문접수", "배송완료"]
    assert a["sort_no"] < b["sort_no"]

    ST.update_option(db, a["id"], name="주문 접수", color="blue")
    got = ST.list_options(db)[0]
    assert got["name"] == "주문 접수" and got["color"] == "blue"

    ST.reorder(db, [b["id"], a["id"]])
    assert [o["name"] for o in ST.list_options(db)] == ["배송완료", "주문 접수"]


def test_reject_unknown_color(db):
    with pytest.raises(ValueError):
        ST.create_option(db, name="아무거나", color="#FF00AA")
    with pytest.raises(ValueError):
        ST.create_option(db, name="아무거나2", color="pink")


def test_reject_blank_name(db):
    with pytest.raises(ValueError):
        ST.create_option(db, name="   ")


def test_crud_endpoints(client):
    r = client.post("/orders/api/status-options",
                    json={"name": "결제완료", "color": "blue"})
    assert r.status_code == 200
    oid = _j(r)["option"]["id"]

    r = client.patch(f"/orders/api/status-options/{oid}",
                     json={"name": "결제 완료", "color": "teal"})
    assert r.status_code == 200
    assert _j(r)["option"]["name"] == "결제 완료"
    assert _j(r)["option"]["color"] == "teal"

    r = client.get("/orders/api/status-options")
    assert [o["name"] for o in _j(r)["options"]] == ["결제 완료"]

    r = client.delete(f"/orders/api/status-options/{oid}")
    assert r.status_code == 200 and _j(r)["options"] == []


# ══════════════════════════════════════════════════════════════════════
# ② 이름 중복 거절
# ══════════════════════════════════════════════════════════════════════

def test_duplicate_name_rejected(db):
    ST.create_option(db, name="배송완료")
    with pytest.raises(ValueError):
        ST.create_option(db, name="배송완료")
    # 앞뒤 공백만 다른 것도 같은 이름이다
    with pytest.raises(ValueError):
        ST.create_option(db, name="  배송완료  ")
    assert len(ST.list_options(db)) == 1


def test_duplicate_name_rejected_on_rename(db):
    a = ST.create_option(db, name="주문접수")
    ST.create_option(db, name="배송완료")
    with pytest.raises(ValueError):
        ST.update_option(db, a["id"], name="배송완료")
    # 자기 이름 그대로 저장하는 건 막지 않는다
    assert ST.update_option(db, a["id"], name="주문접수")["name"] == "주문접수"


def test_duplicate_name_endpoint_400(client):
    client.post("/orders/api/status-options", json={"name": "배송완료"})
    r = client.post("/orders/api/status-options", json={"name": "배송완료"})
    assert r.status_code == 400
    assert _j(r)["ok"] is False and "배송완료" in _j(r)["error"]


# ══════════════════════════════════════════════════════════════════════
# ③ 쓰는 중 삭제 = 409 + 건수 / force 면 삭제되고 그 줄 상태가 비워진다
# ══════════════════════════════════════════════════════════════════════

def test_delete_in_use_raises_with_count(db):
    o = ST.create_option(db, name="해외현지배송중")
    for uid in (UID, UID2, "coupang|BOX3|V1"):
        ST.set_line_status(db, line_uid=uid, option_id=o["id"])
    assert ST.usage_count(db, o["id"]) == 3

    with pytest.raises(ST.InUseError) as e:
        ST.delete_option(db, o["id"])
    assert e.value.count == 3
    # 거절했으면 **아무것도 안 지워져 있어야** 한다
    assert db.query(OrderStatusOption).count() == 1
    assert db.query(OrderLineStatus).count() == 3


def test_delete_endpoint_409_then_force(client, db):
    r = client.post("/orders/api/status-options", json={"name": "오류입고"})
    oid = _j(r)["option"]["id"]
    for uid in (UID, UID2, "coupang|BOX3|V1"):
        client.post("/orders/api/line-status",
                    json={"line_uid": uid, "option_id": oid})

    r = client.delete(f"/orders/api/status-options/{oid}")
    assert r.status_code == 409
    j = _j(r)
    assert j["ok"] is False and j["in_use"] is True and j["count"] == 3
    db.expire_all()
    assert db.query(OrderStatusOption).count() == 1

    r = client.delete(f"/orders/api/status-options/{oid}?force=1")
    assert r.status_code == 200
    j = _j(r)
    assert j["ok"] is True and j["cleared"] == 3 and j["options"] == []
    db.expire_all()
    # 그 주문들의 상태는 **비워진다**(「지정 안 함」)
    assert db.query(OrderLineStatus).count() == 0
    assert ST.resolve(db, [UID, UID2]) == {}


def test_delete_not_in_use_is_allowed_without_force(db):
    o = ST.create_option(db, name="임시")
    assert ST.delete_option(db, o["id"])["cleared"] == 0
    assert ST.list_options(db) == []


# ══════════════════════════════════════════════════════════════════════
# ④ line-status 저장 · 해제
# ══════════════════════════════════════════════════════════════════════

def test_set_and_clear_line_status(db):
    o = ST.create_option(db, name="배송완료", color="green")
    ST.set_line_status(db, line_uid=UID, option_id=o["id"])
    got = ST.resolve(db, [UID])[UID]
    assert got == {"option_id": o["id"], "name": "배송완료", "color": "green",
                   "is_fallback": False}

    # 비우면 **행 자체를 지운다** — 「지정 안 함」을 행으로 남기지 않는다
    assert ST.set_line_status(db, line_uid=UID, option_id=None) is None
    assert db.query(OrderLineStatus).count() == 0
    assert ST.resolve(db, [UID]) == {}


def test_set_line_status_rejects_unknown_option(db):
    with pytest.raises(ValueError):
        ST.set_line_status(db, line_uid=UID, option_id=99999)
    with pytest.raises(ValueError):
        ST.set_line_status(db, line_uid="", option_id=None)


def test_line_status_endpoints(client, db):
    oid = _j(client.post("/orders/api/status-options",
                         json={"name": "국내배송중", "color": "purple"}))["option"]["id"]
    r = client.post("/orders/api/line-status",
                    json={"line_uid": UID, "option_id": oid})
    assert r.status_code == 200
    j = _j(r)
    assert j["saved"] is True and j["status"]["name"] == "국내배송중"
    assert j["status"]["is_fallback"] is False

    r = client.post("/orders/api/line-status",
                    json={"line_uid": UID, "option_id": None})
    assert r.status_code == 200 and _j(r)["cleared"] is True
    # 기본 항목이 없으니 비운 줄은 아무 값도 없다
    assert _j(r)["status"] is None

    r = client.post("/orders/api/line-status", json={"option_id": oid})
    assert r.status_code == 400


def test_bulk_endpoint(client, db):
    oid = _j(client.post("/orders/api/status-options",
                         json={"name": "배송지입고완료"}))["option"]["id"]
    r = client.post("/orders/api/line-status/bulk",
                    json={"line_uids": [UID, UID2], "option_id": oid})
    assert r.status_code == 200
    j = _j(r)
    assert j["saved"] == 2 and not j["failed"]
    assert set(j["statuses"]) == {UID, UID2}


# ══════════════════════════════════════════════════════════════════════
# ⑥ resolve 규약 — 실매입가 resolve 와 같은 모양(행을 그대로 보내면 map 을 준다)
# ══════════════════════════════════════════════════════════════════════

def test_resolve_endpoint_contract(client, db):
    oid = _j(client.post("/orders/api/status-options",
                         json={"name": "배송완료", "color": "green"}))["option"]["id"]
    client.post("/orders/api/line-status", json={"line_uid": UID, "option_id": oid})

    r = client.post("/orders/api/line-status/resolve",
                    json={"rows": [_row(UID), _row(UID2, order_no="O2")]})
    assert r.status_code == 200
    j = _j(r)
    assert j["ok"] is True
    assert j["statuses"][UID] == {"option_id": oid, "name": "배송완료",
                                 "color": "green", "is_fallback": False}
    # 기본 항목이 없으면 지정 안 한 줄은 응답에 아예 없다(= 빈 「고르기」 알약)
    assert UID2 not in j["statuses"]
    # 드롭다운을 그리려면 항목 목록도 필요하다 — 같은 응답에 담는다(요청 1건)
    assert [o["name"] for o in j["options"]] == ["배송완료"]


def test_resolve_endpoint_rejects_bad_payload(client):
    r = client.post("/orders/api/line-status/resolve", json={"rows": "nope"})
    assert r.status_code == 400


def test_resolve_ignores_orphan_rows(db):
    """항목을 지웠는데 상태 행이 남았다면 「지정 안 함」으로 본다(유령 값 금지)."""
    o = ST.create_option(db, name="임시")
    ST.set_line_status(db, line_uid=UID, option_id=o["id"])
    db.query(OrderStatusOption).filter_by(id=o["id"]).delete()
    db.commit()
    assert ST.resolve(db, [UID]) == {}


# ══════════════════════════════════════════════════════════════════════
# ⑤ 🔴 핵심 안전장치 — 주문을 다시 수집해도 상태가 안 지워진다
# ══════════════════════════════════════════════════════════════════════

def test_reingest_does_not_wipe_status(db):
    """`order_store.save` 는 `market_order_lines` 만 건드린다 — 이 표는 안 본다.

    주문 줄 JSON 안에 끼워 넣었다면 재수집이 `row` 를 통째 교체하며 조용히 증발했을 값이다.
    """
    o = ST.create_option(db, name="해외현지배송중", color="blue")
    OS.save([_row()], session=db)
    ST.set_line_status(db, line_uid=UID, option_id=o["id"])

    # 같은 라인을 다시 수집 — 상품명·단가·상태가 전부 바뀐 채로 들어온다
    OS.save([dict(_row(), 상품명="운동화(이름 바뀜) 12345", 단가=149000,
                  주문상태="배송완료")], session=db)
    db.expire_all()

    assert ST.resolve(db, [UID])[UID]["name"] == "해외현지배송중"
    # 주문 쪽은 실제로 갱신됐는지도 확인(테스트가 헛돌지 않게)
    stored = OS.load(order_nos=["O1"], include_claims=False, session=db)
    assert stored and stored[0]["상품명"] == "운동화(이름 바뀜) 12345"


# ══════════════════════════════════════════════════════════════════════
# ⑧ 기본 항목 — 전체에서 하나 · 표시만 · 지우면 「지정 안 함」
#    (사장님 추가 확정 2026-08-06)
# ══════════════════════════════════════════════════════════════════════

def test_setting_default_clears_the_previous_one(db):
    """🔴 둘 다 True 인 상태가 **절대** 안 생겨야 한다."""
    a = ST.create_option(db, name="주문접수")
    b = ST.create_option(db, name="결제완료")
    ST.set_default(db, a["id"])
    assert [o["is_default"] for o in ST.list_options(db)] == [True, False]

    ST.set_default(db, b["id"])
    db.expire_all()
    got = ST.list_options(db)
    assert [o["is_default"] for o in got] == [False, True]
    assert sum(1 for o in got if o["is_default"]) == 1
    assert db.query(OrderStatusOption).filter_by(is_default=True).count() == 1


def test_default_via_patch_endpoint(client, db):
    a = _j(client.post("/orders/api/status-options", json={"name": "주문접수"}))["option"]
    b = _j(client.post("/orders/api/status-options", json={"name": "결제완료"}))["option"]
    client.patch(f"/orders/api/status-options/{a['id']}", json={"is_default": True})
    r = client.patch(f"/orders/api/status-options/{b['id']}", json={"is_default": True})
    assert r.status_code == 200
    opts = {o["name"]: o["is_default"] for o in _j(r)["options"]}
    assert opts == {"주문접수": False, "결제완료": True}

    # 목록 응답에 is_default 가 들어 있다(화면이 ⭐ 를 그린다)
    r = client.get("/orders/api/status-options")
    assert sum(1 for o in _j(r)["options"] if o["is_default"]) == 1

    # 끄기도 된다(기본 없음)
    client.patch(f"/orders/api/status-options/{b['id']}", json={"is_default": False})
    db.expire_all()
    assert ST.get_default(db) is None


def test_unsaved_line_gets_default_with_is_fallback(db):
    """저장 안 된 줄엔 기본 항목이 얹혀 오되 **is_fallback: True** 로 구분된다."""
    d = ST.create_option(db, name="결제완료", color="blue", is_default=True)
    other = ST.create_option(db, name="배송완료", color="green")
    ST.set_line_status(db, line_uid=UID, option_id=other["id"])

    got = ST.resolve(db, [UID, UID2])
    assert got[UID] == {"option_id": other["id"], "name": "배송완료",
                        "color": "green", "is_fallback": False}
    assert got[UID2] == {"option_id": d["id"], "name": "결제완료",
                         "color": "blue", "is_fallback": True}


def test_default_makes_no_db_rows(db):
    """🔴 기본값이 **실제 행을 만들지 않는다** — 주문 100줄에 status 행 0개."""
    ST.create_option(db, name="결제완료", is_default=True)
    uids = [f"coupang|N{i}|V{i}" for i in range(100)]
    got = ST.resolve(db, uids)

    assert len(got) == 100
    assert all(v["is_fallback"] for v in got.values())
    assert db.query(OrderLineStatus).count() == 0, (
        "기본 항목이 주문 줄마다 행을 만들었다 — 「표시만」 규칙 위반")


def test_deleting_default_leaves_rows_unassigned(db):
    """기본 항목을 지우면 그 줄들은 「지정 안 함」이 된다(빈 알약)."""
    d = ST.create_option(db, name="결제완료", is_default=True)
    ST.set_line_status(db, line_uid=UID, option_id=d["id"])   # 손으로 고른 줄도 하나
    assert ST.resolve(db, [UID, UID2])[UID2]["is_fallback"] is True

    res = ST.delete_option(db, d["id"], force=True)
    assert res["was_default"] is True and res["cleared"] == 1
    db.expire_all()
    assert ST.get_default(db) is None
    assert ST.resolve(db, [UID, UID2]) == {}


def test_cleared_line_falls_back_to_default_again(db, client):
    """비운 줄은 기본 항목이 있으면 **다시 기본 표시**로 돌아간다(저장은 안 된다)."""
    d = _j(client.post("/orders/api/status-options",
                       json={"name": "결제완료", "is_default": True}))["option"]
    other = _j(client.post("/orders/api/status-options",
                           json={"name": "배송완료"}))["option"]
    client.post("/orders/api/line-status", json={"line_uid": UID,
                                                 "option_id": other["id"]})
    r = client.post("/orders/api/line-status", json={"line_uid": UID,
                                                     "option_id": None})
    j = _j(r)
    assert j["cleared"] is True
    assert j["status"]["option_id"] == d["id"] and j["status"]["is_fallback"] is True
    db.expire_all()
    assert db.query(OrderLineStatus).count() == 0


def test_usage_count_in_list(db):
    """삭제 확인창이 「몇 건이 쓰는 중」인지 묻기 전에 알 수 있어야 한다."""
    o = ST.create_option(db, name="배송완료")
    ST.create_option(db, name="임시")
    ST.set_line_status(db, line_uid=UID, option_id=o["id"])
    ST.set_line_status(db, line_uid=UID2, option_id=o["id"])
    used = {x["name"]: x["used"] for x in ST.list_options(db)}
    assert used == {"배송완료": 2, "임시": 0}
