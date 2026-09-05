# -*- coding: utf-8 -*-
"""settle_status.attach_settlement_status — 「정산여부」+「주문상태이력」 부착.

실제 DB(SQLite 인메모리)에 주문 라인 + 클레임을 채우고, 마진계산기 matched 행에
그 결과가 제대로 붙는지 확인한다(가짜 dict 만 넣는 단위시험은 실제 조회 경로가
비어 있어도 통과한다 — test_settle_plan_lines_includes_claims.py 가 겪은 함정과 동일).
"""
import datetime as dt

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from lemouton.margin import settle_status as SS
from lemouton.markets import line_uid as L


@pytest.fixture
def session(monkeypatch):
    from shared.db import Base
    import lemouton.markets.models_orders  # noqa: F401 — 테이블 등록

    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng, tables=[
        Base.metadata.tables["market_order_lines"],
        Base.metadata.tables["market_claim_events"],
    ])
    Session = sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)
    s = Session()
    # order_store.lines_for_markets 는 session 을 안 받으면 shared.db.SessionLocal() 을
    #  스스로 연다 — 그 자리를 인메모리 세션으로 바꿔치기한다.
    import shared.db as _db
    monkeypatch.setattr(_db, "SessionLocal", lambda: s)
    yield s
    s.close()


def _seed_line(session, *, order_no, status, market="coupang", days_ago=1,
               settle_paid_date="", status_prev="", status_at=None):
    from lemouton.markets.models_orders import MarketOrderLine
    order_date = (dt.date.today() - dt.timedelta(days=days_ago)).isoformat()
    row = {"오픈마켓주문번호": order_no, "주문일": f"{order_date} 10:00:00",
           "주문상태": status, "쇼핑몰별칭": "브랜드마켓", "상품명": "테스트상품"}
    if settle_paid_date:
        row["_settle_paid_date"] = settle_paid_date
    obj = MarketOrderLine(
        line_uid=f"{market}|{order_no}|1", market=market, order_no=order_no,
        order_date=f"{order_date} 10:00:00", status=status, account="",
        row=row, status_prev=status_prev, status_at=status_at)
    session.add(obj)
    session.commit()


def _seed_claim(session, *, order_no, status, market="coupang", days_ago=5):
    from lemouton.markets.models_orders import MarketClaimEvent
    order_date = (dt.date.today() - dt.timedelta(days=days_ago)).isoformat()
    row = {"오픈마켓주문번호": order_no, "주문상태": status, "_kind": "change",
           "_change_date": order_date}
    obj = MarketClaimEvent(
        event_uid=f"{market}|{order_no}|clm|{status}", line_uid=f"{market}|{order_no}|1",
        market=market, order_no=order_no, changed_at=order_date, status=status,
        row=row)
    session.add(obj)
    session.commit()


def test_실제_입금일이_있으면_O(session):
    _seed_line(session, order_no="O1", status="구매확정", market="coupang",
              settle_paid_date="2026-09-03")
    matched = [{"마켓": "쿠팡", "마켓주문번호": "O1"}]
    SS.attach_settlement_status(matched, today=dt.date(2026, 9, 5))
    assert matched[0]["정산여부"] == "O"


def test_입금일_없으면_확인불가(session):
    _seed_line(session, order_no="O2", status="배송완료", market="coupang")
    matched = [{"마켓": "쿠팡", "마켓주문번호": "O2"}]
    SS.attach_settlement_status(matched, today=dt.date(2026, 9, 5))
    assert matched[0]["정산여부"] == "확인불가"


def test_클레임이_아직_안_끝나면_진행중(session):
    _seed_line(session, order_no="O3", status="배송완료", market="coupang", days_ago=10)
    _seed_claim(session, order_no="O3", status="취소요청", market="coupang", days_ago=3)
    matched = [{"마켓": "쿠팡", "마켓주문번호": "O3"}]
    SS.attach_settlement_status(matched, today=dt.date(2026, 9, 5))
    assert matched[0]["정산여부"] == "진행중"


