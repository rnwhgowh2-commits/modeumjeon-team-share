# -*- coding: utf-8 -*-
"""포장 스캔 출고 API 시험 — 폰이 부르는 두 엔드포인트."""
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


@pytest.fixture()
def seeded(client):
    from shared.db import SessionLocal
    from lemouton.inventory.models import InventoryTx, InventoryLocation
    from lemouton.markets.models_supply import OrderLineSupply
    from lemouton.sourcing.models import Option
    SKU = "SKU-SCANAPI"
    with SessionLocal() as s:
        s.query(InventoryTx).filter_by(option_canonical_sku=SKU).delete(
            synchronize_session=False)
        s.query(OrderLineSupply).delete()
        s.query(Option).filter_by(canonical_sku=SKU).delete(synchronize_session=False)
        loc = s.query(InventoryLocation).filter_by(name="스캔API위치").first()
        if not loc:
            loc = InventoryLocation(name="스캔API위치")
            s.add(loc)
            s.flush()
        s.add(Option(canonical_sku=SKU, model_code="SCANAPI",
                     color_code="BK", size_code="250"))
        s.add(InventoryTx(tx_type="in", location_id=loc.id, qty=5,
                          option_canonical_sku=SKU, status="completed"))
        s.commit()
        return {"sku": SKU, "loc_id": loc.id}


def test_무재고_줄은_안_깎고_사입_줄만_깎는다(client, seeded):
    r1 = client.post("/mobile/api/scan-ship", json={
        "line_uid": "API-드롭", "sku": seeded["sku"],
        "location_id": seeded["loc_id"], "qty": 1})
    j1 = r1.get_json()
    assert j1["ok"] is True and j1["result"] == "no_deduct" and j1["deducted_qty"] == 0

    client.post("/orders/api/supply-mode",
                json={"line_uid": "API-사입", "mode": "사입"})
    r2 = client.post("/mobile/api/scan-ship", json={
        "line_uid": "API-사입", "sku": seeded["sku"],
        "location_id": seeded["loc_id"], "qty": 2})
    j2 = r2.get_json()
    assert j2["result"] == "deducted" and j2["stock_after"] == 3


def test_두_번_찍으면_이미_처리됨(client, seeded):
    client.post("/orders/api/supply-mode",
                json={"line_uid": "API-중복", "mode": "사입"})
    client.post("/mobile/api/scan-ship", json={
        "line_uid": "API-중복", "sku": seeded["sku"],
        "location_id": seeded["loc_id"], "qty": 1})
    r = client.post("/mobile/api/scan-ship", json={
        "line_uid": "API-중복", "sku": seeded["sku"],
        "location_id": seeded["loc_id"], "qty": 1})
    j = r.get_json()
    assert j["result"] == "already" and j["deducted_qty"] == 0
    assert j["stock_after"] == 4          # 5 - 1, 한 번만


def test_재고_부족은_경고를_돌려준다(client, seeded):
    """🔴 막지 않는다 — 화면이 이 warning 을 띄워야 한다."""
    client.post("/orders/api/supply-mode",
                json={"line_uid": "API-부족", "mode": "사입"})
    r = client.post("/mobile/api/scan-ship", json={
        "line_uid": "API-부족", "sku": seeded["sku"],
        "location_id": seeded["loc_id"], "qty": 99})
    j = r.get_json()
    assert j["result"] == "deducted"
    assert j["warning"] and "모자랍니다" in j["warning"]


def test_상태_조회(client, seeded):
    client.post("/orders/api/supply-mode",
                json={"line_uid": "API-상태", "mode": "사입"})
    client.post("/mobile/api/scan-ship", json={
        "line_uid": "API-상태", "sku": seeded["sku"],
        "location_id": seeded["loc_id"], "qty": 1})
    r = client.post("/mobile/api/scan-ship/status",
                    json={"line_uids": ["API-상태", "API-안찍음"]})
    j = r.get_json()
    assert j["ok"] is True
    assert "API-상태" in j["shipped"] and "API-안찍음" not in j["shipped"]
    assert j["modes"]["API-안찍음"] == "dropship"


def test_위치_없으면_404(client, seeded):
    r = client.post("/mobile/api/scan-ship", json={
        "line_uid": "API-x", "sku": seeded["sku"], "location_id": 999999, "qty": 1})
    assert r.status_code == 404


def test_line_uid_없으면_400(client, seeded):
    r = client.post("/mobile/api/scan-ship", json={
        "sku": seeded["sku"], "location_id": seeded["loc_id"], "qty": 1})
    assert r.status_code == 400
