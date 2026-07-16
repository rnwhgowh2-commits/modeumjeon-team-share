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


def test_normalize_and_list(session, monkeypatch):
    from lemouton.cs_inquiries import service as isv
    import datetime as dt
    KST = dt.timezone(dt.timedelta(hours=9))
    now = dt.datetime(2026, 7, 16, 12, tzinfo=KST)
    def fake_fetch(market, since, until, status):
        if market == "coupang":
            return [{"마켓":"쿠팡","문의형태":"온라인문의","문의ID":"CQ1","고객":"박지훈","상품":"키트",
                     "문의내용":"교환되나요","일시":"2026-07-16 08:05","상태":"미답변","답변내용":""}]
        if market == "smartstore":
            return [{"마켓":"스마트스토어","문의형태":"상품문의","문의ID":"SQ9","고객":"오세훈","상품":"티셔츠",
                     "문의내용":"남녀공용?","일시":"2026-07-05 11:05","상태":"답변완료","답변내용":"네 공용입니다","답변일":"20260705"}]
        raise RuntimeError("미지원")
    monkeypatch.setattr(isv, "_fetch_market", fake_fetch)
    res = isv.list_inquiries(["coupang","smartstore","lotteon"], since=now, until=now, now=now, session=session)
    assert [q["문의ID"] for q in res["groups"]["미답변"]] == ["CQ1"]
    assert res["groups"]["답변완료"] == []   # SQ9 답변일 07-05 = 11일전 → 7일 필터 숨김
    assert any("연동 준비 중" in w for w in res["warnings"])   # lotteon 미지원
