# -*- coding: utf-8 -*-
"""[TEST] 옵션별 브랜드 API — 목록·조회·저장·일괄.

- GET  /api/options/brands                     브랜드 목록(검색 팔레트)
- POST /api/options/brand                       옵션 1개 저장 {canonical_sku, brand}
- GET  /api/bundles/<model_code>/brands         옵션별 브랜드 + 요약
- POST /api/bundles/<model_code>/brands/bulk    일괄 {brand, mode, skus?}

dev DB 오염 방지: 고유 접두사 데이터로 만들고 teardown 에서 제거.
"""
import os
import pytest

os.environ.setdefault("ENVIRONMENT", "test")

PFX = "OBT_"   # 이 테스트 전용 model_code/sku 접두사


@pytest.fixture
def client():
    for _m in (
        "lemouton.sourcing.models", "lemouton.sourcing.models_pricing",
        "lemouton.sources.models", "lemouton.templates.models",
        "lemouton.inventory.models", "lemouton.pricing.settings",
        "lemouton.multitenancy.models",
    ):
        try:
            __import__(_m)
        except ImportError:
            pass
    from shared.db import Base, engine, _apply_lightweight_migrations
    Base.metadata.create_all(engine)
    _apply_lightweight_migrations()   # 신규 컬럼(options.brand)은 ALTER 로 보강

    from flask import Flask
    from webapp.routes.api import bp
    app = Flask(__name__)
    app.register_blueprint(bp)
    app.config.update(TESTING=True)
    yield app.test_client()

    # teardown — 이 테스트가 만든 행만 제거(dev DB 찌꺼기 방지)
    from shared.db import SessionLocal
    from lemouton.sourcing.models import Model, Option
    s = SessionLocal()
    try:
        s.query(Option).filter(Option.model_code.like(PFX + "%")).delete(
            synchronize_session=False)
        s.query(Model).filter(Model.model_code.like(PFX + "%")).delete(
            synchronize_session=False)
        s.commit()
    finally:
        s.close()


def _seed(model_brand="르무통", opts=None):
    """PFX 모델 1개 + 옵션들 생성. opts=[(sku_suffix, brand)]."""
    from shared.db import SessionLocal
    from lemouton.sourcing.models import Model, Option
    s = SessionLocal()
    try:
        mc = PFX + "M1"
        s.merge(Model(model_code=mc, model_name_raw=mc, brand=model_brand))
        for i, (suf, brand) in enumerate(opts or []):
            s.merge(Option(canonical_sku=PFX + suf, model_code=mc,
                           color_code="블랙", size_code=str(260 + i), brand=brand))
        s.commit()
        return mc
    finally:
        s.close()


def test_get_brands_list(client):
    _seed("르무통", [("s1", "나이키"), ("s2", "아디다스"), ("s3", None)])
    r = client.get("/api/options/brands")
    assert r.status_code == 200
    brands = r.get_json()["brands"]
    assert "나이키" in brands and "아디다스" in brands and "르무통" in brands


def test_post_set_option_brand(client):
    mc = _seed("르무통", [("s1", None)])
    r = client.post("/api/options/brand",
                    json={"canonical_sku": PFX + "s1", "brand": "구찌"})
    assert r.status_code == 200
    assert r.get_json()["ok"] is True

    from shared.db import SessionLocal
    from lemouton.sourcing.models import Option
    s = SessionLocal()
    try:
        assert s.get(Option, PFX + "s1").brand == "구찌"
    finally:
        s.close()


def test_post_set_option_brand_missing_404(client):
    r = client.post("/api/options/brand",
                    json={"canonical_sku": PFX + "nope", "brand": "구찌"})
    assert r.status_code == 404
    assert r.get_json()["ok"] is False


def test_get_bundle_brands_with_summary(client):
    mc = _seed("르무통", [("s1", "나이키"), ("s2", None)])
    r = client.get(f"/api/bundles/{mc}/brands")
    assert r.status_code == 200
    d = r.get_json()
    assert d["summary"]["total"] == 2
    assert d["summary"]["unassigned"] == 1
    # 옵션별 유효 브랜드 포함(상속 반영)
    by_sku = {o["canonical_sku"]: o for o in d["options"]}
    assert by_sku[PFX + "s1"]["effective_brand"] == "나이키"
    assert by_sku[PFX + "s2"]["effective_brand"] == "르무통"   # 상속
    assert by_sku[PFX + "s2"]["brand"] is None                # 자체는 미지정


def test_post_bulk_empty_only(client):
    mc = _seed("르무통", [("s1", "나이키"), ("s2", None), ("s3", None)])
    r = client.post(f"/api/bundles/{mc}/brands/bulk",
                    json={"brand": "발렌시아가", "mode": "empty"})
    assert r.status_code == 200
    assert r.get_json()["applied"] == 2

    from shared.db import SessionLocal
    from lemouton.sourcing.models import Option
    s = SessionLocal()
    try:
        assert s.get(Option, PFX + "s1").brand == "나이키"       # 유지
        assert s.get(Option, PFX + "s2").brand == "발렌시아가"
        assert s.get(Option, PFX + "s3").brand == "발렌시아가"
    finally:
        s.close()


def test_post_bulk_selected(client):
    mc = _seed("르무통", [("s1", None), ("s2", None)])
    r = client.post(f"/api/bundles/{mc}/brands/bulk",
                    json={"brand": "프라다", "mode": "selected",
                          "skus": [PFX + "s1"]})
    assert r.status_code == 200
    assert r.get_json()["applied"] == 1

    from shared.db import SessionLocal
    from lemouton.sourcing.models import Option
    s = SessionLocal()
    try:
        assert s.get(Option, PFX + "s1").brand == "프라다"
        assert s.get(Option, PFX + "s2").brand is None
    finally:
        s.close()
