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
    assert r["쇼핑몰"] == "04.스마트스토어"


def test_order_rows_rejects_unsupported():
    for mk in ("coupang", "lotteon", "eleven11"):
        with pytest.raises(ValueError):
            oe.order_rows(mk, days=7)          # 추측 데이터 안 만듦


def test_rows_to_xlsx_has_header_and_row():
    xlsx = oe.rows_to_xlsx([{"상품명": "코트", "정산예정금액": 100}])
    assert xlsx[:2] == b"PK"                    # xlsx = zip
    import io, openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(xlsx))
    ws = wb.active
    assert [(c.value or "") for c in ws[1]] == oe.HEADER   # 빈 열은 None→"" 정규화
    assert ws[2][1].value == "코트"             # 상품명 열


def test_supported_is_smartstore_only():
    assert oe.SUPPORTED == {"smartstore"}       # 정직: 실제 되는 것만
