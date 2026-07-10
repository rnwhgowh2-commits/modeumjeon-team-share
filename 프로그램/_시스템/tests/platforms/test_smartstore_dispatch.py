# -*- coding: utf-8 -*-
"""[TEST] 스마트스토어 발송처리(송장) 요청 본문.

근거: 네이버 커머스 dispatch 를 실제로 호출하는 독립 구현 2건이 일치.
  · POST /external/v1/pay-order/seller/product-orders/dispatch
  · body dispatchProductOrders[] = {productOrderId, deliveryMethod, deliveryCompanyCode, trackingNumber}
우리 기존 코드는 shippingCompany 를 보냈다(필드명 불일치) — 실전송을 한 적이 없어 드러나지 않았다.

⚠️ 라이브 미검증 — 실계정 1건 전송으로 최종 확인 필요.
"""


class FakeSS:
    def __init__(self):
        self.body = None
        self.path = None

    def request(self, method, path, body=None, query=""):
        self.path, self.body = path, body
        return {"ok": True}


def _dispatch_item(fake):
    return fake.body["dispatchProductOrders"][0]


def test_dispatch_body_uses_delivery_company_code():
    """택배사는 deliveryCompanyCode 로 보낸다(shippingCompany 아님)."""
    from shared.platforms.smartstore.orders import send_tracking
    fake = FakeSS()
    send_tracking(["P1"], "LOGEN", "1234567890", client=fake)
    item = _dispatch_item(fake)
    assert item["deliveryCompanyCode"] == "LOGEN"
    assert "shippingCompany" not in item


def test_dispatch_body_includes_delivery_method():
    from shared.platforms.smartstore.orders import send_tracking
    fake = FakeSS()
    send_tracking(["P1"], "LOGEN", "1", client=fake)
    assert _dispatch_item(fake)["deliveryMethod"] == "DELIVERY"


def test_dispatch_maps_each_product_order_id():
    from shared.platforms.smartstore.orders import send_tracking
    fake = FakeSS()
    send_tracking(["P1", "P2"], "LOGEN", "999", client=fake)
    items = fake.body["dispatchProductOrders"]
    assert [i["productOrderId"] for i in items] == ["P1", "P2"]
    assert all(i["trackingNumber"] == "999" for i in items)   # 합포장: 같은 송장


def test_dispatch_caps_at_30():
    from shared.platforms.smartstore.orders import send_tracking
    fake = FakeSS()
    send_tracking([f"P{i}" for i in range(40)], "LOGEN", "1", client=fake)
    assert len(fake.body["dispatchProductOrders"]) == 30
