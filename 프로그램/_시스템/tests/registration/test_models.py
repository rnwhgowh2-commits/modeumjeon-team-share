# -*- coding: utf-8 -*-
"""ProductDraft / ProductDraftMarket — 스키마·기본값·제약."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import IntegrityError

from shared.db import Base
from lemouton.registration.models import ProductDraft, ProductDraftMarket


@pytest.fixture
def session():
    engine = create_engine('sqlite://', future=True)
    Base.metadata.create_all(engine)
    S = sessionmaker(bind=engine, future=True)
    s = S()
    yield s
    s.close()


def test_draft_defaults(session):
    """origin 기본 'bulk', status 기본 'draft', 업데이트 플래그 기본 켜짐."""
    d = ProductDraft(name='테스트 상품', sale_price=75800)
    session.add(d)
    session.commit()
    assert d.id is not None
    assert d.origin == 'bulk'
    assert d.source == 'manual'
    assert d.status == 'draft'
    assert d.update_price is True
    assert d.update_stock is True
    assert d.created_at is not None


def test_draft_market_unique_per_market(session):
    """같은 드래프트에 같은 마켓 2행 금지."""
    d = ProductDraft(name='상품', sale_price=10000)
    session.add(d)
    session.commit()
    session.add(ProductDraftMarket(draft_id=d.id, market='smartstore'))
    session.commit()
    session.add(ProductDraftMarket(draft_id=d.id, market='smartstore'))
    with pytest.raises(IntegrityError):
        session.commit()


def test_draft_market_defaults(session):
    """등록 결과 기본 상태 = pending."""
    d = ProductDraft(name='상품', sale_price=10000)
    session.add(d)
    session.commit()
    m = ProductDraftMarket(draft_id=d.id, market='coupang')
    session.add(m)
    session.commit()
    assert m.status == 'pending'
    assert m.market_product_id is None
    assert m.error_message is None
