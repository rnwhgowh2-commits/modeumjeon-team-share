# -*- coding: utf-8 -*-
"""쿠팡 브랜드 판별 캐시.

🔴 이 파일이 지키는 것: **「모른다」와 「아니다」를 가른다.** uid_required 가 None 인
   것은 판정 못 한 것이지 「소명 필요 없음」이 아니다. 기본값을 판정으로 읽으면
   소명 대상 브랜드가 그대로 올라가 계정이 정지된다.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from shared.db import Base
from lemouton.policy import models as PM  # noqa: F401 — 테이블 등록
from lemouton.policy.models import BrandRegistryCache


@pytest.fixture()
def db():
    eng = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()


def test_판별_결과를_저장하고_읽는다(db):
    db.add(BrandRegistryCache(brand='나이키', coupang_brand_id='B123',
                              uid_required=True, matched=True))
    db.commit()

    got = db.query(BrandRegistryCache).one()
    assert got.coupang_brand_id == 'B123'
    assert got.uid_required is True
    assert got.matched is True


def test_판정_못한_브랜드는_None_이다(db):
    """🔴 None 은 「소명 필요 없음(False)」이 아니다 — 정확히 「모름」이다."""
    db.add(BrandRegistryCache(brand='듣보브랜드', matched=False))
    db.commit()

    got = db.query(BrandRegistryCache).one()
    assert got.uid_required is None
    assert got.matched is False
    assert got.uid_required is not False   # 「모름」을 「아니다」로 읽으면 안 된다


def test_브랜드는_한_번만_들어간다(db):
    db.add(BrandRegistryCache(brand='나이키', matched=True))
    db.commit()
    db.add(BrandRegistryCache(brand='나이키', matched=True))
    with pytest.raises(IntegrityError):
        db.commit()


def test_자유판매_브랜드도_기록된다(db):
    db.add(BrandRegistryCache(brand='르무통', coupang_brand_id='B999',
                              uid_required=False, matched=True))
    db.commit()

    got = db.query(BrandRegistryCache).one()
    assert got.uid_required is False
    assert got.coupang_brand_id == 'B999'
