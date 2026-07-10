# -*- coding: utf-8 -*-
"""[TEST] 송장 전송에 필요한 마켓별 식별자가 주문 행에 남는지.

쿠팡 송장 전송 API 는 shipmentBoxId(경로) + orderSheetId(본문) 을 요구한다
(shared/platforms/coupang/orders.py::send_tracking).
그런데 주문 행에는 「오픈마켓주문번호」=orderId 만 남고 shipmentBoxId 는
중복제거용으로만 쓰고 버려져, 화면에서 송장을 보낼 수 없다.
"""
import datetime as _dt

KST = _dt.timezone(_dt.timedelta(hours=9))

_BOX = {
    "shipmentBoxId": "SB-777",
    "orderId": "OID-123",
    "orderedAt": "2026-07-10T10:00:00",
    "shippingPrice": 0,
    "orderer": {"name": "구매자"},
    "receiver": {"name": "수령인", "addr1": "서울시", "addr2": "101동", "postCode": "01234"},
    "orderItems": [{
        "vendorItemId": "VI-1",
        "sellerProductName": "르무통 신발",
        "sellerProductItemName": "블랙 250",
        "shippingCount": 1,
        "salesPrice": 19000,
    }],
}


def _stub_fetch_orders(monkeypatch):
    """첫 호출만 발주서 1건, 이후 빈 목록(페이징·상태 순회 종료)."""
    calls = {"n": 0}

    def fake(w0, w1, client=None, status=None, next_token=None):
        calls["n"] += 1
        return {"data": [_BOX]} if calls["n"] == 1 else {"data": []}

    import shared.platforms.coupang.orders as cp_orders
    monkeypatch.setattr(cp_orders, "fetch_orders", fake)


def test_coupang_row_keeps_ids_needed_to_send_invoice(monkeypatch):
    """쿠팡 행은 송장 전송용 shipmentBoxId·orderSheetId 를 보존해야 한다."""
    _stub_fetch_orders(monkeypatch)
    from lemouton.markets.order_export import coupang_order_rows

    since = _dt.datetime(2026, 7, 9, tzinfo=KST)
    until = _dt.datetime(2026, 7, 11, tzinfo=KST)
    rows = coupang_order_rows(since, until, client=object())

    assert len(rows) == 1
    send = rows[0].get("_send_ids")
    assert send is not None, "송장 전송용 식별자(_send_ids)가 행에 없다"
    assert send["shipment_box_id"] == "SB-777"
    assert send["order_sheet_id"] == "OID-123"


def test_send_ids_survive_finalize(monkeypatch):
    """_finalize_rows(정산·배송비 정규화)를 거쳐도 식별자가 살아남아야 한다."""
    _stub_fetch_orders(monkeypatch)
    from lemouton.markets.order_export import coupang_order_rows, _finalize_rows

    since = _dt.datetime(2026, 7, 9, tzinfo=KST)
    until = _dt.datetime(2026, 7, 11, tzinfo=KST)
    rows = _finalize_rows(coupang_order_rows(since, until, client=object()))

    assert rows[0]["_send_ids"]["shipment_box_id"] == "SB-777"


def test_send_ids_not_leaked_into_excel_columns():
    """엑셀 열 목록에는 내부 식별자가 없어야 한다(출력 누출 방지)."""
    from lemouton.markets.order_export import ALL_COLUMNS

    assert not any(c.startswith("_") for c in ALL_COLUMNS)


# ── 11번가 ────────────────────────────────────────────────────
_XML_11 = """<?xml version="1.0" encoding="euc-kr"?><ns2:orders xmlns:ns2="http://x">
 <ns2:order><ns2:ordNo>202607100001</ns2:ordNo><ns2:ordPrdSeq>2</ns2:ordPrdSeq>
  <ns2:prdNm>스커트</ns2:prdNm><ns2:ordQty>1</ns2:ordQty><ns2:selPrc>19000</ns2:selPrc>
  <ns2:rcvrNm>홍길동</ns2:rcvrNm><ns2:ordDt>2026-07-08 16:53:53</ns2:ordDt></ns2:order>
</ns2:orders>"""


class _Fake11:
    def request(self, method, path, body=None):
        return _XML_11


def test_eleven11_row_keeps_ord_no_and_ord_prd_seq():
    """11번가 발송처리는 상품주문번호(ordPrdSeq)까지 필요 — 중복제거용으로만 쓰고 버리면 전송 불가."""
    from lemouton.markets.order_export import eleven11_order_rows, _finalize_rows

    since = _dt.datetime(2026, 7, 8, tzinfo=KST)
    until = _dt.datetime(2026, 7, 9, tzinfo=KST)
    rows = _finalize_rows(eleven11_order_rows(since, until, client=_Fake11()))

    send = rows[0].get("_send_ids")
    assert send is not None, "11번가 전송 식별자(_send_ids)가 행에 없다"
    assert send["ord_no"] == "202607100001"
    assert send["ord_prd_seq"] == "2"


# ── 롯데온 ────────────────────────────────────────────────────
class _FakeLo:
    def request(self, method, path, body=None):
        if "/delivery/" in path:
            return {"data": {"deliveryOrderList": [
                {"odNo": "OD777", "odSeq": "3", "spdNm": "코트", "odQty": "1",
                 "slPrc": "10000", "odPrgsStepCd": "11", "odCmptDttm": "20260708100000"}]}}
        return {"data": {}}


def test_lotteon_row_keeps_od_no_and_od_seq():
    """롯데온 배송상태 통보는 단품순번(odSeq) 필요 — _odseq 는 마지막에 pop 되어 사라진다."""
    from lemouton.markets.order_export import lotteon_order_rows, _finalize_rows

    since = _dt.datetime(2026, 7, 8, tzinfo=KST)
    until = _dt.datetime(2026, 7, 9, tzinfo=KST)
    rows = _finalize_rows(lotteon_order_rows(since, until, client=_FakeLo()))

    send = rows[0].get("_send_ids")
    assert send is not None, "롯데온 전송 식별자(_send_ids)가 행에 없다"
    assert send["od_no"] == "OD777"
    assert send["od_seq"] == "3"
