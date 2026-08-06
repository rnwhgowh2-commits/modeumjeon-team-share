# -*- coding: utf-8 -*-
"""정산 스윕의 지급예정일 저장 — 정산예정금액 탭의 날짜 실값 원천.

마켓이 주는데 버리던 값을 저장한다: ESM SettleExpectDate(정산예정일)·RemitDate(송금일=
실지급 확인), 쿠팡 settlementDate+finalSettlementDate(분할 2날짜), 스스 settleExpectDate+
settleCompleteDate, 11번가 stlPlnDy(송금예정일).

🔴 이미 real 인 행도 **날짜는** 갱신한다(백필 겸용) — 금액 규약(확정 real 불가침)은 불변.
🔴 ESM 보류 센티널(1991-01-01 류·0001-01-01)은 날짜가 아니다 — 버린다.
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
    import lemouton.markets.models_orders  # noqa: F401  — 테이블 등록
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


# ── ESM: settle_detail_map 이 날짜를 담는다 ──────────────────────────────────

def _esm_map_from(monkeypatch, data_rows):
    import shared.platforms.esm.settlements as _s
    resp = {"ResultCode": 0, "TotalCount": len(data_rows), "Data": data_rows}
    monkeypatch.setattr(_s, "_request_with_rate_backoff", lambda client, body: resp)
    now = _dt.datetime.now(KST)
    return _s.settle_detail_map("gmarket", now - _dt.timedelta(days=3), now,
                                client=object())


def test_esm_상세맵이_정산예정일과_송금일을_담는다(monkeypatch):
    out = _esm_map_from(monkeypatch, [{
        "ContrNo": 123, "Kind": 1, "SettlementPrice": "9000",
        "OrderUnitPrice": "10000", "OrderQty": "1", "BuyerPayAmt": "10000",
        "SettleExpectDate": "2026-08-20T00:00:00",
        "RemitDate": "0001-01-01T00:00:00",          # 빈 값 센티널 → 담지 않는다
        "BuyDecisonDate": "2026-08-05T00:00:00"}])
    ent = out["123"]
    assert ent["정산예정일"] == "2026-08-20"
    assert ent["송금일"] is None
    assert ent["구매확정일"] == "2026-08-05"


def test_esm_보류_센티널_1991년은_날짜가_아니다(monkeypatch):
    out = _esm_map_from(monkeypatch, [{
        "ContrNo": 123, "Kind": 1, "SettlementPrice": "9000",
        "SettleExpectDate": "1991-01-01T00:00:00"}])   # 장기미배송 보류
    assert out["123"]["정산예정일"] is None


def test_esm_송금일이_오면_실지급_확인으로_담는다(monkeypatch):
    out = _esm_map_from(monkeypatch, [{
        "ContrNo": 9, "Kind": 1, "SettlementPrice": "5000",
        "RemitDate": "2026-08-01T00:00:00"}])
    assert out["9"]["송금일"] == "2026-08-01"


# ── ESM: refresh_settlement 가 row 에 날짜를 쓴다 ────────────────────────────

def _row(uid="gmarket|4463818179", ono="4463818179", days_ago=24, **kw):
    row = {L.FIELD: uid, "판매처": "G마켓", "쇼핑몰": "G마켓", "오픈마켓주문번호": ono,
           "주문일": _order_date(days_ago), "주문상태": "구매결정",
           "상품명": "나이키 리엑스 8", "단가": 81800, "수량": 1,
           "실결제금액": 81800, "배송비": 0,
           "정산예정금액": 69000, "_settle_source": "estimated"}
    row.update(kw)
    return row


def _patch_settlement(monkeypatch, smap, clients=(("브랜드위시", object()),)):
    monkeypatch.setattr(OI, "_esm_settlement_clients", lambda market: list(clients))
    import shared.platforms.esm.settlements as _s
    monkeypatch.setattr(
        _s, "settle_detail_map",
        lambda market, since, until, *, client, srch_type="D1", page_rows=None: smap)


def test_esm_스윕이_금액과_날짜를_함께_쓴다(session, monkeypatch):
    OS.save([_row()], session=session)
    _patch_settlement(monkeypatch, {"4463818179": {
        "정산예정금액": 69530, "정산예정일": "2026-08-20", "송금일": None}})

    stat = OI.refresh_settlement("gmarket", session=session)

    assert stat["updated"] == 1
    stored = OS.load(["gmarket"], since="2000-01-01", until="2999-01-01",
                     session=session)[0]
    assert str(stored["정산예정금액"]) == "69530"
    assert stored["_settle_source"] == "real"
    assert stored["정산예정일"] == "2026-08-20"


def test_esm_이미_real_인_행에도_날짜만_백필하고_금액은_불변(session, monkeypatch):
    OS.save([_row(정산예정금액=69530, _settle_source="real")], session=session)
    _patch_settlement(monkeypatch, {"4463818179": {
        "정산예정금액": 11111,                      # 다른 값이 와도 금액은 불가침
        "정산예정일": "2026-08-20", "송금일": "2026-08-25"}})

    stat = OI.refresh_settlement("gmarket", session=session)

    assert stat["updated"] == 1
    stored = OS.load(["gmarket"], since="2000-01-01", until="2999-01-01",
                     session=session)[0]
    assert str(stored["정산예정금액"]) == "69530"    # 금액 그대로
    assert stored["정산예정일"] == "2026-08-20"
    assert stored["_settle_paid_date"] == "2026-08-25"


def test_esm_날짜가_같으면_다시_쓰지_않는다(session, monkeypatch):
    """무의미한 쓰기(last_seen_at 갱신) 방지 — 기존 「값이 같으면 안 쓴다」 규약 유지."""
    OS.save([_row(정산예정금액=69530, _settle_source="real",
                  정산예정일="2026-08-20")], session=session)
    _patch_settlement(monkeypatch, {"4463818179": {
        "정산예정금액": 69530, "정산예정일": "2026-08-20", "송금일": None}})

    stat = OI.refresh_settlement("gmarket", session=session)
    assert stat["updated"] == 0


def test_esm_날짜만_있는_정산행도_스윕이_받는다(session, monkeypatch):
    """금액 파싱 실패·0 이어도 날짜(송금일=지급확인)는 유효 정보다."""
    OS.save([_row(정산예정금액=69530, _settle_source="real")], session=session)
    _patch_settlement(monkeypatch, {"4463818179": {
        "정산예정금액": None, "정산예정일": None, "송금일": "2026-08-01"}})

    stat = OI.refresh_settlement("gmarket", session=session)
    assert stat["updated"] == 1
    stored = OS.load(["gmarket"], since="2000-01-01", until="2999-01-01",
                     session=session)[0]
    assert stored["_settle_paid_date"] == "2026-08-01"
    assert str(stored["정산예정금액"]) == "69530"
