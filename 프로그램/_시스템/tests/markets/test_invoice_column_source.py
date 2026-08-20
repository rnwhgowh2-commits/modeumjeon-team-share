# -*- coding: utf-8 -*-
"""[TEST] 「송장입력」 칸은 마켓이 이미 들고 있는 송장을 그대로 읽어야 한다.

2026-07-10 실제 사고:
  · 스마트스토어 118행 · 롯데온 154행 전부 「송장미입력」으로 표시됐다.
  · 사장님이 송장을 손으로 다시 입력했고, 그 번호가 마켓의 실제 송장과 달랐다.
  · 안 읽어오는 것 자체가 오입력의 원인이다 — 빈칸은 '없다'가 아니라 '안 봤다'였다.

2026-07-23 같은 사고 재발(옥션·G마켓):
  · 화면 「송장입력」 칸이 G마켓 배송완료 줄 전부 '확인 불가'로 떴다.
  · 원인은 마켓이 안 준 게 아니라 **우리가 안 읽은 것** — 주문조회 응답에 NoSongjang 이 있다.

각 마켓의 송장 출처(라이브 실측 / 데이터 코드 지도):
  · 스마트스토어 = 주문 상세의 delivery.trackingNumber
  · 롯데온       = 진행단계 API(140) 의 invcNo   ※ 출고지시(209) 응답엔 송장 필드가 없다
  · 옥션·G마켓   = 주문조회(esm:67) NoSongjang / 클레임(esm:53·59) ShippingInfo.InvoiceNo
"""
import datetime as _dt

from lemouton.markets.order_export import KST


def _kst(y, m, d):
    """스마트스토어 빌더는 now(KST) 와 비교하므로 시간대 있는 값이어야 한다."""
    return _dt.datetime(y, m, d, tzinfo=KST)


class TestSmartstoreInvoiceColumn:
    def test_tracking_number_is_read_from_delivery(self, monkeypatch):
        import shared.platforms.smartstore.orders as ss
        import shared.platforms.smartstore.settlements as st
        from lemouton.markets import order_export as oe

        monkeypatch.setattr(ss, "iter_changed_product_order_ids",
                            lambda *a, **k: ["2026070936855501"])
        monkeypatch.setattr(ss, "fetch_order_detail", lambda ids, client=None: {"data": [{
            "productOrder": {"productOrderId": "2026070936855501", "productName": "스카프",
                             "quantity": 1, "productOrderStatus": "DELIVERING"},
            "order": {"orderId": "O1", "orderDate": "2026-07-09T18:04:52.000+09:00"},
            "delivery": {"deliveryCompany": "KGB", "trackingNumber": "44749740582"},
        }]})
        monkeypatch.setattr(st, "settle_expect_maps", lambda **k: ({}, {}))

        rows = oe.smartstore_order_rows(_kst(2026, 7, 9), _kst(2026, 7, 10), client=object())
        assert len(rows) == 1
        assert rows[0]["송장입력"] == "44749740582"

    def test_missing_delivery_leaves_blank_not_crash(self, monkeypatch):
        """발송 전 주문은 delivery 자체가 없다 — 빈칸이면 되고, 터지면 안 된다."""
        import shared.platforms.smartstore.orders as ss
        import shared.platforms.smartstore.settlements as st
        from lemouton.markets import order_export as oe

        monkeypatch.setattr(ss, "iter_changed_product_order_ids", lambda *a, **k: ["P2"])
        monkeypatch.setattr(ss, "fetch_order_detail", lambda ids, client=None: {"data": [{
            "productOrder": {"productOrderId": "P2", "productOrderStatus": "PAYED"},
            "order": {"orderId": "O2", "orderDate": "2026-07-09T10:00:00.000+09:00"},
        }]})
        monkeypatch.setattr(st, "settle_expect_maps", lambda **k: ({}, {}))

        rows = oe.smartstore_order_rows(_kst(2026, 7, 9), _kst(2026, 7, 10), client=object())
        assert rows[0]["송장입력"] == ""


