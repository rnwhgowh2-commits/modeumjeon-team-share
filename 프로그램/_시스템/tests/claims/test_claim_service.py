# -*- coding: utf-8 -*-
"""CS 클레임 처리상태 모델·서비스."""
import datetime as dt
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from shared.db import Base


@pytest.fixture()
def session():
    import lemouton.claims.models  # 모델 등록
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    S = sessionmaker(bind=eng)
    s = S()
    yield s
    s.close()


def test_claim_handling_table_created(session):
    from lemouton.claims.models import ClaimHandling
    row = ClaimHandling(claim_key="롯데온:LO1:반품", market="롯데온", order_no="LO1", claim_type="반품")
    session.add(row); session.commit()
    got = session.query(ClaimHandling).filter_by(claim_key="롯데온:LO1:반품").one()
    assert got.acknowledged_at is None and got.memo is None