def test_취소요청_이후_입금일이_찍히면_이력에_둘_다_남고_O(session):
    """사장님 예시: 취소요청('26.08.30) → 정산완료('26.09.03)."""
    _seed_line(session, order_no="O4", status="배송완료", market="lotteon",
              settle_paid_date="2026-09-03")
    _seed_claim(session, order_no="O4", status="취소요청", market="lotteon", days_ago=6)
    matched = [{"마켓": "롯데ON", "마켓주문번호": "O4"}]
    SS.attach_settlement_status(matched, today=dt.date(2026, 9, 5))
    assert matched[0]["정산여부"] == "O"
    statuses = [e["status"] for e in matched[0]["_주문상태이력"]]
    assert statuses == ["취소요청", "배송완료"]


def test_해당하는_주문이_없으면_확인불가_기본값(session):
    matched = [{"마켓": "쿠팡", "마켓주문번호": "없는주문"}]
    SS.attach_settlement_status(matched, today=dt.date(2026, 9, 5))
    assert matched[0]["정산여부"] == "확인불가"
    assert matched[0]["_주문상태이력"] == []


def test_11번가는_입금채널이_없어_확인불가지만_진행중은_그대로_잡는다(session):
    """11번가·옥션·G마켓은 「O」 근거(_settle_paid_date)가 절대 안 채워지는 마켓일 뿐,
    반품·취소가 마켓에서도 아직 안 끝난 「진행중」은 똑같이 잡아야 한다."""
    _seed_line(session, order_no="O9", status="배송완료", market="eleven11", days_ago=10)
    _seed_claim(session, order_no="O9", status="취소요청", market="eleven11", days_ago=3)
    matched = [{"마켓": "11번가", "마켓주문번호": "O9"}]
    SS.attach_settlement_status(matched, today=dt.date(2026, 9, 5))
    assert matched[0]["정산여부"] == "진행중"


def test_주문내역_스타일_행_판매처_오픈마켓주문번호_필드명도_작동한다(session):
    """주문내역 탭은 '마켓'·'마켓주문번호'가 아니라 '판매처'·'오픈마켓주문번호'를 쓴다 —
    같은 함수가 두 화면 어느 쪽 필드명이든 받아야 판정이 갈리지 않는다."""
    _seed_line(session, order_no="O5", status="구매확정", market="coupang",
              settle_paid_date="2026-09-03")
    rows = [{"판매처": "쿠팡", "오픈마켓주문번호": "O5"}]
    SS.attach_settlement_status(rows, today=dt.date(2026, 9, 5))
    assert rows[0]["정산여부"] == "O"


def test_order_nos로_좁혀_읽는다_전체_스캔_금지(session, monkeypatch):
    """🔴 2026-09-05 라이브 실측 — order_nos 로 안 좁히면 analyze() 마다 마켓 180일
    전체 + 클레임 무제한을 통째로 읽어(매칭 3,499건에 50초) Cloudflare 100초 상한에
    근접했다. order_nos 를 반드시 넘겨야 한다(안 넘기면 이 시험이 잡는다)."""
    _seed_line(session, order_no="O6", status="배송완료", market="coupang")
    from lemouton.markets import order_store as _store
    captured = {}
    orig = _store.lines_for_markets
    def _spy(*a, **kw):
        captured.update(kw)
        return orig(*a, **kw)
    monkeypatch.setattr(_store, "lines_for_markets", _spy)

    matched = [{"마켓": "쿠팡", "마켓주문번호": "O6"}]
    SS.attach_settlement_status(matched, today=dt.date(2026, 9, 5))
    assert captured.get("order_nos") == ["O6"], (
        "settle_status 가 order_nos 를 안 넘긴다 — 마켓 전체를 읽는 느린 경로로 되돌아갔다")
