# -*- coding: utf-8 -*-
"""[TEST] /api/admin/option-dupes 중복 진단 — keeper/삭제후보 판정 (2026-06-13).

스카이블루 처럼 같은 (model,color,size) 가 2행일 때:
  - 활성+매핑 있는 행을 'keeper'(보존)로,
  - 잉여 + 매핑 0 인 행을 '안전 삭제후보'로 식별해야 한다.
삭제 대상 결정이라 로직을 영구 잠근다. (격리 in-memory DB + SessionLocal 패치)
"""
import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("ENVIRONMENT", "test")

_TEST_MODEL = "ZZ_DUPE_TEST"


@pytest.fixture
def client_with_dupe(monkeypatch):
    for _m in (
        "lemouton.sourcing.models", "lemouton.sourcing.models_pricing",
        "lemouton.sources.models", "lemouton.templates.models",
        "lemouton.inventory.models", "lemouton.multitenancy.models",
        "lemouton.audit.models", "lemouton.mapping.models",
    ):
        try:
            __import__(_m)
        except ImportError:
            pass
    from shared.db import Base
    import lemouton.sourcing.models as M

    # 격리 in-memory DB (StaticPool → 여러 세션이 같은 DB 공유)
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    Base.metadata.create_all(eng)
    TestSession = sessionmaker(bind=eng)

    s = TestSession()
    s.add(M.Option(canonical_sku="ZZ-keep", model_code=_TEST_MODEL,
                   color_code="스카이블루", size_code="220", is_active=True))
    s.add(M.Option(canonical_sku="ZZ-dupe", model_code=_TEST_MODEL,
                   color_code="스카이블루", size_code="220", is_active=False))
    # 중복 아닌 단일 옵션(대조군)
    s.add(M.Option(canonical_sku="ZZ-solo", model_code=_TEST_MODEL,
                   color_code="블랙", size_code="230", is_active=True))
    s.commit()
    s.close()

    # 엔드포인트가 쓰는 SessionLocal 을 테스트 세션으로 교체
    import webapp.routes.bundles as B
    monkeypatch.setattr(B, "SessionLocal", TestSession)

    from flask import Flask
    app = Flask(__name__)
    app.register_blueprint(B.bp)
    app.config.update(TESTING=True)
    return app.test_client()


def test_dupe_detected_and_safe_delete(client_with_dupe):
    d = client_with_dupe.get("/api/admin/option-dupes?format=json").get_json()
    assert d["ok"] is True
    # 중복군은 (스카이블루,220) 하나만 — solo(블랙,230)는 안 잡혀야 함
    assert d["dup_group_count"] == 1
    grp = d["groups"][0]
    assert grp["color_code"] == "스카이블루" and grp["size_code"] == "220"
    assert len(grp["rows"]) == 2
    keeper = [r for r in grp["rows"] if r["keeper"]]
    deletable = [r for r in grp["rows"] if r["deletable"]]
    # 활성 행 보존, 비활성+매핑0 행이 삭제후보
    assert len(keeper) == 1 and keeper[0]["sku"] == "ZZ-keep"
    assert len(deletable) == 1 and deletable[0]["sku"] == "ZZ-dupe"
    assert d["safe_delete_skus"] == ["ZZ-dupe"]


def test_html_renders(client_with_dupe):
    r = client_with_dupe.get("/api/admin/option-dupes")
    assert r.status_code == 200
    assert r.mimetype == "text/html"
    assert "스카이블루".encode() in r.data
