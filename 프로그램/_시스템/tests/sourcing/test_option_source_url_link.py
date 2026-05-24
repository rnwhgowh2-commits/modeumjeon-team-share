"""옵션 ↔ 소싱처 URL N:N 매핑 (OptionSourceUrlLink) 데이터 무결성 테스트.

2026-05-24 — D안 (URL 마스터 + 옵션 종속) 구현 검증.
핵심:
  - UNIQUE(option, url) — 중복 매핑 차단
  - URL 삭제 시 매핑 CASCADE
  - 옵션 삭제 시 매핑 CASCADE
  - BundleSourceUrl.label nullable
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from shared.db import Base

# create_all 이 모든 FK 타겟 테이블을 찾도록 전체 모델 등록
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


@pytest.fixture
def db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = Session(eng)
    # SQLite 의 FK CASCADE 활성화 (기본 OFF)
    from sqlalchemy import text
    s.execute(text("PRAGMA foreign_keys=ON"))
    s.add(M.Model(model_code="AF", model_name_raw="에어포스"))
    s.add(M.Option(canonical_sku="AF-블랙-260", model_code="AF",
                   color_code="블랙", size_code="260"))
    s.add(M.Option(canonical_sku="AF-블랙-270", model_code="AF",
                   color_code="블랙", size_code="270"))
    s.add(M.Option(canonical_sku="AF-화이트-260", model_code="AF",
                   color_code="화이트", size_code="260"))
    s.commit()
    yield s
    s.close()


def test_url_label_nullable(db):
    """BundleSourceUrl.label 은 선택 입력 (nullable)."""
    u = M.BundleSourceUrl(model_code="AF", source_key="musinsa",
                          url="https://musinsa.com/x", sort_order=0)
    db.add(u)
    db.commit()
    assert u.label is None
    u.label = "통합 모음전"
    db.commit()
    assert db.query(M.BundleSourceUrl).first().label == "통합 모음전"


def test_n_to_n_mapping(db):
    """한 옵션 ↔ 한 소싱처 안에서 URL 여러개 매핑 가능 (시연 시나리오)."""
    u1 = M.BundleSourceUrl(model_code="AF", source_key="musinsa",
                           url="https://musinsa.com/all", label="통합", sort_order=0)
    u2 = M.BundleSourceUrl(model_code="AF", source_key="musinsa",
                           url="https://musinsa.com/black", label="블랙 단품", sort_order=1)
    db.add_all([u1, u2])
    db.flush()
    # AF-블랙-260 옵션이 두 URL 에 모두 매핑
    db.add(M.OptionSourceUrlLink(option_canonical_sku="AF-블랙-260",
                                 bundle_source_url_id=u1.id))
    db.add(M.OptionSourceUrlLink(option_canonical_sku="AF-블랙-260",
                                 bundle_source_url_id=u2.id))
    db.commit()
    links = db.query(M.OptionSourceUrlLink).filter_by(
        option_canonical_sku="AF-블랙-260").all()
    assert len(links) == 2


def test_unique_constraint_blocks_duplicate(db):
    """같은 (옵션, URL) 중복 매핑 시 UNIQUE 위반."""
    u = M.BundleSourceUrl(model_code="AF", source_key="musinsa",
                          url="https://musinsa.com/x", sort_order=0)
    db.add(u); db.flush()
    db.add(M.OptionSourceUrlLink(option_canonical_sku="AF-블랙-260",
                                 bundle_source_url_id=u.id))
    db.commit()
    # 중복 INSERT 시도
    db.add(M.OptionSourceUrlLink(option_canonical_sku="AF-블랙-260",
                                 bundle_source_url_id=u.id))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_url_delete_cascades_links(db):
    """URL 삭제 시 매핑 자동 삭제 (CASCADE)."""
    u = M.BundleSourceUrl(model_code="AF", source_key="musinsa",
                          url="https://musinsa.com/x", sort_order=0)
    db.add(u); db.flush()
    db.add_all([
        M.OptionSourceUrlLink(option_canonical_sku="AF-블랙-260",
                              bundle_source_url_id=u.id),
        M.OptionSourceUrlLink(option_canonical_sku="AF-블랙-270",
                              bundle_source_url_id=u.id),
    ])
    db.commit()
    assert db.query(M.OptionSourceUrlLink).count() == 2
    db.delete(u)
    db.commit()
    assert db.query(M.OptionSourceUrlLink).count() == 0


def test_option_delete_cascades_links(db):
    """옵션 삭제 시 매핑 자동 삭제 (CASCADE)."""
    u = M.BundleSourceUrl(model_code="AF", source_key="musinsa",
                          url="https://musinsa.com/x", sort_order=0)
    db.add(u); db.flush()
    db.add(M.OptionSourceUrlLink(option_canonical_sku="AF-블랙-260",
                                 bundle_source_url_id=u.id))
    db.commit()
    opt = db.query(M.Option).filter_by(canonical_sku="AF-블랙-260").first()
    db.delete(opt)
    db.commit()
    assert db.query(M.OptionSourceUrlLink).count() == 0


def test_mapping_relationship_backref(db):
    """BundleSourceUrl.option_links relationship 동작."""
    u = M.BundleSourceUrl(model_code="AF", source_key="musinsa",
                          url="https://musinsa.com/x", sort_order=0)
    db.add(u); db.flush()
    db.add_all([
        M.OptionSourceUrlLink(option_canonical_sku="AF-블랙-260",
                              bundle_source_url_id=u.id),
        M.OptionSourceUrlLink(option_canonical_sku="AF-화이트-260",
                              bundle_source_url_id=u.id),
    ])
    db.commit()
    db.refresh(u)
    assert len(u.option_links) == 2
    skus = sorted(ln.option_canonical_sku for ln in u.option_links)
    assert skus == ["AF-블랙-260", "AF-화이트-260"]
