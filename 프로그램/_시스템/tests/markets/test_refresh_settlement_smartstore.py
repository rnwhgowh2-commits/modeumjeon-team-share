# -*- coding: utf-8 -*-
"""스마트스토어 정산 스윕 — 구매확정 뒤에 들어오는 실정산을 받아온다.

🔴 왜 필요한가(2026-07-25 전 마켓 검수 실측) — 스마트스토어 구매확정 1,682건이 40일
넘게 추정치로 고착. real 은 전체의 4%뿐이었다. 정산은 구매확정 며칠 뒤에 확정되는데
증분(7일)·refresh_open_orders(끝난 주문 건너뜀)가 옛 주문을 다시 안 봐서 못 받아왔다
(옥션·G마켓과 같은 클래스).

★ 조인 = 상품주문번호(productOrderId = 오픈마켓주문번호). 정산은 결제일 기준.
★ M열(정산예정금액) = **상품 정산만**. 배송비 정산은 안 더한다(빌더와 같은 규약).
  🔴 2026-08-07 정정 — 옛 규칙은 배송비 정산을 주문당 1회 더했는데, `_finalize_rows` 가
  N열(=M+고객배송비)에서 고객배송비를 **또** 더해 배송비가 두 번 들어갔다(라이브 2,910원 과다).
  쿠팡·11번가·롯데온은 이미 분리해 두고 있었다 — 스스만 남아 있던 것.
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


def test_배송비정산은_M열에_안_섞는다(session, monkeypatch):
    """같은 주문(orderId) 여러 상품주문이어도 M 은 각자의 상품 정산 그대로다.

    🔴 이 시험이 지키는 것 — 배송비를 M 에 더하면 N열(M+고객배송비)에서 두 번 세어져
    「받을 돈」이 배송비만큼 부풀어 오른다. 되채움도 빌더와 같은 규약이어야 한다.
    """
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
    assert settles == [10000, 12000], (
        "배송비 정산 2,500 이 M열에 섞였다 — N열에서 고객배송비와 이중 가산된다: %s" % settles)


def test_이미_real_이어도_정산조회_값이_이긴다(session, monkeypatch):
    """🔴 2026-08-07 정정 — 옛 시험은 「이미 real 이면 무조건 안 건드린다」였다.

    그 규칙이 배송비 섞인 옛값(규약 전환 전 저장분)을 영영 보호해, 과거 「받을 돈」이
    부풀어 남았다. 정산조회가 곧 원천이므로 **거기 값이 이긴다**.
    「안 건드린다」의 참된 자리는 아래 `정산조회에_없으면_그대로` 다.
    """
    OS.save([_row("PO1", 정산예정금액=18850, _settle_source="real")], session=session)
    _patch(monkeypatch, [{"productOrderId": "PO1", "orderId": "O1",
                          "productOrderType": "PROD", "settleExpectAmount": 99}])
    stat = OI.refresh_settlement_smartstore(session=session)
    rows = {r["오픈마켓주문번호"]: r for r in OS.load(
        ["smartstore"], since="2000-01-01", until="2999-01-01", session=session)}
    assert int(float(str(rows["PO1"]["정산예정금액"]))) == 99
    assert stat["updated"] == 1


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


def test_이미_real_이어도_배송비가_섞인_옛값은_바로잡는다(session, monkeypatch):
    """🔴 옛 규칙으로 저장된 행은 `real` 이라 되채움이 건너뛰어 영영 부풀린 채 남는다.

    2026-08-07 규약 전환(M열=상품분만) 전에 저장된 행은 M 에 배송비 정산이 섞여 있고
    `_settle_source='real'` 이다. 「이미 real 이면 안 건드린다」는 규칙이 그걸 보호해
    과거 「받을 돈」이 배송비만큼 계속 부풀어 보인다.
    정산조회가 주는 상품분과 **다르면** 바로잡는다(같으면 안 쓴다 — 무의미한 쓰기 방지).
    """
    # 옛값: 상품 10,000 + 배송비정산 2,500 = 12,500 이 real 로 저장돼 있다
    OS.save([_row("PO1", 정산예정금액=12500, _settle_source="real")], session=session)
    _patch(monkeypatch, [
        {"productOrderId": "PO1", "orderId": "O1", "productOrderType": "PROD",
         "settleExpectAmount": 10000},
        {"orderId": "O1", "productOrderType": "DELIVERY", "settleExpectAmount": 2500},
    ])
    stat = OI.refresh_settlement_smartstore(session=session)
    rows = {r["오픈마켓주문번호"]: r for r in OS.load(
        ["smartstore"], since="2000-01-01", until="2999-01-01", session=session)}
    assert int(float(str(rows["PO1"]["정산예정금액"]))) == 10000, (
        "이미 real 이라고 배송비 섞인 옛값을 그대로 뒀다: %s" % rows["PO1"]["정산예정금액"])
    assert stat["updated"] >= 1


def test_이미_real_이고_값도_같으면_안_쓴다(session, monkeypatch):
    """바로잡기가 「매번 전 행 다시 쓰기」로 번지면 안 된다(무의미한 쓰기·경합)."""
    OS.save([_row("PO1", 정산예정금액=10000, _settle_source="real")], session=session)
    _patch(monkeypatch, [{"productOrderId": "PO1", "orderId": "O1",
                          "productOrderType": "PROD", "settleExpectAmount": 10000}])
    stat = OI.refresh_settlement_smartstore(session=session)
    assert stat["updated"] == 0, "값이 같은데 다시 썼다: %s" % stat
