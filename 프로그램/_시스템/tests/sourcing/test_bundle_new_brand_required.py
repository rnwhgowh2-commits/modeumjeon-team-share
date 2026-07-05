# -*- coding: utf-8 -*-
"""[TEST] 신규 모음전 등록 — 브랜드 필수화(르무통 자동 채움 제거).

신규 등록은 브랜드를 반드시 받아야 하고, 빈 값을 '르무통'으로 자동 채우지 않는다.
(기존 데이터는 건드리지 않음 — 신규만 필수화.)
"""
import os
import pathlib
import pytest

os.environ.setdefault("ENVIRONMENT", "test")

PFX = "RBT_"


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
    from webapp.routes import bundles as b
    app = Flask(__name__, template_folder="webapp/templates",
                root_path=pathlib.Path(b.__file__).parents[2].as_posix())
    app.register_blueprint(b.bp)
    app.config.update(TESTING=True, PROPAGATE_EXCEPTIONS=False)
    yield app.test_client()

    from shared.db import SessionLocal
    from lemouton.sourcing.models import Model
    s = SessionLocal()
    try:
        s.query(Model).filter(Model.model_code.like(PFX + "%")).delete(
            synchronize_session=False)
        s.commit()
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


def test_new_with_brand_saves_that_brand(client):
    code = PFX + "M1"
    r = client.post("/bundles/new", data={
        "model_code": code, "model_name_raw": "테스트모델",
        "brand": "나이키", "category": "신발",
    })
    assert r.status_code == 302   # 성공 → 리다이렉트
    assert _model(code).brand == "나이키"


def test_new_empty_brand_does_not_create_and_not_defaulted(client):
    code = PFX + "M2"
    client.post("/bundles/new", data={
        "model_code": code, "model_name_raw": "테스트모델",
        "brand": "", "category": "신발",
    })
    # 빈 브랜드는 거부 — 모델이 생기지 않아야 하고, '르무통'으로 자동 생성돼서도 안 됨
    assert _model(code) is None
