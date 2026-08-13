# -*- coding: utf-8 -*-
"""[2026-08-13] 정산 스윕도 **배송비 정산 실값**을 실어야 한다 — 과거분이 안 고쳐지던 것.

🔴 무엇이 문제였나

  2026-08-12 에 「배송비도 수수료를 뗀다」를 고쳤는데, 고친 곳이 **화면 조회 경로
  (인라인 빌더)뿐**이었다. 정산 스윕 2경로는 배송비 정산 실값을 받아 놓고 버렸다:

      order_ingest.refresh_settlement_coupang      `_deliv` 를 받아서 **버린다**
      order_ingest.refresh_settlement_smartstore   `deliv` 를 만들어 놓고 **한 번도 안 읽는다**

  스윕은 60~75일 묵은 주문을 추정 → 실값으로 바꾸는 **바로 그 경로**다. 거기서
  M(정산예정금액)만 실값이 되고 배송비는 안 실리면, N열(정산예정금(배송비포함))이
  고객배송비 **전액**을 더한다 → 과거분의 「받을 돈」이 배송비 수수료만큼 계속 과대다.
  (쿠팡 실측: 4,000 → 수수료 132 → 정산 3,868. 배송비 붙은 라이브 2,072건이 대상)

🔴 이 시험이 지키는 두 가지

  ① **주문(배송건)당 1회** — 스윕은 행을 **한 줄씩** `_finalize_rows([row])` 에 넣는다.
     그래서 `_shipkey` 로 하는 중복 제거가 **안 걸린다**(저장 때 이미 pop 됐다).
     스윕이 스스로 담당 줄을 정해 주지 않으면 다품 주문에서 줄 수만큼 곱해진다.
  ② **안 맡는 줄엔 0 을 명시 대입** — pop 하면 저장분 병합(`_merge_row`)이 못 지워
     옛 값이 살아남는다(2026-08-12 에 인라인 경로에서 실제로 잡힌 함정).
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
    import lemouton.markets.models_orders  # noqa: F401 — 테이블 등록
    from shared.db import Base
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng, tables=[
        Base.metadata.tables["market_order_lines"],
        Base.metadata.tables["market_claim_events"],
    ])
    s = sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)()
    yield s
    s.close()


def _order_date(days_ago: int) -> str:
    return (_dt.datetime.now(KST) - _dt.timedelta(days=days_ago)
            ).strftime("%Y-%m-%d %H:%M:%S")


def _n(row) -> int:
    return int(float(str(row["정산예정금(배송비포함)"])))


# ══════════════════════════════════════════════════════════════
# 쿠팡 스윕
# ══════════════════════════════════════════════════════════════

def _cp_row(uid="coupang|70001|1001", ono="70001", vid="1001", 배송비=4000, **kw):
    row = {L.FIELD: uid, "판매처": "쿠팡", "쇼핑몰": "쿠팡", "오픈마켓주문번호": ono,
           "_pd_market_option_id": vid,
           "주문일": _order_date(40), "주문상태": "구매확정",
           "상품명": "테스트 상품", "단가": 30000, "수량": 1,
           "실결제금액": 34000, "배송비": 배송비,
           "정산예정금액": 27000, "_settle_source": "estimated"}
    row.update(kw)
    return row


def _cp_patch(monkeypatch, item_map, deliv=None):
    monkeypatch.setattr(OI, "_esm_settlement_clients",
                        lambda market: [("메인", object())])
    import lemouton.markets.order_export as _oe
    monkeypatch.setattr(_oe, "_coupang_settle_map",
                        lambda since, until, client: (dict(item_map),
                                                      dict(deliv or {}), {}))


def _cp_load(session):
    return {r["orders_line_uid"] if "orders_line_uid" in r else r[L.FIELD]: r
            for r in OS.load(["coupang"], since="2000-01-01", until="2999-01-01",
                             session=session)}


def test_쿠팡스윕이_배송비_정산_실값을_N열에_싣는다(session, monkeypatch):
    """🔴 여태 `_deliv` 를 받아서 버렸다 — N 이 고객배송비 4,000 전액을 더했다."""
    OS.save([_cp_row()], session=session)
    _cp_patch(monkeypatch, {("70001", "1001"): 26500}, deliv={"70001": 3868})

    OI.refresh_settlement_coupang(session=session)

    r = OS.load(["coupang"], since="2000-01-01", until="2999-01-01",
                session=session)[0]
    assert _n(r) == 26500 + 3868, \
        f'배송비 정산 실값(3,868)을 안 쓰고 고객배송비(4,000)를 더했다: {_n(r)}'


def test_쿠팡스윕_배송비_정산이_없으면_종전대로(session, monkeypatch):
    """모르는 값을 지어내지 않는다 — 요율을 박아 추정하지 말 것."""
    OS.save([_cp_row()], session=session)
    _cp_patch(monkeypatch, {("70001", "1001"): 26500}, deliv={})

    OI.refresh_settlement_coupang(session=session)

    r = OS.load(["coupang"], since="2000-01-01", until="2999-01-01",
                session=session)[0]
    assert _n(r) == 26500 + 4000


def test_쿠팡스윕은_다품주문에_한_번만_더한다(session, monkeypatch):
    """🔴 스윕은 행을 **한 줄씩** _finalize 에 넣어 `_shipkey` 중복 제거가 안 걸린다.

    저장분에서 배송비를 지고 있는 줄이 그 배송건의 담당이다(저장 때 정규화된 결과).
    """
    OS.save([_cp_row(uid="coupang|70001|1001", vid="1001", 배송비=4000),
             _cp_row(uid="coupang|70001|1002", vid="1002", 배송비=0)],
            session=session)
    _cp_patch(monkeypatch, {("70001", "1001"): 10000, ("70001", "1002"): 20000},
              deliv={"70001": 3868})

    OI.refresh_settlement_coupang(session=session)

    rows = OS.load(["coupang"], since="2000-01-01", until="2999-01-01",
                   session=session)
    합 = sum(_n(r) for r in rows)
    assert 합 == 10000 + 20000 + 3868, \
        f'같은 주문인데 배송비 정산을 두 번 더했다(또는 아예 안 더했다): {합}'


def test_쿠팡스윕_재실행이_멱등하다(session, monkeypatch):
    """스케줄러가 매일 돈다 — 돌 때마다 배송비가 쌓이면 안 된다."""
    OS.save([_cp_row(uid="coupang|70001|1001", vid="1001", 배송비=4000),
             _cp_row(uid="coupang|70001|1002", vid="1002", 배송비=0)],
            session=session)
    _cp_patch(monkeypatch, {("70001", "1001"): 10000, ("70001", "1002"): 20000},
              deliv={"70001": 3868})

    OI.refresh_settlement_coupang(session=session)
    첫판 = sum(_n(r) for r in OS.load(["coupang"], since="2000-01-01",
                                      until="2999-01-01", session=session))
    OI.refresh_settlement_coupang(session=session)
    둘째판 = sum(_n(r) for r in OS.load(["coupang"], since="2000-01-01",
                                        until="2999-01-01", session=session))
    assert 첫판 == 둘째판 == 10000 + 20000 + 3868


def test_쿠팡스윕_안_맡는_줄엔_0을_명시_대입한다(session, monkeypatch):
    """🔴 pop 하면 저장분 병합이 못 지워 옛 값이 살아남는다(인라인 경로에서 잡힌 함정)."""
    OS.save([_cp_row(uid="coupang|70001|1001", vid="1001", 배송비=4000),
             _cp_row(uid="coupang|70001|1002", vid="1002", 배송비=0)],
            session=session)
    _cp_patch(monkeypatch, {("70001", "1001"): 10000, ("70001", "1002"): 20000},
              deliv={"70001": 3868})

    OI.refresh_settlement_coupang(session=session)

    rows = {r[L.FIELD]: r for r in OS.load(["coupang"], since="2000-01-01",
                                           until="2999-01-01", session=session)}
    값 = [rows[u].get("_ship_settle") for u in ("coupang|70001|1001",
                                                "coupang|70001|1002")]
    assert 0 in [int(v) for v in 값 if v is not None], \
        f'안 맡는 줄에 0 을 명시 대입하지 않았다: {값}'


def test_쿠팡스윕_M열엔_배송비를_안_넣는다(session, monkeypatch):
    """M 에 섞으면 N 이 또 더해 이중 계상된다(2026-08-07 사고)."""
    OS.save([_cp_row()], session=session)
    _cp_patch(monkeypatch, {("70001", "1001"): 26500}, deliv={"70001": 3868})

    OI.refresh_settlement_coupang(session=session)

    r = OS.load(["coupang"], since="2000-01-01", until="2999-01-01",
                session=session)[0]
    assert int(float(str(r["정산예정금액"]))) == 26500


# ══════════════════════════════════════════════════════════════
# 스마트스토어 스윕
# ══════════════════════════════════════════════════════════════

def _ss_row(poid="PO1", 배송비=3000, **kw):
    row = {L.FIELD: "smartstore|" + poid, "판매처": "스마트스토어",
           "쇼핑몰": "04.스마트스토어", "오픈마켓주문번호": poid,
           "주문일": _order_date(30), "주문상태": "구매확정",
           "상품명": "티셔츠", "단가": 20000, "수량": 1, "실결제금액": 23000,
           "배송비": 배송비, "정산예정금액": 18800, "_settle_source": "estimated"}
    row.update(kw)
    return row


def _ss_patch(monkeypatch, elements):
    from lemouton.markets import order_export as OE
    monkeypatch.setattr(OE, "_active_accounts", lambda m: [(None, "대표계정")])
    monkeypatch.setattr(OE, "_account_client", lambda m, p=None: object())
    import shared.platforms.smartstore.settlements as _ss
    seen = {"done": False}

    def _iter(search_date=None, period_type=None, client=None, **kw):
        if seen["done"]:            # 정산은 결제일 '하루'에만 나온다 — 한 번만 준다
            return []
        seen["done"] = True
        return list(elements)
    monkeypatch.setattr(_ss, "iter_settle_by_case", _iter)


def test_스스스윕이_배송비_정산_실값을_N열에_싣는다(session, monkeypatch):
    """🔴 여태 `deliv` 를 만들어 놓고 한 번도 안 읽었다."""
    OS.save([_ss_row("PO1")], session=session)
    _ss_patch(monkeypatch, [
        {"productOrderId": "PO1", "orderId": "O1", "productOrderType": "PROD",
         "settleExpectAmount": 18850},
        {"orderId": "O1", "productOrderType": "DELIVERY", "settleExpectAmount": 2910},
    ])

    OI.refresh_settlement_smartstore(session=session)

    r = OS.load(["smartstore"], since="2000-01-01", until="2999-01-01",
                session=session)[0]
    assert _n(r) == 18850 + 2910, \
        f'배송비 정산 실값(2,910)을 안 쓰고 고객배송비(3,000)를 더했다: {_n(r)}'


def test_스스스윕_배송비_정산이_없으면_종전대로(session, monkeypatch):
    OS.save([_ss_row("PO1")], session=session)
    _ss_patch(monkeypatch, [
        {"productOrderId": "PO1", "orderId": "O1", "productOrderType": "PROD",
         "settleExpectAmount": 18850},
    ])

    OI.refresh_settlement_smartstore(session=session)

    r = OS.load(["smartstore"], since="2000-01-01", until="2999-01-01",
                session=session)[0]
    assert _n(r) == 18850 + 3000


def test_스스스윕은_다품주문에_한_번만_더한다(session, monkeypatch):
    """같은 orderId 의 상품주문 둘 — 배송비 정산은 주문당 1회."""
    OS.save([_ss_row("PO1", 배송비=3000), _ss_row("PO2", 배송비=0)], session=session)
    _ss_patch(monkeypatch, [
        {"productOrderId": "PO1", "orderId": "O1", "productOrderType": "PROD",
         "settleExpectAmount": 10000},
        {"productOrderId": "PO2", "orderId": "O1", "productOrderType": "PROD",
         "settleExpectAmount": 12000},
        {"orderId": "O1", "productOrderType": "DELIVERY", "settleExpectAmount": 2910},
    ])

    OI.refresh_settlement_smartstore(session=session)

    rows = OS.load(["smartstore"], since="2000-01-01", until="2999-01-01",
                   session=session)
    합 = sum(_n(r) for r in rows)
    assert 합 == 10000 + 12000 + 2910, \
        f'같은 주문인데 배송비 정산을 두 번 더했다(또는 아예 안 더했다): {합}'


def test_스스스윕_재실행이_멱등하다(session, monkeypatch):
    OS.save([_ss_row("PO1", 배송비=3000), _ss_row("PO2", 배송비=0)], session=session)
    els = [
        {"productOrderId": "PO1", "orderId": "O1", "productOrderType": "PROD",
         "settleExpectAmount": 10000},
        {"productOrderId": "PO2", "orderId": "O1", "productOrderType": "PROD",
         "settleExpectAmount": 12000},
        {"orderId": "O1", "productOrderType": "DELIVERY", "settleExpectAmount": 2910},
    ]
    _ss_patch(monkeypatch, els)
    OI.refresh_settlement_smartstore(session=session)
    첫판 = sum(_n(r) for r in OS.load(["smartstore"], since="2000-01-01",
                                      until="2999-01-01", session=session))
    _ss_patch(monkeypatch, els)                # 새 조회 흉내(같은 값이 또 온다)
    OI.refresh_settlement_smartstore(session=session)
    둘째판 = sum(_n(r) for r in OS.load(["smartstore"], since="2000-01-01",
                                        until="2999-01-01", session=session))
    assert 첫판 == 둘째판 == 10000 + 12000 + 2910


def test_스스스윕_M열엔_배송비를_안_넣는다(session, monkeypatch):
    """이미 있던 규약 — 배선을 붙이다 이걸 깨면 2026-08-07 사고가 재발한다."""
    OS.save([_ss_row("PO1")], session=session)
    _ss_patch(monkeypatch, [
        {"productOrderId": "PO1", "orderId": "O1", "productOrderType": "PROD",
         "settleExpectAmount": 18850},
        {"orderId": "O1", "productOrderType": "DELIVERY", "settleExpectAmount": 2910},
    ])

    OI.refresh_settlement_smartstore(session=session)

    r = OS.load(["smartstore"], since="2000-01-01", until="2999-01-01",
                session=session)[0]
    assert int(float(str(r["정산예정금액"]))) == 18850
