"""tests/sourcing/test_option_source_service.py — 옵션 소싱처 URL 다중 (Phase 3).

ai-workflow cycle 20260521 — in-memory SQLite 통합 테스트.
핵심: 한 소싱처에 URL 여러 개 (UniqueConstraint 제거 검증).
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from shared.db import Base

# create_all 이 모든 FK 타겟 테이블을 찾도록 전체 모델 등록 (app.py 와 동일)
for _m in (
    "lemouton.sourcing.models", "lemouton.sourcing.models_pricing",
    "lemouton.sourcing.models_v2", "lemouton.pricing.settings",
    "lemouton.uploader.models", "lemouton.templates.models",
    "lemouton.inventory.models", "lemouton.sources.models",
    "lemouton.multitenancy.models", "lemouton.audit.models",
    "lemouton.mapping.models",
):
    try:
        __import__(_m)
    except ImportError:
        pass

import lemouton.sourcing.models as M
from lemouton.sourcing.models_pricing import SourceRegistry
from lemouton.sourcing.option_source_service import (
    add_source_url, list_source_urls, count_urls_by_source, delete_source_url,
)


@pytest.fixture
def db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = Session(eng)
    s.add(M.Model(model_code="AF", model_name_raw="에어포스"))
    s.add(M.Option(canonical_sku="AF-블랙-260", model_code="AF",
                   color_code="블랙", size_code="260"))
    s.add(SourceRegistry(id=1, name="무신사"))
    s.add(SourceRegistry(id=2, name="SSF"))
    s.commit()
    yield s
    s.close()


def test_multiple_urls_same_source(db):
    # Phase 3 핵심 — 한 소싱처(무신사)에 URL 2개 (UniqueConstraint 제거 검증)
    add_source_url(db, "AF-블랙-260", 1, "https://musinsa.com/a")
    add_source_url(db, "AF-블랙-260", 1, "https://musinsa.com/b")
    db.commit()
    assert len(list_source_urls(db, "AF-블랙-260")) == 2


def test_multiple_sources(db):
    add_source_url(db, "AF-블랙-260", 1, "https://musinsa.com/a")
    add_source_url(db, "AF-블랙-260", 2, "https://ssf.com/x")
    db.commit()
    assert count_urls_by_source(db, "AF-블랙-260") == {1: 1, 2: 1}


def test_count_by_source_multi(db):
    add_source_url(db, "AF-블랙-260", 1, "u1")
    add_source_url(db, "AF-블랙-260", 1, "u2")
    add_source_url(db, "AF-블랙-260", 2, "u3")
    db.commit()
    assert count_urls_by_source(db, "AF-블랙-260") == {1: 2, 2: 1}


def test_delete_url(db):
    r1 = add_source_url(db, "AF-블랙-260", 1, "u1")
    add_source_url(db, "AF-블랙-260", 1, "u2")
    db.commit()
    delete_source_url(db, r1.id)
    db.commit()
    assert len(list_source_urls(db, "AF-블랙-260")) == 1
