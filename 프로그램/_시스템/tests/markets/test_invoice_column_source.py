# -*- coding: utf-8 -*-
"""[TEST] 「송장입력」 칸은 마켓이 이미 들고 있는 송장을 그대로 읽어야 한다.

2026-07-10 실제 사고:
  · 스마트스토어 118행 · 롯데온 154행 전부 「송장미입력」으로 표시됐다.
  · 사장님이 송장을 손으로 다시 입력했고, 그 번호가 마켓의 실제 송장과 달랐다.
  · 안 읽어오는 것 자체가 오입력의 원인이다 — 빈칸은 '없다'가 아니라 '안 봤다'였다.

각 마켓의 송장 출처(라이브 실측):
  · 스마트스토어 = 주문 상세의 delivery.trackingNumber
  · 롯데온       = 진행단계 API(140) 의 invcNo   ※ 출고지시(209) 응답엔 송장 필드가 없다
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
