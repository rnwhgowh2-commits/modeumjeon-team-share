# -*- coding: utf-8 -*-
"""order_export._settle_source — real / estimated / none 태깅."""
import datetime as dt

from lemouton.markets import order_export as oe

KST = dt.timezone(dt.timedelta(hours=9))
SINCE = dt.datetime(2026, 7, 5, tzinfo=KST)
UNTIL = dt.datetime(2026, 7, 8, tzinfo=KST)


class CoupangSettled:
    _cfg = {"vendor_id": "A1"}

    def request(self, method, path, query=""):
        if "ordersheets" in path:
            return {"data": [{"shipmentBoxId": 1, "orderId": 100, "status": "FINAL_DELIVERY",
                              "orderer": {}, "receiver": {}, "shippingPrice": 0,
                              "orderItems": [{"vendorItemId": 9, "sellerProductName": "코트",
                                              "shippingCount": 1,
                                              "salesPrice": {"units": 10000}}]}],
                    "nextToken": ""}
        if "revenue-history" in path:
            return {"data": [{"orderId": 100,
                              "items": [{"vendorItemId": 9, "settlementAmount": 8800}]}],
                    "hasNext": False}
        return {"data": [], "nextToken": ""}


class CoupangUnsettled(CoupangSettled):
    def request(self, method, path, query=""):
        if "revenue-history" in path:
            return {"data": [], "hasNext": False}
        return CoupangSettled.request(self, method, path, query)


def test_coupang_settled_is_real():
    rows = oe.coupang_order_rows(SINCE, UNTIL, client=CoupangSettled())
    r = next(r for r in rows if str(r["오픈마켓주문번호"]) == "100")
    assert r["_settle_source"] == "real"
    assert r["정산예정금액"] == 8800


def test_coupang_unsettled_is_estimated():
    rows = oe.coupang_order_rows(SINCE, UNTIL, client=CoupangUnsettled())
    r = next(r for r in rows if str(r["오픈마켓주문번호"]) == "100")
    assert r["_settle_source"] == "estimated"
    assert r["정산예정금액"] == round(10000 * oe.CP_FEE_FACTOR)


def test_settle_source_survives_finalize():
    rows = oe._finalize_rows([{"주문일": "2026-07-05", "단가": 100, "수량": 1,
                               "정산예정금액": 88, "_settle_source": "estimated"}])
    assert rows[0]["_settle_source"] == "estimated"


def test_settle_source_not_in_xlsx_columns():
    """엑셀 출력 컬럼은 불변 — 기존 소비자 영향 없음."""
    assert "_settle_source" not in oe.ALL_COLUMNS
    assert "_settle_source" not in oe.resolve_columns(None)
