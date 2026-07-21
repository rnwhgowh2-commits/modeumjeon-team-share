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


def test_백필창은_계정접두어_클라이언트와_별칭을_쓴다(monkeypatch, session):
    """백필이 대표계정 1개만 돌던 것(누락 605건 최대 원인) — prefix 로 계정을 고르고
    쇼핑몰별칭을 행에 새겨 계정 귀속이 남게 한다."""
    from lemouton.markets import line_uid as L
    from lemouton.markets import order_store as OS
    got = {}

    def fake_client(m, p=None):
        got["prefix"] = p
        return object()

    monkeypatch.setattr("lemouton.markets.order_export._account_client", fake_client)
    monkeypatch.setattr(
        "shared.platforms.lotteon.settle_orders.order_rows",
        lambda s, u, client=None: [{L.FIELD: "lotteon|O1|1", "판매처": "롯데온",
                                    "오픈마켓주문번호": "O1",
                                    "주문일": "2026-04-01 10:00:00"}])
    st = OI.ingest_window("lotteon", SINCE, UNTIL, session=session,
                          include_settlement=False, backfill=True,
                          prefix="LOTTEON_2", alias="브랜드타임(롯데온)")
    assert st["orders_new"] == 1
    assert got["prefix"] == "LOTTEON_2"
    rows = OS.load(session=session)
    assert rows[0]["쇼핑몰별칭"] == "브랜드타임(롯데온)"


def test_롯데온_클레임_백필창은_클레임전용_경로로_적재한다(monkeypatch, session):
    seen = {}

    def fake(since, until, client=None, include_settlement=True, **kw):
        seen.update(kw)
        return [{"판매처": "롯데온", "_kind": "change", "오픈마켓주문번호": "LO1",
                 "_change_date": "2026-04-05", "주문상태": "취소완료",
                 "주문상태원본": "21",
                 "_send_ids": {"od_no": "LO1", "od_seq": "1", "clm_no": "C1"}}]

    monkeypatch.setattr("lemouton.markets.order_export.lotteon_order_rows", fake)
    monkeypatch.setattr("lemouton.markets.order_export._account_client",
                        lambda m, p=None: object())
    st = OI.ingest_lotteon_claims_window(SINCE, UNTIL, prefix="L1",
                                         alias="브랜드박스(롯데온)", session=session)
    assert seen.get("claims_only") is True and seen.get("claim_to_now") is False
    assert st["claims_new"] == 1


def test_11번가_단건복구는_계정을_순회하며_찾은_계정_별칭을_새긴다(monkeypatch, session):
    def fake_rows(since, until, client=None, include_settlement=True, order_nos=None, **kw):
        # 'P2' 계정에서만 주문이 나온다(다른 계정 키로는 빈 응답)
        if getattr(client, "tag", "") != "P2":
            return []
        return [{"판매처": "11번가", "오픈마켓주문번호": order_nos[0],
                 "주문일": "2026-05-19 10:00:00", "주문상태": "반품완료",
                 "_send_ids": {"ord_no": order_nos[0], "ord_prd_seq": "1"}}]

    class _Cli:
        def __init__(self, tag): self.tag = tag

    monkeypatch.setattr("lemouton.markets.order_export.eleven11_order_rows", fake_rows)
    monkeypatch.setattr("lemouton.markets.order_export._active_accounts",
                        lambda m: [("P1", "가게1"), ("P2", "가게2")])
    monkeypatch.setattr("lemouton.markets.order_export._account_client",
                        lambda m, p=None: _Cli(p))
    st = OI.ingest_eleven11_orders_by_no(["20260519069451269"], session=session)
    assert st["found"] == {"20260519069451269": "가게2"}
    assert st["not_found"] == []
    from lemouton.markets import order_store as OS
    rows = OS.load(session=session)
    assert rows and rows[0]["쇼핑몰별칭"] == "가게2"


def test_11번가_단건복구_못찾으면_정직하게_보고(monkeypatch, session):
    monkeypatch.setattr("lemouton.markets.order_export.eleven11_order_rows",
                        lambda *a, **k: [])
    monkeypatch.setattr("lemouton.markets.order_export._active_accounts",
                        lambda m: [("P1", "가게1")])
    monkeypatch.setattr("lemouton.markets.order_export._account_client",
                        lambda m, p=None: object())
    st = OI.ingest_eleven11_orders_by_no(["999"], session=session)
    assert st["found"] == {} and st["not_found"] == ["999"]
