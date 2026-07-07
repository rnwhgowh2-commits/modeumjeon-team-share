# -*- coding: utf-8 -*-
"""주문 엑셀 재사용 모듈 — Mock 단위테스트(스마트스토어 매핑·정산조인·xlsx·미지원마켓)."""
import datetime as dt

import pytest

from lemouton.markets import order_export as oe

KST = dt.timezone(dt.timedelta(hours=9))


class FakeSSClient:
    """SmartStoreClient 대역 — 엔드포인트별 응답 라우팅."""
    def request(self, method, path, query="", body=None):
        if "last-changed-statuses" in path:
            return {"data": {"lastChangeStatuses": [{"productOrderId": "P1"}]}}
        if path.endswith("/product-orders/query"):
            return {"data": [{
                "order": {"orderDate": "2026-07-05T09:00:00", "ordererName": "구매자A", "ordererTel": "01000000000"},
                "productOrder": {"productOrderId": "P1", "productName": "코트", "productOption": "블랙/95",
                                 "quantity": 1, "unitPrice": 189000,
                                 "shippingAddress": {"name": "수령자A", "tel1": "01011112222",
                                                     "zipCode": "13105", "baseAddress": "서울 어딘가", "detailedAddress": "101동"}},
            }]}
        if "pay-settle/settle/case" in path:
            return {"elements": [{"productOrderId": "P1", "settleExpectAmount": 169155}],
                    "pagination": {"totalPages": 1}}
        return {"data": {}}


def test_smartstore_rows_map_and_join(monkeypatch):
    since = dt.datetime(2026, 7, 5, tzinfo=KST)
    until = dt.datetime(2026, 7, 5, 23, tzinfo=KST)
    rows = oe.smartstore_order_rows(since, until, client=FakeSSClient())
    assert len(rows) == 1
    r = rows[0]
    assert r["상품명"] == "코트" and r["옵션"] == "블랙/95"
    assert r["수령자"] == "수령자A" and r["구매자"] == "구매자A"
    assert r["단가"] == 189000
    assert r["정산예정금액"] == 169155        # 정산 조인됨
    assert r["판매처"] == "스마트스토어"       # 판매처 열(B)


def test_order_rows_rejects_unsupported():
    for mk in ("eleven11", "gmarket", "auction"):
        with pytest.raises(ValueError):
            oe.order_rows(mk, days=7)          # UI 미노출 마켓 — 추측 데이터 안 만듦


def test_rows_to_xlsx_default_columns():
    xlsx = oe.rows_to_xlsx([{"판매처": "쿠팡", "상품명": "코트"}])
    assert xlsx[:2] == b"PK"                    # xlsx = zip
    import io, openpyxl
    ws = openpyxl.load_workbook(io.BytesIO(xlsx)).active
    assert [(c.value or "") for c in ws[1]] == oe.DEFAULT_COLUMNS
    assert ws[1][1].value == "판매처" and ws[1][2].value == "주문상태"   # B열·C열
    assert ws[2][1].value == "쿠팡"             # 판매처 값


def test_rows_to_xlsx_custom_columns_order():
    cols = ["판매처", "주문상태", "상품명"]        # 사용자 지정 부분집합·순서
    xlsx = oe.rows_to_xlsx([{"판매처": "쿠팡", "주문상태": "결제완료", "상품명": "코트", "단가": 9}], columns=cols)
    import io, openpyxl
    ws = openpyxl.load_workbook(io.BytesIO(xlsx)).active
    assert [c.value for c in ws[1]] == cols     # 지정 열만·순서대로
    assert [c.value for c in ws[2]] == ["쿠팡", "결제완료", "코트"]


def test_resolve_columns_filters_unknown():
    assert oe.resolve_columns(["상품명", "없는열", "판매처"]) == ["상품명", "판매처"]
    assert oe.resolve_columns([]) == oe.DEFAULT_COLUMNS
    assert oe.resolve_columns(None) == oe.DEFAULT_COLUMNS


