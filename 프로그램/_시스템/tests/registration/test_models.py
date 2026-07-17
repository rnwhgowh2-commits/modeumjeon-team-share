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


def test_draft_market_unique_per_market_account(session):
    """같은 드래프트 + 같은 마켓 + 같은 계정 = 2행 금지 (동일 계정 재등록 차단)."""
    d = ProductDraft(name='상품', sale_price=10000)
    session.add(d)
    session.commit()
    session.add(ProductDraftMarket(draft_id=d.id, market='smartstore', account_key='acct_a'))
    session.commit()
    session.add(ProductDraftMarket(draft_id=d.id, market='smartstore', account_key='acct_a'))
    with pytest.raises(IntegrityError):
        session.commit()


def test_draft_market_allows_other_account(session):
    """같은 드래프트 + 같은 마켓 + 다른 계정 = 허용 (타 계정 별도 등록).

    계정별로 마켓 상품번호가 다르므로 각 행이 살아있어야 한다 — 덮어쓰기 = 금전 손실.
    """
    d = ProductDraft(name='상품', sale_price=10000)
    session.add(d)
    session.commit()
    session.add(ProductDraftMarket(draft_id=d.id, market='smartstore',
                                   account_key='acct_a', market_product_id='111'))
    session.add(ProductDraftMarket(draft_id=d.id, market='smartstore',
                                   account_key='acct_b', market_product_id='222'))
    session.commit()

    rows = session.query(ProductDraftMarket).filter_by(draft_id=d.id,
                                                       market='smartstore').all()
    assert len(rows) == 2
    assert {r.account_key for r in rows} == {'acct_a', 'acct_b'}
    # 계정별 마켓 상품번호가 각각 보존됐는지 (덮어쓰기 없음)
    assert {r.market_product_id for r in rows} == {'111', '222'}


def test_draft_market_account_key_defaults(session):
    """account_key 미지정 = 'default' 센티넬 (Phase 1A 단일계정 경로)."""
    d = ProductDraft(name='상품', sale_price=10000)
    session.add(d)
    session.commit()
    m = ProductDraftMarket(draft_id=d.id, market='smartstore')
    session.add(m)
    session.commit()
    assert m.account_key == 'default'


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
