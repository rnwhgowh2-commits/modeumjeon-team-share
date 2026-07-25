# -*- coding: utf-8 -*-
"""스마트스토어 정산 스윕 — 구매확정 뒤에 들어오는 실정산을 받아온다.

🔴 왜 필요한가(2026-07-25 전 마켓 검수 실측) — 스마트스토어 구매확정 1,682건이 40일
넘게 추정치로 고착. real 은 전체의 4%뿐이었다. 정산은 구매확정 며칠 뒤에 확정되는데
증분(7일)·refresh_open_orders(끝난 주문 건너뜀)가 옛 주문을 다시 안 봐서 못 받아왔다
(옥션·G마켓과 같은 클래스).

★ 조인 = 상품주문번호(productOrderId = 오픈마켓주문번호). 정산은 결제일 기준.
★ 배송비 정산은 주문(orderId)당 1회만 더한다(원본 smartstore_order_rows 규약).
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
    from shared.db import Base
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng, tables=[
        Base.metadata.tables["market_order_lines"],
        Base.metadata.tables["market_claim_events"],
    ])
    s = sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)()
    yield s
    s.close()


def _row(poid="PO1", days_ago=30, **kw):
    d = (_dt.datetime.now(KST) - _dt.timedelta(days=days_ago)).strftime("%Y-%m-%d %H:%M:%S")
    row = {L.FIELD: "smartstore|" + poid, "판매처": "스마트스토어", "쇼핑몰": "04.스마트스토어",
           "오픈마켓주문번호": poid, "주문일": d, "주문상태": "구매확정",
           "상품명": "티셔츠", "단가": 20000, "수량": 1, "실결제금액": 20000, "배송비": 0,
           "정산예정금액": 18800, "_settle_source": "estimated"}
    row.update(kw)
    return row


def _patch(monkeypatch, elements, accounts=(("대표계정", object()),), calls=None):
    from lemouton.markets import order_export as OE
    monkeypatch.setattr(OE, "_active_accounts",
                        lambda m: [(None, n) for n, _ in accounts])
    monkeypatch.setattr(OE, "_account_client", lambda m, p=None: accounts[0][1])
    import shared.platforms.smartstore.settlements as _ss

    seen = {"done": False}

    def _iter(search_date=None, period_type=None, client=None, **kw):
        if calls is not None:
            calls.append((search_date, period_type))
        if seen["done"]:            # 정산은 결제일 '하루'에만 나온다 — 한 번만 준다
            return []
        seen["done"] = True
        return list(elements)
    monkeypatch.setattr(_ss, "iter_settle_by_case", _iter)


def test_구매확정_뒤_실정산을_받아온다(session, monkeypatch):
    OS.save([_row("PO1")], session=session)
    _patch(monkeypatch, [{"productOrderId": "PO1", "orderId": "O1",
                          "productOrderType": "PROD", "settleExpectAmount": 18850}])

    stat = OI.refresh_settlement_smartstore(session=session)

    assert stat["updated"] == 1
    stored = OS.load(["smartstore"], since="2000-01-01", until="2999-01-01",
                     session=session)[0]
    assert str(stored["정산예정금액"]) == "18850"
    assert stored["_settle_source"] == "real"


def test_배송비정산은_주문당_1회만_더한다(session, monkeypatch):
    """같은 주문(orderId) 여러 상품주문이면 배송비 정산은 한 번만."""
    OS.save([_row("PO1"), _row("PO2")], session=session)
    _patch(monkeypatch, [
        {"productOrderId": "PO1", "orderId": "O1", "productOrderType": "PROD",
         "settleExpectAmount": 10000},
        {"productOrderId": "PO2", "orderId": "O1", "productOrderType": "PROD",
         "settleExpectAmount": 12000},
        {"orderId": "O1", "productOrderType": "DELIVERY", "settleExpectAmount": 2500},
    ])

    OI.refresh_settlement_smartstore(session=session)
    rows = {r["오픈마켓주문번호"]: r for r in OS.load(
        ["smartstore"], since="2000-01-01", until="2999-01-01", session=session)}
    settles = sorted(int(float(str(rows[p]["정산예정금액"]))) for p in ("PO1", "PO2"))
    # 배송비 2,500 은 한 행에만 붙어야 한다(합계 중복 금지) — 어느 행이든 하나만 +2,500.
    assert settles in ([12000, 12500], [10000, 14500])
    assert sum(settles) == 10000 + 12000 + 2500


def test_이미_real_은_안_건드린다(session, monkeypatch):
    OS.save([_row("PO1", 정산예정금액=18850, _settle_source="real")], session=session)
    _patch(monkeypatch, [{"productOrderId": "PO1", "orderId": "O1",
                          "productOrderType": "PROD", "settleExpectAmount": 99}])
    stat = OI.refresh_settlement_smartstore(session=session)
    assert stat["updated"] == 0


def test_정산조회에_없으면_그대로(session, monkeypatch):
    OS.save([_row("PO1")], session=session)
    _patch(monkeypatch, [{"productOrderId": "OTHER", "orderId": "O9",
                          "productOrderType": "PROD", "settleExpectAmount": 5}])
    stat = OI.refresh_settlement_smartstore(session=session)
    assert stat["updated"] == 0
    stored = OS.load(["smartstore"], since="2000-01-01", until="2999-01-01",
                     session=session)[0]
    assert stored["_settle_source"] == "estimated"


def test_클레임행은_안_건드린다(session, monkeypatch):
    OS.save([_row("PO1", 주문상태="반품완료", _kind="change",
                  _change_date="2026-07-10")], session=session)
    _patch(monkeypatch, [{"productOrderId": "PO1", "orderId": "O1",
                          "productOrderType": "PROD", "settleExpectAmount": 18850}])
    stat = OI.refresh_settlement_smartstore(session=session)
    assert stat["updated"] == 0


def test_결제일_기준으로_조회한다(session, monkeypatch):
    calls = []
    OS.save([_row("PO1")], session=session)
    _patch(monkeypatch, [], calls=calls)
    OI.refresh_settlement_smartstore(session=session, days=3, skip_days=0)
    assert calls, "정산조회가 한 번도 안 불렸다"
    assert all(p == "SETTLE_CASEBYCASE_PAY_DATE" for _d, p in calls)