def test_supported_markets():
    assert oe.SUPPORTED == {"smartstore", "lotteon", "coupang"}   # 3마켓 UI 노출


def test_coupang_settlement_join(monkeypatch):
    # 발주서 조회 → revenue-history 를 (주문번호,옵션ID)로 조인해 정산예정금액 채움
    class C:
        _cfg = {"vendor_id": "A00012345"}
        def request(self, method, path, query=""):
            if "ordersheets" in path:
                if "nextToken" in query:
                    return {"data": [], "nextToken": ""}
                return {"data": [{"shipmentBoxId": 1, "orderId": 777, "status": "FINAL_DELIVERY",
                        "orderer": {}, "receiver": {},
                        "orderItems": [{"vendorItemId": 9, "sellerProductName": "코트",
                                        "shippingCount": 1, "salesPrice": {"units": 189000}}]}],
                        "nextToken": ""}
            if "revenue-history" in path:
                return {"data": [{"orderId": 777, "items": [
                        {"vendorItemId": 9, "settlementAmount": 165155}]}], "hasNext": False}
            return {"data": []}
    since = dt.datetime(2026, 7, 5, tzinfo=oe.KST)
    until = dt.datetime(2026, 7, 8, tzinfo=oe.KST)
    rows = oe.coupang_order_rows(since, until, client=C())
    assert len(rows) == 1
    assert rows[0]["정산예정금액"] == 165155      # revenue-history 조인됨
    assert "_oid" not in rows[0] and "_vid" not in rows[0]   # 임시키 정리됨


def test_columns_bc_are_market_and_status():
    assert oe.ALL_COLUMNS[0] == "주문일"
    assert oe.ALL_COLUMNS[1] == "판매처"      # 요청: B열 판매처
    assert oe.ALL_COLUMNS[2] == "주문상태"    # 요청: C열 주문상태


def test_combined_rows_sorted_desc(monkeypatch):
    # 두 마켓 행을 합쳐 주문일 내림차순 정렬
    monkeypatch.setattr(oe, "order_rows", lambda mk, days=7, **k: {
        "coupang": [{"주문일": "2026-07-01", "판매처": "쿠팡"}],
        "lotteon": [{"주문일": "2026-07-05", "판매처": "롯데온"}],
    }[mk])
    out = oe.combined_order_rows(["coupang", "lotteon"], days=7)
    assert [r["주문일"] for r in out] == ["2026-07-05", "2026-07-01"]   # 최신 먼저


def test_status_ko_mapping():
    assert oe._status_ko("coupang", "INSTRUCT") == "상품준비중"
    assert oe._status_ko("smartstore", "DELIVERED") == "배송완료"
    assert oe._status_ko("lotteon", "11") == "출고지시"
    assert oe._status_ko("coupang", "UNKNOWN_X") == "UNKNOWN_X"   # 미매핑=원값(추측금지)
    assert oe._status_ko("coupang", None) == ""


class FakeCoupangClient:
    def __init__(self):
        self.calls = 0
        self._cfg = {"vendor_id": "A00012345"}   # 계정 클라이언트가 주입하는 vendor_id
        self.paths = []

    def request(self, method, path, query=""):
        self.calls += 1
        self.paths.append(path)
        # 첫 status 첫 페이지에만 1건, 나머지는 빈 목록(nextToken 없음)
        if self.calls == 1:
            return {"code": 200, "data": [{
                "shipmentBoxId": 1, "orderedAt": "2026-07-05T09:00:00+09:00",
                "parcelPrintMessage": "문앞",
                "orderer": {"name": "구매자A", "ordererNumber": "01000000000"},
                "receiver": {"name": "수령자A", "receiverNumber": "01011112222",
                             "addr1": "서울", "addr2": "101동", "postCode": "04315"},
                "orderItems": [{"vendorItemId": 9, "sellerProductName": "코트",
                                "sellerProductItemName": "블랙/95", "shippingCount": 1,
                                "salesPrice": {"units": 189000, "nanos": 0}}]}],
                "nextToken": ""}
        return {"code": 200, "data": [], "nextToken": ""}


