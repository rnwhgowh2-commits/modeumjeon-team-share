# -*- coding: utf-8 -*-
"""AI 카테고리·태그 매핑 보류함 — 확신 낮은 것만 쌓인다.

🔴 이 파일이 지키는 것: **확신이 없으면 자동으로 넣지 않는다.** 엉뚱한 카테고리로
   올리면 노출이 죽고 마켓 제재 대상이 된다(프로젝트 최상위 원칙 — 지어내지 않는다).
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shared.db import Base
from lemouton.policy import models as PM  # noqa: F401 — 테이블 등록
from lemouton.policy.models import CategoryMappingReview


@pytest.fixture()
def db():
    eng = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()


def test_보류_항목을_쌓고_읽는다(db):
    db.add(CategoryMappingReview(
        product_id='LM-2024', market='coupang',
        ai_suggestion='패션잡화 > 운동화', confidence=0.62))
    db.commit()

    got = db.query(CategoryMappingReview).one()
    assert got.status == 'pending'
    assert got.confidence == pytest.approx(0.62)
    assert got.resolved_value is None


def test_확정하면_상태와_값이_남는다(db):
    row = CategoryMappingReview(product_id='LM-2024', market='coupang',
                                ai_suggestion='패션잡화 > 운동화', confidence=0.62)
    db.add(row)
    db.commit()

    row.status = 'confirmed'
    row.resolved_value = '패션잡화 > 운동화'
    db.commit()

    got = db.query(CategoryMappingReview).one()
    assert got.status == 'confirmed'
    assert got.resolved_value == '패션잡화 > 운동화'


def test_고치면_AI_추천과_다른_값이_남는다(db):
    """🔴 AI 추천을 덮어쓰지 않는다 — 나중에 「AI 가 뭘 틀렸나」를 세려면 둘 다 있어야 한다."""
    row = CategoryMappingReview(product_id='LM-2024', market='coupang',
                                ai_suggestion='패션잡화 > 운동화', confidence=0.58)
    db.add(row)
    db.commit()

    row.status = 'corrected'
    row.resolved_value = '패션잡화 > 스니커즈'
    db.commit()

    got = db.query(CategoryMappingReview).one()
    assert got.ai_suggestion == '패션잡화 > 운동화'   # 원본 보존
    assert got.resolved_value == '패션잡화 > 스니커즈'


def test_상품번호로_찾을_수_있다(db):
    db.add_all([
        CategoryMappingReview(product_id='A', market='coupang', confidence=0.5),
        CategoryMappingReview(product_id='A', market='smartstore', confidence=0.5),
        CategoryMappingReview(product_id='B', market='coupang', confidence=0.5),
    ])
    db.commit()

    assert db.query(CategoryMappingReview).filter_by(product_id='A').count() == 2
