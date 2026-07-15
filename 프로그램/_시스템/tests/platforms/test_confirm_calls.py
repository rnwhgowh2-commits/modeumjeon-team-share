# -*- coding: utf-8 -*-
"""[TEST] 마켓별 '배송준비중 전환' 요청 모양 고정 (라이브 호출 없이 body/path 검증).

실제 마켓 전이는 라이브 미검증이지만, 우리가 '무엇을 보내는지'는 여기서 못박는다.
스펙이 틀리면 라이브 되읽기 검증이 잡지만, 최소한 의도한 형태는 회귀로 지킨다.
"""


class FakeClient:
    def __init__(self, vendor_id=None):
        self._cfg = {"vendor_id": vendor_id} if vendor_id else {}
        self.calls = []

    def request(self, method=None, path=None, body=None, query=None):
        self.calls.append({"method": method, "path": path, "body": body, "query": query})
        # 스스 발주확인은 네이버식 성공 본문을 돌려준다(confirm 이 본문을 검사하므로).
        if path and path.endswith("/confirm"):
            return {"data": {"successProductOrderIds": list((body or {}).get("productOrderIds") or [])}}
        return {"returnCode": "0000"}   # 롯데온 성공 코드(다른 마켓은 무시)


def test_coupang_acknowledge_shape():
    from shared.platforms.coupang import orders as cp
    c = FakeClient(vendor_id="V123")
    cp.acknowledge(["11", "22"], client=c)
    call = c.calls[0]
    assert call["method"] == "PUT"
    assert call["path"].endswith("/vendors/V123/ordersheets/acknowledgement")
    assert call["body"] == {"vendorId": "V123", "shipmentBoxIds": [11, 22]}  # 숫자화


def test_coupang_acknowledge_no_ids_raises():
    from shared.platforms.coupang import orders as cp
    import pytest
    with pytest.raises(ValueError):
        cp.acknowledge([], client=FakeClient(vendor_id="V1"))


def test_smartstore_confirm_shape():
    from shared.platforms.smartstore import orders as ss
    c = FakeClient()
    ss.confirm_orders(["PO1", "PO2"], client=c)
    call = c.calls[0]
    assert call["method"] == "POST"
    assert call["path"] == "/external/v1/pay-order/seller/product-orders/confirm"
    assert call["body"] == {"productOrderIds": ["PO1", "PO2"]}


def test_smartstore_confirm_raises_when_not_confirmed():
    """200 이지만 본문에 성공이 없으면(=미확정) 거짓성공 대신 예외 — 되읽기 전에 잡는다."""
    from shared.platforms.smartstore import orders as ss
    import pytest

    class NoOkClient(FakeClient):
        def request(self, method=None, path=None, body=None, query=None):
            return {"data": {"successProductOrderIds": [], "failProductOrderInfos":
                             [{"productOrderId": "PO1", "code": "X", "message": "안됨"}]}}
    with pytest.raises(RuntimeError):
        ss.confirm_orders(["PO1"], client=NoOkClient())


def test_lotteon_set_preparing_shape():
    from shared.platforms.lotteon import shipping as lo
    c = FakeClient()
    ok = lo.set_preparing(od_no="OD1", od_seq="1", proc_seq="1",
                          spd_no="SP1", sitm_no="SI1", qty="2", client=c)
    assert ok is True
    item = c.calls[0]["body"]["deliveryProgressStateList"][0]
    assert item["odPrgsStepCd"] == "12"       # 상품준비(배송준비중)
    assert item["dvRtrvDvsCd"] == "DV"
    assert (item["odNo"], item["spdNo"], item["sitmNo"], item["slQty"]) == ("OD1", "SP1", "SI1", "2")
    assert item["invcNo"] == "" and item["dvCoCd"] == ""   # 준비 단계엔 송장 없음


def test_confirm_api_eleven11_unsupported():
    from lemouton.orders import confirm_api as capi
    import pytest
    with pytest.raises(capi.ConfirmUnsupported):
        capi.confirm_targets("eleven11", [{"오픈마켓주문번호": "E1"}], client=object())


def test_confirm_api_routes_and_requires_ids():
    from lemouton.orders import confirm_api as capi
    import pytest
    # 쿠팡: shipmentBox 없으면 추측 안 하고 예외
    with pytest.raises(ValueError):
        capi.confirm_targets("coupang", [{"오픈마켓주문번호": "C1", "_send_ids": {}}], client=FakeClient(vendor_id="V1"))
    # 롯데온: 식별자 없으면 예외
    with pytest.raises(ValueError):
        capi.confirm_targets("lotteon", [{"오픈마켓주문번호": "L1", "_send_ids": {}}], client=FakeClient())
