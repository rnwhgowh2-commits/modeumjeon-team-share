# -*- coding: utf-8 -*-
"""옥션·G마켓 과거 클레임 백필 — 1년 백필이 orders_only 라 클레임이 0건이던 구멍."""
import datetime as _dt

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import lemouton.markets.order_ingest as OI

UNTIL = _dt.datetime(2026, 7, 20, 12, 0)
SINCE = UNTIL - _dt.timedelta(days=21)


@pytest.fixture
def session():
    from shared.db import Base
    import lemouton.markets.models_orders  # noqa: F401
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng, tables=[
        Base.metadata.tables["market_order_lines"],
        Base.metadata.tables["market_claim_events"],
    ])
    s = sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)()
    yield s
    s.close()


def test_클레임전용_경로로_창을_적재한다(monkeypatch, session):
    seen = {}

    def fake_rows(market, since, until, client=None, include_settlement=True, **kw):
        seen.update(kw, market=market, since=since, until=until)
        return [{"판매처": "옥션", "_kind": "change", "오픈마켓주문번호": "77",
                 "_change_date": "2026-07-01", "주문상태": "취소완료",
                 "주문상태원본": "3"}]

    monkeypatch.setattr("lemouton.markets.order_export.esm_order_rows", fake_rows)
    monkeypatch.setattr("lemouton.markets.order_export._account_client",
                        lambda m, p=None: object())
    st = OI.ingest_esm_claims_window("auction", SINCE, UNTIL, prefix="X",
                                     session=session)
    assert seen.get("claims_only") is True and seen.get("claim_to_now") is False
    assert st["claims_new"] == 1 and st["fetched"] == 1


def test_esm_아닌_마켓은_거부한다(session):
    with pytest.raises(ValueError):
        OI.ingest_esm_claims_window("coupang", SINCE, UNTIL, session=session)
