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


def test_list_inquiries_defaults_window_when_no_dates(session, monkeypatch):
    from lemouton.cs_inquiries import service as isv
    seen = {}
    def fake_fetch(market, since, until, status):
        seen["since"], seen["until"] = since, until
        return []
    monkeypatch.setattr(isv, "_fetch_market", fake_fetch)
    res = isv.list_inquiries(["coupang"], since=None, until=None, session=session)   # 크래시 없어야
    assert res["groups"] == {"미답변": [], "답변완료": []}
    assert seen["since"] is not None and seen["until"] is not None   # 기본 창 채워짐
    assert (seen["until"] - seen["since"]).days == 7


def test_fetch_market_paginates_coupang(monkeypatch):
    from lemouton.cs_inquiries import service as isv
    import datetime as dt
    pages = {1: {"data": [{"inquiryId": str(i)} for i in range(50)]},
             2: {"data": [{"inquiryId": "x"}]}}
    monkeypatch.setattr(isv, "_cp_fetch", lambda since, until, **kw: pages[kw["page_num"]])
    rows = isv._fetch_market("coupang", dt.datetime(2026,7,10), dt.datetime(2026,7,16), "ALL")
    assert len(rows) == 51   # 50 + 1, stopped on short page


def test_dismiss_and_reply_preview(session, monkeypatch):
    from lemouton.cs_inquiries import service as isv
    from lemouton.cs_inquiries.models import InquiryHandling
    isv.dismiss_inquiry("쿠팡:CQ1", market="쿠팡", session=session)
    assert session.query(InquiryHandling).filter_by(inquiry_key="쿠팡:CQ1").one().dismissed_at is not None
    monkeypatch.setenv("LEMOUTON_LIVE_INQUIRY_REPLY", "")
    res = isv.reply_preview("coupang", "CQ1", "안녕하세요 답변드립니다")
    assert res["sent"] is False and "안녕하세요" in res["preview"]
