# -*- coding: utf-8 -*-
"""최근 3주 상태·송장 최신화 — 미확정 날짜만 골라 재확인.

사장님 기준(2026-07-24): 보통 3주 안에 구매확정·클레임으로 바뀌므로 최근 21일의
주문상태·송장번호가 늘 최신이어야 한다. 스스·롯데온은 하루씩만 조회되므로
'아직 안 끝난 건이 남은 날짜'만 다시 본다.
"""
import datetime as _dt

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from lemouton.markets import order_store as _store
from lemouton.markets.models_orders import Base, MarketOrderLine


@pytest.fixture()
def session():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()


def _line(s, uid, market, date, status, seen_days_ago=0):
    s.add(MarketOrderLine(
        line_uid=uid, market=market, order_no=uid, order_date=date + " 10:00:00",
        status=status, account="계정", row={"주문상태": status},
        first_seen_at=_dt.datetime(2026, 7, 1),
        last_seen_at=_dt.datetime(2026, 7, 24) - _dt.timedelta(days=seen_days_ago)))
    s.commit()


def test_끝난_주문만_있는_날짜는_안_고른다(session):
    """구매확정·취소완료만 남은 날은 값이 더 안 바뀐다 — 다시 부를 이유가 없다."""
    _line(session, "a1", "smartstore", "2026-07-10", "구매확정")
    _line(session, "a2", "smartstore", "2026-07-10", "취소완료")
    got = _store.open_order_dates("smartstore", since="2026-07-03",
                                  until="2026-07-24", session=session)
    assert got == []


def test_안_끝난_건이_하나라도_있으면_그_날짜를_고른다(session):
    _line(session, "b1", "smartstore", "2026-07-11", "구매확정")
    _line(session, "b2", "smartstore", "2026-07-11", "배송중")
    got = _store.open_order_dates("smartstore", since="2026-07-03",
                                  until="2026-07-24", session=session)
    assert got == ["2026-07-11"]


def test_배송완료는_아직_안_끝난_것으로_본다(session):
    """배송완료 다음에 구매확정으로 한 번 더 바뀐다 — 여기서 끊으면 그 변화를 놓친다."""
    _line(session, "c1", "smartstore", "2026-07-12", "배송완료")
    got = _store.open_order_dates("smartstore", since="2026-07-03",
                                  until="2026-07-24", session=session)
    assert got == ["2026-07-12"]


def test_오래_안_본_날짜부터_준다(session):
    """한 틱에 몇 개만 처리해도 다음 틱이 나머지를 이어받아야 굶는 날짜가 없다."""
    _line(session, "d1", "smartstore", "2026-07-13", "배송중", seen_days_ago=1)
    _line(session, "d2", "smartstore", "2026-07-14", "배송중", seen_days_ago=5)
    _line(session, "d3", "smartstore", "2026-07-15", "배송중", seen_days_ago=3)
    got = _store.open_order_dates("smartstore", since="2026-07-03",
                                  until="2026-07-24", session=session)
    assert got == ["2026-07-14", "2026-07-15", "2026-07-13"]


def test_한_틱_처리량을_제한한다(session):
    _line(session, "e1", "smartstore", "2026-07-13", "배송중", seen_days_ago=1)
    _line(session, "e2", "smartstore", "2026-07-14", "배송중", seen_days_ago=5)
    got = _store.open_order_dates("smartstore", since="2026-07-03",
                                  until="2026-07-24", limit=1, session=session)
    assert got == ["2026-07-14"]


def test_3주_밖은_안_고른다(session):
    """3주가 지나면 거의 확정된다 — 무한정 되돌아보지 않는다."""
    _line(session, "f1", "smartstore", "2026-06-01", "배송중")
    got = _store.open_order_dates("smartstore", since="2026-07-03",
                                  until="2026-07-24", session=session)
    assert got == []


def test_다른_마켓_날짜는_안_섞인다(session):
    _line(session, "g1", "lotteon", "2026-07-16", "배송중")
    got = _store.open_order_dates("smartstore", since="2026-07-03",
                                  until="2026-07-24", session=session)
    assert got == []
