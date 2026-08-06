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


# ── 쿠팡: _coupang_settle_map 날짜맵 + 스윕 저장 ─────────────────────────────

def test_coupang_settle_map_이_지급예정일_두_날짜를_담는다():
    from lemouton.markets import order_export as oe

    class C:
        _cfg = {"vendor_id": "A1"}

        def request(self, method, path, query=""):
            if "revenue-history" in path and "token=&" in query:   # 첫 페이지만
                return {"data": [
                    {"orderId": 7, "saleType": "SALE",
                     "settlementDate": "2026-08-20",
                     "finalSettlementDate": "2026-09-10",
                     "items": [{"vendorItemId": 9, "settlementAmount": 88450}]},
                    {"orderId": 8, "saleType": "REFUND",
                     "settlementDate": "2026-08-21",
                     "items": [{"vendorItemId": 9, "settlementAmount": 100}]},
                ], "hasNext": False}
            return {"data": [], "hasNext": False}

    imap, _deliv, dates = oe._coupang_settle_map(
        _dt.datetime(2026, 7, 5, tzinfo=OI.KST),
        _dt.datetime(2026, 7, 8, tzinfo=OI.KST), C())
    assert dates["7"]["정산예정일"] == "2026-08-20"
    assert dates["7"]["_settle_final_date"] == "2026-09-10"
    assert "8" not in dates      # REFUND 날짜는 환불 기준 — 지급 배치 오염 방지


def _cp_row(ono="7", vid="9", **kw):
    row = {L.FIELD: f"coupang|{ono}|{vid}", "판매처": "쿠팡", "쇼핑몰": "쿠팡",
           "오픈마켓주문번호": ono, "_pd_market_option_id": vid,
           "주문일": _order_date(24), "주문상태": "구매확정",
           "상품명": "코트", "단가": 100000, "수량": 1, "실결제금액": 100000,
           "배송비": 0, "정산예정금액": 88000, "_settle_source": "estimated"}
    row.update(kw)
    return row


def test_coupang_스윕이_금액과_분할_두_날짜를_쓴다(session, monkeypatch):
    OS.save([_cp_row()], session=session)
    monkeypatch.setattr(OI, "_esm_settlement_clients",
                        lambda market: [("계정A", object())])
    from lemouton.markets import order_export as oe
    monkeypatch.setattr(
        oe, "_coupang_settle_map",
        lambda since, until, cli: ({("7", "9"): 88450}, {},
                                   {"7": {"정산예정일": "2026-08-20",
                                          "_settle_final_date": "2026-09-10"}}))

    stat = OI.refresh_settlement_coupang(session=session)

    assert stat["updated"] == 1
    stored = OS.load(["coupang"], since="2000-01-01", until="2999-01-01",
                     session=session)[0]
    assert str(stored["정산예정금액"]) == "88450"
    assert stored["정산예정일"] == "2026-08-20"
    assert stored["_settle_final_date"] == "2026-09-10"


def test_coupang_이미_real_행에도_날짜만_백필(session, monkeypatch):
    OS.save([_cp_row(정산예정금액=88450, _settle_source="real")], session=session)
    monkeypatch.setattr(OI, "_esm_settlement_clients",
                        lambda market: [("계정A", object())])
    from lemouton.markets import order_export as oe
    monkeypatch.setattr(
        oe, "_coupang_settle_map",
        lambda since, until, cli: ({("7", "9"): 11111}, {},
                                   {"7": {"정산예정일": "2026-08-20"}}))

    stat = OI.refresh_settlement_coupang(session=session)

    assert stat["updated"] == 1
    stored = OS.load(["coupang"], since="2000-01-01", until="2999-01-01",
                     session=session)[0]
    assert str(stored["정산예정금액"]) == "88450"    # 금액 불가침
    assert stored["정산예정일"] == "2026-08-20"


# ── 스마트스토어: 스윕이 정산예정일·완료일을 담는다 ──────────────────────────

def _ss_row(poid="P1", **kw):
    row = {L.FIELD: f"smartstore|{poid}", "판매처": "스마트스토어",
           "쇼핑몰": "스마트스토어", "오픈마켓주문번호": poid,
           "주문일": _order_date(10), "주문상태": "구매확정",
           "상품명": "가디건", "단가": 50000, "수량": 1, "실결제금액": 50000,
           "배송비": 0, "정산예정금액": 47000, "_settle_source": "estimated"}
    row.update(kw)
    return row