class TestLotteonInvoiceColumn:
    def _patch_claims(self, monkeypatch):
        import shared.platforms.lotteon.claims as clm
        for fn in ("iter_cancel", "iter_return", "iter_exchange"):
            monkeypatch.setattr(clm, fn, lambda *a, **k: [])
        monkeypatch.setattr(clm, "commission_map", lambda *a, **k: {})

    def test_invoice_comes_from_progress_api_not_delivery_order(self, monkeypatch):
        """출고지시 응답에 송장이 없어도, 진행단계의 invcNo 로 채워져야 한다."""
        import shared.platforms.lotteon.orders as lo
        from lemouton.markets import order_export as oe
        self._patch_claims(monkeypatch)

        monkeypatch.setattr(lo, "iter_delivery_orders", lambda *a, **k: [{
            "odNo": "OD1", "odSeq": "1", "procSeq": "1", "spdNo": "S1", "sitmNo": "I1",
            "odQty": "1", "spdNm": "가방", "sitmNm": "블랙", "odCmptDttm": "20260709180452",
            "odPrgsStepCd": "11",
        }])
        monkeypatch.setattr(lo, "iter_progress_states", lambda *a, **k: [{
            "odNo": "OD1", "odSeq": "1", "odPrgsStepCd": "14",
            "dvTrcStatDttm": "20260710120000", "invcNo": "253744052100", "dvCoCd": "0005",
        }])

        rows = oe.lotteon_order_rows(_dt.datetime(2026, 7, 9), _dt.datetime(2026, 7, 10),
                                     client=object())
        assert len(rows) == 1
        assert rows[0]["송장입력"] == "253744052100"

    def test_no_invoice_yet_stays_blank(self, monkeypatch):
        """아직 발송 전(invcNo 없음)이면 빈칸 — 옛 값을 지어내지 않는다."""
        import shared.platforms.lotteon.orders as lo
        from lemouton.markets import order_export as oe
        self._patch_claims(monkeypatch)

        monkeypatch.setattr(lo, "iter_delivery_orders", lambda *a, **k: [{
            "odNo": "OD2", "odSeq": "1", "spdNm": "가방", "odCmptDttm": "20260709180452",
            "odPrgsStepCd": "11",
        }])
        monkeypatch.setattr(lo, "iter_progress_states", lambda *a, **k: [{
            "odNo": "OD2", "odSeq": "1", "odPrgsStepCd": "21",
            "dvTrcStatDttm": "20260710120000", "invcNo": None,
        }])

        rows = oe.lotteon_order_rows(_dt.datetime(2026, 7, 9), _dt.datetime(2026, 7, 10),
                                     client=object())
        assert rows[0]["송장입력"] == ""


class TestEsmInvoiceColumn:
    """옥션·G마켓 — 주문조회가 이미 준 송장을 그대로 읽는다."""

    SHIPPED = {
        "OrderNo": "A1", "OrderDate": "2026-07-15T10:00:00", "OrderStatus": 4,
        "GoodsName": "코트", "SalePrice": 50000, "ContrAmount": 1,
        "TakbaeName": "CJ대한통운", "NoSongjang": "612345678901",
    }

    def test_invoice_comes_from_no_songjang(self, monkeypatch):
        """배송완료 주문의 NoSongjang(발송 송장번호)이 「송장입력」에 그대로 실린다."""
        from lemouton.markets import order_export as oe
        monkeypatch.setattr("shared.platforms.esm.orders.iter_orders",
                            lambda *a, **k: iter([dict(self.SHIPPED)]))
        r = oe.esm_order_rows("gmarket", None, None, client=object())[0]
        assert r["송장입력"] == "612345678901"
        assert r["택배사"] == "CJ대한통운"          # 원장(invoice_ledger) 저장용

    def test_before_shipping_stays_blank(self, monkeypatch):
        """발송 전엔 NoSongjang 이 null 로 온다 — 빈칸이어야 하고 지어내면 안 된다."""
        from lemouton.markets import order_export as oe
        od = dict(self.SHIPPED, OrderStatus=1, NoSongjang=None, TakbaeName=None)
        monkeypatch.setattr("shared.platforms.esm.orders.iter_orders",
                            lambda *a, **k: iter([od]))
        r = oe.esm_order_rows("gmarket", None, None, client=object())[0]
        assert r["송장입력"] == ""

    def test_claim_row_uses_original_shipping_invoice(self, monkeypatch):
        """반품 행은 주문조회로 안 온다 — 클레임 응답의 원배송 송장(ShippingInfo)을 쓴다."""
        from lemouton.markets import order_export as oe
        import shared.platforms.esm.claims as clm
        import shared.platforms.esm.orders as eo

        monkeypatch.setattr(eo, "iter_orders", lambda *a, **k: iter([]))
        monkeypatch.setattr(eo, "fill_from_product",
                            lambda *a, **k: (None, "테스트: 상품API 미호출"))
        monkeypatch.setattr(clm, "iter_all", lambda *a, **k: iter([{
            "OrderNo": "R9", "OrderDate": "2026-07-15T10:00:00", "_claim_kind": "return",
            "ReturnStatus": 6, "ShippingInfo": {"InvoiceNo": "556677889900"},
        }]))
        rows = oe.esm_order_rows("gmarket", _dt.datetime(2026, 7, 14),
                                 _dt.datetime(2026, 7, 16), client=object(),
                                 include_settlement=False)
        assert rows[0]["송장입력"] == "556677889900"
