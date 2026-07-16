# -*- coding: utf-8 -*-
import datetime as dt
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from shared.db import Base


@pytest.fixture()
def session():
    import lemouton.cs_inquiries.models
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()


def test_inquiry_handling_table(session):
    from lemouton.cs_inquiries.models import InquiryHandling
    row = InquiryHandling(inquiry_key="쿠팡:Q1", market="쿠팡")
    session.add(row); session.commit()
    assert session.query(InquiryHandling).filter_by(inquiry_key="쿠팡:Q1").one().dismissed_at is None