def test_smartstore_스윕이_정산예정일과_완료일을_쓴다(session, monkeypatch):
    OS.save([_ss_row()], session=session)
    from lemouton.markets import order_export as oe
    monkeypatch.setattr(oe, "_active_accounts", lambda market: [(None, "본계정")])
    monkeypatch.setattr(oe, "_account_client", lambda market, prefix=None: object())
    from shared.platforms.smartstore import settlements as _ss

    def _fake_iter(search_date=None, period_type=None, client=None, **kw):
        yield {"productOrderId": "P1", "orderId": "O1",
               "settleExpectAmount": 47120, "productOrderType": "PROD_ORDER",
               "settleExpectDate": "2026-08-12",
               "settleCompleteDate": "2026-08-12"}

    monkeypatch.setattr(_ss, "iter_settle_by_case", _fake_iter)
    now = _dt.datetime.now(KST)
    stat = OI.refresh_settlement_smartstore(since=now, until=now, session=session)

    assert stat["updated"] == 1
    stored = OS.load(["smartstore"], since="2000-01-01", until="2999-01-01",
                     session=session)[0]
    assert str(stored["정산예정금액"]) == "47120"
    assert stored["정산예정일"] == "2026-08-12"
    assert stored["_settle_paid_date"] == "2026-08-12"   # 완료일 = 실지급 확인


# ── 11번가: 파서가 송금예정일·구매확정일을 담고 스윕이 쓴다 ──────────────────

def test_eleven11_파서가_송금예정일과_구매확정일을_담는다():
    from shared.platforms.eleven11.settlement import parse_settlement_details
    xml = """<?xml version="1.0" encoding="utf-8"?>
<ns2:seStlDtlList xmlns:ns2="http://x">
  <seStlDtl>
    <ordNo>111</ordNo><ordPrdSeq>1</ordPrdSeq><stlAmt>65032</stlAmt>
    <selPrcAmt>73200</selPrcAmt><deductAmt>8168</deductAmt>
    <stlPlnDy>2026/08/20</stlPlnDy><pocnfrmDt>20260818</pocnfrmDt>
  </seStlDtl>
</ns2:seStlDtlList>"""
    out = parse_settlement_details(xml)
    ent = out[("111", "1")]
    assert ent["정산금액"] == 65032
    assert ent["송금예정일"] == "2026-08-20"
    assert ent["구매확정일"] == "2026-08-18"


def _e11_row(ono="111", seq="1", **kw):
    row = {L.FIELD: f"eleven11|{ono}|{seq}", "판매처": "11번가", "쇼핑몰": "11번가",
           "오픈마켓주문번호": ono, "_send_ids": {"ord_prd_seq": seq},
           "주문일": _order_date(20), "주문상태": "구매확정",
           "상품명": "운동화", "단가": 73200, "수량": 1, "실결제금액": 73200,
           "배송비": 0, "정산예정금액": 65000, "_settle_source": "estimated"}
    row.update(kw)
    return row


def test_eleven11_스윕이_송금예정일을_쓴다(session, monkeypatch):
    OS.save([_e11_row()], session=session)
    monkeypatch.setattr(OI, "_esm_settlement_clients",
                        lambda market: [("계정A", object())])
    from shared.platforms.eleven11 import settlement as _el
    monkeypatch.setattr(
        _el, "settlement_detail_map",
        lambda since, until, *, client: {("111", "1"): {"정산금액": 65032,
                                                        "송금예정일": "2026-08-20"}})

    stat = OI.refresh_settlement_eleven11(session=session)

    assert stat["updated"] == 1
    stored = OS.load(["eleven11"], since="2000-01-01", until="2999-01-01",
                     session=session)[0]
    assert str(stored["정산예정금액"]) == "65032"
    assert stored["정산예정일"] == "2026-08-20"


def test_eleven11_이미_real_행에도_날짜만_백필(session, monkeypatch):
    OS.save([_e11_row(정산예정금액=65032, _settle_source="real")], session=session)
    monkeypatch.setattr(OI, "_esm_settlement_clients",
                        lambda market: [("계정A", object())])
    from shared.platforms.eleven11 import settlement as _el
    monkeypatch.setattr(
        _el, "settlement_detail_map",
        lambda since, until, *, client: {("111", "1"): {"정산금액": 11111,
                                                        "송금예정일": "2026-08-20"}})

    stat = OI.refresh_settlement_eleven11(session=session)

    assert stat["updated"] == 1
    stored = OS.load(["eleven11"], since="2000-01-01", until="2999-01-01",
                     session=session)[0]
    assert str(stored["정산예정금액"]) == "65032"    # 금액 불가침
    assert stored["정산예정일"] == "2026-08-20"
