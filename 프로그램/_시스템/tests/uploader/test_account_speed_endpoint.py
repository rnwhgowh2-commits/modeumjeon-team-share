# -*- coding: utf-8 -*-
"""[TEST] POST /api/upload/account-speed — 계정(API) 업로드 속도 저장."""
import os

import pytest

os.environ.setdefault("ENVIRONMENT", "test")


@pytest.fixture
def client():
    # 부팅 시 등록되는 모델 전부 import 해야 create_all 이 FK 그래프 해결.
    for _m in (
        "lemouton.sourcing.models", "lemouton.sourcing.models_pricing",
        "lemouton.pricing.settings", "lemouton.uploader.models",
        "lemouton.templates.models", "lemouton.inventory.models",
        "lemouton.sets.models", "lemouton.sources.models",
        "lemouton.sourcing.models_v2", "lemouton.multitenancy.models",
        "lemouton.audit.models", "lemouton.mapping.models",
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


def _seed_account():
    from shared.db import SessionLocal
    from lemouton.multitenancy.models import MarketAccount
    s = SessionLocal()
    try:
        name = "속도테스트계정"
        a = s.query(MarketAccount).filter_by(market="smartstore",
                                             account_name=name).first()
        if a is None:
            a = MarketAccount(market="smartstore", account_name=name,
                              credentials_encrypted="x", is_active=True)
            s.add(a)
            s.commit()
        return a.id
    finally:
        s.close()


def test_list_returns_accounts_and_totals(client):
    _seed_account()
    r = client.get("/api/upload/account-speed")
    assert r.status_code == 200
    d = r.get_json()
    assert any(a["account_name"] == "속도테스트계정" for a in d["accounts"])
    assert "smartstore" in d["market_totals"]
    assert d["market_totals"]["smartstore"] >= 600   # 기본 6초 = 600/시간


def test_set_seconds_returns_per_hour(client):
    acc_id = _seed_account()
    r = client.post("/api/upload/account-speed",
                    json={"account_id": acc_id, "seconds_per_item": 4})
    assert r.status_code == 200
    d = r.get_json()
    assert d["ok"] is True
    assert d["seconds_per_item"] == 4
    assert d["per_hour"] == 900          # 3600/4


def test_seconds_clamped_min_1(client):
    acc_id = _seed_account()
    r = client.post("/api/upload/account-speed",
                    json={"account_id": acc_id, "seconds_per_item": 0})
    assert r.status_code == 200
    assert r.get_json()["seconds_per_item"] == 1


def test_missing_account_id_400(client):
    r = client.post("/api/upload/account-speed", json={"seconds_per_item": 5})
    assert r.status_code == 400


def test_unknown_account_404(client):
    r = client.post("/api/upload/account-speed",
                    json={"account_id": 999999, "seconds_per_item": 5})
    assert r.status_code == 404
