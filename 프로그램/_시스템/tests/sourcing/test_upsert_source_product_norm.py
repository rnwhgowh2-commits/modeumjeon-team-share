"""[TEST] upsert_source_product 정규화 dedup (INV-2, 2026-06-13).

배경: upsert 가 raw URL 로 조회·저장 → 같은 상품이 utag/NaPm 같은 트래킹
      파라미터 차이만으로 SourceProduct 2행으로 분열(INV-2). 매트릭스는 정규화로
      매칭하므로 둘 중 하나를 임의 선택 → 값이 다르면 stale 픽 위험.
정책: 트래킹 파라미터만 다른 URL 은 같은 상품 = 1행. 의미있는 파라미터
      (ckwhere 등 normalize 가 보존)는 그대로 → 별도 상품 유지(가격 다름).
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from shared.db import Base

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

from lemouton.sources.models import SourceProduct
from lemouton.sources.service import upsert_source_product


@pytest.fixture
def db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = Session(eng)
    yield s
    s.close()


def _count(s):
    return s.query(SourceProduct).filter(SourceProduct.deleted_at.is_(None)).count()


def test_tracking_param_difference_dedups_to_one_row(db):
    # utag 트래킹만 다른 같은 SSF 상품 → 1행.
    base = "https://www.ssfshop.com/LEMOUTON/GRG424102517741/good"
    a = upsert_source_product(db, site="ssf", url=base + "?utag=ref_sch:x$set:1")
    b = upsert_source_product(db, site="ssf", url=base)
    db.commit()
    assert a.id == b.id
    assert _count(db) == 1


def test_napm_tracking_dedups(db):
    base = "https://brand.naver.com/lemouton/products/9496367527"
    a = upsert_source_product(db, site="ss_lemouton", url=base + "?NaPm=ct%3Dx")
    b = upsert_source_product(db, site="ss_lemouton", url=base)
    db.commit()
    assert a.id == b.id
    assert _count(db) == 1


def test_meaningful_param_kept_as_separate(db):
    # ckwhere(제휴 쿠폰가 노출 — normalize 가 보존)는 다른 상품으로 유지.
    base = "https://www.ssg.com/item/itemView.ssg?itemId=1000"
    a = upsert_source_product(db, site="ssg", url=base)
    b = upsert_source_product(db, site="ssg", url=base + "&ckwhere=ssg_naver")
    db.commit()
    assert a.id != b.id
    assert _count(db) == 2


def test_same_url_idempotent(db):
    url = "https://www.musinsa.com/products/3728480"
    a = upsert_source_product(db, site="musinsa", url=url)
    b = upsert_source_product(db, site="musinsa", url=url)
    db.commit()
    assert a.id == b.id
    assert _count(db) == 1
