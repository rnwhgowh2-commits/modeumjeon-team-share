# -*- coding: utf-8 -*-
"""쿠팡 취소주문 실주문일 채움 — set_order_dates(빈 칸만)·계정 순회 계약."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import lemouton.markets.models_orders  # noqa: F401
from lemouton.markets import order_store
from lemouton.markets.models_orders import MarketClaimEvent, MarketOrderLine


@pytest.fixture
def s():
    from shared.db import Base
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng, tables=[
        Base.metadata.tables["market_order_lines"],
        Base.metadata.tables["market_claim_events"],
    ])
    Maker = sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)
    ses = Maker()
    yield ses
    ses.close()


def test_fills_blank_dates_only(s):
    s.add(MarketClaimEvent(event_uid="c1", line_uid="cp|1", market="coupang",
                           order_no="O1", row={"주문일": ""}))
    s.add(MarketClaimEvent(event_uid="c2", line_uid="cp|2", market="coupang",
                           order_no="O2", row={"주문일": "2026-05-01 10:00:00"}))
    s.add(MarketOrderLine(line_uid="cp|1", market="coupang", order_no="O1",
                          order_date="", row={"주문일": ""}))
    s.commit()
    st = order_store.set_order_dates(
        "coupang", {"O1": "2026-04-20 09:00:00", "O2": "2026-04-21 09:00:00"},
        session=s)
    assert st["lines_filled"] == 1 and st["claims_filled"] == 1
    assert s.get(MarketClaimEvent, "c1").row["주문일"] == "2026-04-20 09:00:00"
    # 실값 보존 — 이미 있는 주문일은 덮지 않는다
    assert s.get(MarketClaimEvent, "c2").row["주문일"] == "2026-05-01 10:00:00"
    assert s.get(MarketOrderLine, "cp|1").order_date == "2026-04-20 09:00:00"


def test_ingest_iterates_accounts_and_converts_kst(monkeypatch, s):
    from lemouton.markets import order_ingest as OI
    monkeypatch.setattr("lemouton.markets.order_export._active_accounts",
                        lambda m: [("A", "계정A"), ("B", "계정B")])
    monkeypatch.setattr("lemouton.markets.order_export._account_client",
                        lambda m, p=None: object())
    def fake_fetch(oid, client=None):
        if oid == "O1":
            return {"data": [{"orderedAt": "2026-04-20T09:00:00+09:00"}]}
        raise RuntimeError("이 계정에 없음")
    monkeypatch.setattr(
        "shared.platforms.coupang.orders.fetch_ordersheets_by_order_id", fake_fetch)
    s.add(MarketClaimEvent(event_uid="c1", line_uid="cp|1", market="coupang",
                           order_no="O1", row={"주문일": ""}))
    s.commit()
    st = OI.ingest_coupang_dates_by_order_ids(["O1", "OX"], session=s)
    assert st["found"] == 1 and st["not_found"] == ["OX"]
    assert s.get(MarketClaimEvent, "c1").row["주문일"] == "2026-04-20 09:00:00"
