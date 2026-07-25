# -*- coding: utf-8 -*-
"""롯데온 정산 스윕 — 크롤 DB(라인 정밀) 우선 + scan 총액은 단품 주문에만.

🔴 왜 필요한가(2026-07-25 검수) — 롯데온 배송완료 453건이 추정치 고착.
★★ scan(itmd)은 **주문 총액**(odNo 합계)인데 저장은 **라인 단위** → 다품 주문에
그대로 쓰면 주문당 여러 번 계상된다. 그래서 단품 주문(저장 라인 1개)에만 itmd 를 쓰고,
다품은 라인 정밀 크롤 DB 가 있을 때만 채운다(없으면 추정 유지 → 경보가 드러냄).
"""
from __future__ import annotations

import datetime as _dt

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from lemouton.markets import line_uid as L
from lemouton.markets import order_ingest as OI
from lemouton.markets import order_store as OS

KST = _dt.timezone(_dt.timedelta(hours=9))


@pytest.fixture
def session():
    import lemouton.markets.models_orders  # noqa: F401
    import lemouton.sourcing.models_v2      # noqa: F401  — LotteonSettlement 테이블
    from shared.db import Base
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng, tables=[
        Base.metadata.tables["market_order_lines"],
        Base.metadata.tables["market_claim_events"],
        Base.metadata.tables["lotteon_settlements"],
    ])
    s = sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)()
    yield s
    s.close()


def _row(odno="O1", odseq="1", sitm="S1", **kw):
    uid = "lotteon|%s|%s|%s" % (odno, odseq, sitm)
    row = {L.FIELD: uid, "판매처": "롯데온", "쇼핑몰": "롯데온", "오픈마켓주문번호": odno,
           "주문일": "2026-06-01 10:00:00", "주문상태": "배송완료",
           "상품명": "보드숏", "단가": 44800, "수량": 1, "실결제금액": 44800, "배송비": 0,
           "정산예정금액": 43000, "_settle_source": "estimated",
           "_send_ids": {"od_no": odno, "od_seq": odseq, "sitm_no": sitm}}
    row.update(kw)
    return row


def _no_scan(monkeypatch, itmd=None):
    """scan API 를 막고(itmd 지정) 계정 1개로."""
    from lemouton.markets import order_export as OE
    monkeypatch.setattr(OE, "_active_accounts", lambda m: [(None, "대표")])
    monkeypatch.setattr(OE, "_account_client", lambda m, p=None: object())
    import shared.platforms.lotteon.settlement as _s
    monkeypatch.setattr(_s, "scan", lambda since, until, client=None:
                        ({k: {"pymtAmt": v} for k, v in (itmd or {}).items()}, {}))


def _add_crawl(session, od_no, od_seq, amt):
    from lemouton.sourcing.models_v2 import LotteonSettlement
    session.add(LotteonSettlement(od_no=od_no, od_seq=od_seq, pymt_tgt_amt=amt))
    session.commit()


def test_크롤DB_라인값을_최우선으로_쓴다(session, monkeypatch):
    OS.save([_row("O1", "1")], session=session)
    _add_crawl(session, "O1", "1", 43512)
    _no_scan(monkeypatch, itmd={"O1": 99999})   # itmd 있어도 크롤이 이긴다

    stat = OI.refresh_settlement_lotteon(session=session)

    assert stat["updated"] == 1
    stored = OS.load(["lotteon"], since="2000-01-01", until="2999-01-01",
                     session=session)[0]
    assert str(stored["정산예정금액"]) == "43512"
    assert stored["_settle_source"] == "real"


def test_단품주문은_scan총액을_쓴다(session, monkeypatch):
    OS.save([_row("O1", "1")], session=session)
    _no_scan(monkeypatch, itmd={"O1": 43512})

    stat = OI.refresh_settlement_lotteon(session=session)
    assert stat["updated"] == 1
    stored = OS.load(["lotteon"], since="2000-01-01", until="2999-01-01",
                     session=session)[0]
    assert str(stored["정산예정금액"]) == "43512"
    assert stored["_settle_source"] == "real"


def test_다품주문은_scan총액을_안_쓴다(session, monkeypatch):
    """★★ 핵심 안전장치 — 한 주문에 라인 2개인데 scan 은 주문 총액뿐이라, 그걸 각
    라인에 쓰면 주문당 2배 계상된다. 크롤 없으면 추정 유지(경보가 드러냄)."""
    OS.save([_row("O1", "1", "S1"), _row("O1", "2", "S2")], session=session)
    _no_scan(monkeypatch, itmd={"O1": 80000})

    stat = OI.refresh_settlement_lotteon(session=session)
    assert stat["updated"] == 0
    for r in OS.load(["lotteon"], since="2000-01-01", until="2999-01-01",
                     session=session):
        assert r["_settle_source"] == "estimated"


def test_다품이어도_크롤DB_라인값은_쓴다(session, monkeypatch):
    """다품 주문이라도 크롤 DB 는 라인 정밀이라 안전하게 쓴다."""
    OS.save([_row("O1", "1", "S1"), _row("O1", "2", "S2")], session=session)
    _add_crawl(session, "O1", "1", 30000)
    _add_crawl(session, "O1", "2", 25000)
    _no_scan(monkeypatch, itmd={"O1": 55000})

    OI.refresh_settlement_lotteon(session=session)
    rows = {(r["_send_ids"]["od_seq"]): r for r in OS.load(
        ["lotteon"], since="2000-01-01", until="2999-01-01", session=session)}
    assert str(rows["1"]["정산예정금액"]) == "30000"
    assert str(rows["2"]["정산예정금액"]) == "25000"
    assert all(r["_settle_source"] == "real" for r in rows.values())


def test_이미_real_과_클레임은_안_건드린다(session, monkeypatch):
    OS.save([_row("O1", "1", 정산예정금액=43512, _settle_source="real"),
             _row("O2", "1", 주문상태="반품완료", _kind="change",
                  _change_date="2026-07-10")], session=session)
    _add_crawl(session, "O1", "1", 111)
    _add_crawl(session, "O2", "1", 222)
    _no_scan(monkeypatch, itmd={"O1": 111, "O2": 222})

    stat = OI.refresh_settlement_lotteon(session=session)
    assert stat["updated"] == 0


def test_실값_없으면_그대로(session, monkeypatch):
    OS.save([_row("O1", "1")], session=session)
    _no_scan(monkeypatch, itmd={"OTHER": 5})
    stat = OI.refresh_settlement_lotteon(session=session)
    assert stat["updated"] == 0
    stored = OS.load(["lotteon"], since="2000-01-01", until="2999-01-01",
                     session=session)[0]
    assert stored["_settle_source"] == "estimated"