def test_coupang_rows_flatten_and_map(monkeypatch):
    # 전역 COUPANG_VENDOR_ID 없어도 계정 클라이언트 _cfg.vendor_id 로 동작해야 함(버그수정)
    monkeypatch.delenv("COUPANG_VENDOR_ID", raising=False)
    since = dt.datetime(2026, 7, 5, tzinfo=oe.KST)
    until = dt.datetime(2026, 7, 6, tzinfo=oe.KST)
    fc = FakeCoupangClient()
    rows = oe.coupang_order_rows(since, until, client=fc)
    assert len(rows) == 1
    r = rows[0]
    assert r["상품명"] == "코트" and r["옵션"] == "블랙/95" and r["수량"] == 1
    assert r["수령자"] == "수령자A" and r["구매자"] == "구매자A"
    assert r["단가"] == 189000                 # 금액 객체 units 추출
    assert r["정산예정금액"] == ""              # 쿠팡 정산 별도(폴백 0 금지)
    assert r["쇼핑몰"] == "쿠팡"
    assert "/vendors/A00012345/ordersheets" in fc.paths[0]   # 클라 config vendor_id 사용
    assert "/api/v5/" in fc.paths[0]           # v5 정정 반영


class FakeLotteonClient:
    def request(self, method, path, body=None):
        return {"returnCode": "0000", "data": {"deliveryOrderList": [{
            "odCmptDttm": "20260705120000", "spdNm": "코트", "sitmNm": "블랙/95",
            "odQty": 1, "slPrc": 189000, "actualAmt": 170000,
            "dvpCustNm": "수령자A", "dvpMphnNo": "01011112222", "odrNm": "구매자A",
            "dvpZipNo": "04315", "dvpStnmZipAddr": "서울 어딘가", "dvpStnmDtlAddr": "101동",
            "dvMsg": "문앞", "mphnNo": "01000000000"}]}}


def test_lotteon_rows_map_from_delivery_orders():
    since = dt.datetime(2026, 7, 5, tzinfo=oe.KST)
    until = dt.datetime(2026, 7, 6, tzinfo=oe.KST)
    rows = oe.lotteon_order_rows(since, until, client=FakeLotteonClient())
    assert len(rows) == 1
    r = rows[0]
    assert r["주문일"] == "2026-07-05" and r["상품명"] == "코트" and r["옵션"] == "블랙/95"
    assert r["수령자"] == "수령자A" and r["구매자"] == "구매자A"
    assert r["단가"] == 189000 and r["정산예정금액"] == 170000
    assert r["판매처"] == "롯데온"


def test_lotteon_unescapes_html_entities():
    class C:
        def request(self, method, path, body=None):
            return {"data": {"deliveryOrderList": [{
                "odCmptDttm": "20260705", "spdNm": "&lt;매장정품&gt; 코트",
                "sitmNm": "R&amp;B / 100", "odQty": 1}]}}
    r = oe.lotteon_order_rows(dt.datetime(2026, 7, 5, tzinfo=oe.KST),
                              dt.datetime(2026, 7, 6, tzinfo=oe.KST), client=C())[0]
    assert r["상품명"] == "<매장정품> 코트"        # &lt; &gt; 해제
    assert r["옵션"] == "R&B / 100"                # &amp; 해제


def test_lotteon_ready_in_builders_and_supported():
    assert "lotteon" in oe._BUILDERS and "lotteon" in oe.SUPPORTED   # 코드+UI 노출
    assert oe._ENV_PREFIX["lotteon"] == "LOTTEON_MAIN"               # 실키 로드용 prefix
