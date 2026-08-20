# -*- coding: utf-8 -*-
"""[TEST] /api/inventory/compose-bundle — 신규 모음전 브랜드 필수화.

new.html 폼의 실제 등록 경로. 빈 브랜드를 '르무통'으로 자동 채우지 않고 거부한다.
"""
import os
import pytest

os.environ.setdefault("ENVIRONMENT", "test")

PFX = "CBT_"


@pytest.fixture
def client():
    for _m in (
        "lemouton.sourcing.models", "lemouton.sourcing.models_pricing",
        "lemouton.sources.models", "lemouton.templates.models",
        "lemouton.inventory.models", "lemouton.multitenancy.models",
    ):
        try:
            __import__(_m)
        except ImportError:
            pass
    from shared.db import Base, engine, _apply_lightweight_migrations
    Base.metadata.create_all(engine)
    _apply_lightweight_migrations()

    from flask import Flask
    from webapp.routes.api import bp
    app = Flask(__name__)
    app.register_blueprint(bp)
    app.config.update(TESTING=True)
    yield app.test_client()

    from shared.db import SessionLocal
    from lemouton.sourcing.models import Model, Option
    from lemouton.inventory.models import InventoryProduct, OptionProductLink
    s = SessionLocal()
    try:
        s.query(OptionProductLink).filter(
            OptionProductLink.option_canonical_sku.like(PFX + "%")).delete(
            synchronize_session=False)
        s.query(Option).filter(Option.model_code.like(PFX + "%")).delete(
            synchronize_session=False)
        s.query(Model).filter(Model.model_code.like(PFX + "%")).delete(
            synchronize_session=False)
        s.query(InventoryProduct).filter(
            InventoryProduct.canonical_sku.like(PFX + "%")).delete(
            synchronize_session=False)
        s.commit()
    finally:
        s.close()


def _seed_product(suffix="p1"):
    from shared.db import SessionLocal
    from lemouton.inventory.models import InventoryProduct
    s = SessionLocal()
    try:
        sku = PFX + suffix
        s.merge(InventoryProduct(canonical_sku=sku, color_code="블랙", size_code="260"))
        s.commit()
        return sku
    finally:
        s.close()


def _model(code):
    from shared.db import SessionLocal
    from lemouton.sourcing.models import Model
    s = SessionLocal()
    try:
        return s.get(Model, code)
    finally:
        s.close()


def test_compose_with_brand_saves_that_brand(client):
    psku = _seed_product("p1")
    code = PFX + "M1"
    r = client.post("/api/inventory/compose-bundle", json={
        "model_code": code, "model_name_raw": "테스트", "brand": "나이키",
        "category": "신발", "product_skus": [psku],
    })
    assert r.status_code == 200
    assert r.get_json()["ok"] is True
    assert _model(code).brand == "나이키"


def test_compose_empty_brand_rejected_not_defaulted(client):
    psku = _seed_product("p2")
    code = PFX + "M2"
    r = client.post("/api/inventory/compose-bundle", json={
        "model_code": code, "model_name_raw": "테스트", "brand": "",
        "category": "신발", "product_skus": [psku],
    })
    assert r.status_code == 400
    assert r.get_json()["ok"] is False
    assert _model(code) is None   # 르무통으로 자동 생성되지 않음
