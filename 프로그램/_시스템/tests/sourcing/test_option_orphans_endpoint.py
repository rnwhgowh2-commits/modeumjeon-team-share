# -*- coding: utf-8 -*-
"""[TEST] 유령 옵션 창구 — GET /api/bundles/<code>/options/orphans · POST .../resolve.

설계서 — docs/superpowers/specs/2026-08-02-옵션값-이름바꾸기-design.md
"""
import os

import pytest

os.environ.setdefault("ENVIRONMENT", "test")

_CODE = "TESTORPHAN1"


@pytest.fixture
def client():
    for _m in (
        "lemouton.sourcing.models", "lemouton.sourcing.models_pricing",
        "lemouton.sources.models", "lemouton.templates.models",
        "lemouton.inventory.models", "lemouton.matrix.models",
    ):
        try:
            __import__(_m)
        except ImportError:
            pass
    from shared.db import Base, engine
    Base.metadata.create_all(engine)

    from flask import Flask
    from webapp.routes.api import bp
    app = Flask(__name__)
    app.register_blueprint(bp)
    app.config.update(TESTING=True)
    return app.test_client()


@pytest.fixture
def seeded(client):
    """테스트 이름(색상1·색상2)으로 만들었다가 설계를 블랙 하나로 고친 상태."""
    from shared.db import SessionLocal
    from lemouton.sourcing.models import BundleOptionStep, Model, Option
    from lemouton.sourcing.option_service import (
        create_combination_options, save_step_design)

    s = SessionLocal()
    try:
        s.query(Option).filter_by(model_code=_CODE).delete()
        s.query(BundleOptionStep).filter_by(model_code=_CODE).delete()
        if s.query(Model).filter_by(model_code=_CODE).first() is None:
            s.add(Model(model_code=_CODE, model_name_raw="유령테스트"))
        s.commit()

        create_combination_options(
            s, _CODE,
            [{"axis_name": "색상", "values": ["색상1", "색상2"]},
             {"axis_name": "사이즈", "values": ["250"]}],
            selected=[["색상1", "250"], ["색상2", "250"]], prune=True)
        # 옛 결함이 남긴 상태 재현 — 설계만 바뀌고 옛 옵션이 남은 모양
        save_step_design(s, _CODE, [{"axis_name": "색상", "values": ["블랙"]},
                                    {"axis_name": "사이즈", "values": ["250"]}])
        s.commit()
    finally:
        s.close()
    yield client
    s = SessionLocal()
    try:
        s.query(Option).filter_by(model_code=_CODE).delete()
        s.query(BundleOptionStep).filter_by(model_code=_CODE).delete()
        s.query(Model).filter_by(model_code=_CODE).delete()
        s.commit()
    finally:
        s.close()


def test_orphans_listed_with_labels(seeded):
    r = seeded.get(f"/api/bundles/{_CODE}/options/orphans")
    assert r.status_code == 200
    d = r.get_json()
    assert d["total"] == 2
    assert {i["label"] for i in d["items"]} == {"색상1 250", "색상2 250"}
    assert all(i["deletable"] for i in d["items"])


def test_orphans_404_for_unknown_bundle(seeded):
    assert seeded.get("/api/bundles/NOPE-XYZ/options/orphans").status_code == 404


def test_resolve_off(seeded):
    skus = [i["canonical_sku"]
            for i in seeded.get(f"/api/bundles/{_CODE}/options/orphans").get_json()["items"]]
    r = seeded.post(f"/api/bundles/{_CODE}/options/orphans/resolve",
                    json={"skus": skus, "action": "off"})
    assert r.status_code == 200
    assert r.get_json()["turned_off"] == 2


def test_resolve_delete_removes_them(seeded):
    skus = [i["canonical_sku"]
            for i in seeded.get(f"/api/bundles/{_CODE}/options/orphans").get_json()["items"]]
    r = seeded.post(f"/api/bundles/{_CODE}/options/orphans/resolve",
                    json={"skus": skus, "action": "delete"})
    assert r.get_json()["deleted"] == 2
    assert seeded.get(f"/api/bundles/{_CODE}/options/orphans").get_json()["total"] == 0


def test_resolve_rejects_unknown_action(seeded):
    r = seeded.post(f"/api/bundles/{_CODE}/options/orphans/resolve",
                    json={"skus": ["SKU-WHATEVER"], "action": "지우기"})
    assert r.status_code != 200 or r.get_json().get("ok") is False
