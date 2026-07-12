# -*- coding: utf-8 -*-
"""[TEST] 전송 직후 마켓에 실제 등록된 송장번호 되읽기(read-back).

목적: 화면의 「✓ 전송」 옆 숫자를 **입력값이 아니라 마켓 재조회값**으로 표시해,
      그 숫자 자체가 '마켓에 등록됨'의 증거가 되게 한다.

원칙:
  · 되읽기 실패(None)는 '전송 실패'가 아니다 — '아직 확인 불가'. 전송 성공/실패는 send_invoice 가 판정.
  · 못 읽었는데 입력값을 마켓값인 척 보여주지 않는다(폴백 금지).
"""
import datetime as _dt


class TestReadbackSmartstore:
    def test_returns_market_tracking_number(self, monkeypatch):
        import shared.platforms.smartstore.orders as ss
        monkeypatch.setattr(ss, "fetch_order_detail", lambda ids, client=None: {"data": [{
            "productOrder": {"productOrderId": "2026071077855811"},
            "delivery": {"deliveryCompany": "KGB", "trackingNumber": "91720549351"},
        }]})
        from lemouton.markets.invoice_send import read_registered_invoice
        assert read_registered_invoice(market="smartstore", order_no="2026071077855811",
                                       client=object()) == "91720549351"

    def test_none_when_not_yet_registered(self, monkeypatch):
        import shared.platforms.smartstore.orders as ss
        monkeypatch.setattr(ss, "fetch_order_detail", lambda ids, client=None: {"data": [{
            "productOrder": {"productOrderId": "P1"}, "delivery": {}}]})
        from lemouton.markets.invoice_send import read_registered_invoice
        assert read_registered_invoice(market="smartstore", order_no="P1", client=object()) is None

    def test_none_on_read_error_not_raise(self, monkeypatch):
        import shared.platforms.smartstore.orders as ss
        def boom(*a, **k): raise RuntimeError("network")
        monkeypatch.setattr(ss, "fetch_order_detail", boom)
        from lemouton.markets.invoice_send import read_registered_invoice
        assert read_registered_invoice(market="smartstore", order_no="P1", client=object()) is None


class TestReadbackCoupang:
    def test_reads_invoice_from_order_items(self, monkeypatch):
        import shared.platforms.coupang.orders as cp
        monkeypatch.setattr(cp, "fetch_order_detail", lambda osid, client=None: {"data": {
            "orderId": "100", "orderItems": [{"invoiceNumber": "614111222333"}]}})
        from lemouton.markets.invoice_send import read_registered_invoice
        assert read_registered_invoice(market="coupang", order_no="100",
                                       send_ids={"order_sheet_id": "100"},
                                       client=object()) == "614111222333"

    def test_none_without_order_sheet_id(self):
        from lemouton.markets.invoice_send import read_registered_invoice
        assert read_registered_invoice(market="coupang", order_no="100",
                                       send_ids={}, client=object()) is None


class TestReadbackLotteon:
    def test_reads_invcno_from_progress_matching_odno(self, monkeypatch):
        import shared.platforms.lotteon.orders as lo
        monkeypatch.setattr(lo, "iter_progress_states", lambda *a, **k: [
            {"odNo": "OD1", "odSeq": "1", "invcNo": "253744052100",
             "dvTrcStatDttm": "20260710120000"},
            {"odNo": "OTHER", "odSeq": "1", "invcNo": "999", "dvTrcStatDttm": "20260710130000"},
        ])
        from lemouton.markets.invoice_send import read_registered_invoice
        assert read_registered_invoice(market="lotteon", order_no="OD1",
                                       send_ids={"od_no": "OD1", "od_seq": "1"},
                                       client=object()) == "253744052100"

    def test_picks_latest_by_dttm(self, monkeypatch):
        import shared.platforms.lotteon.orders as lo
        monkeypatch.setattr(lo, "iter_progress_states", lambda *a, **k: [
            {"odNo": "OD1", "odSeq": "1", "invcNo": "OLD", "dvTrcStatDttm": "20260709100000"},
            {"odNo": "OD1", "odSeq": "1", "invcNo": "NEW", "dvTrcStatDttm": "20260710120000"},
        ])
        from lemouton.markets.invoice_send import read_registered_invoice
        assert read_registered_invoice(market="lotteon", order_no="OD1",
                                       send_ids={"od_no": "OD1", "od_seq": "1"},
                                       client=object()) == "NEW"


class TestReadbackEleven11:
    def test_reads_invcno_from_shipping_by_dlvno(self, monkeypatch):
        import shared.platforms.eleven11.orders as el
        monkeypatch.setattr(el, "iter_shipping", lambda *a, **k: [
            {"ordNo": "20260710X", "dlvNo": "D1", "invcNo": "91720092892"}])
        monkeypatch.setattr(el, "iter_delivered", lambda *a, **k: [])
        from lemouton.markets.invoice_send import read_registered_invoice
        assert read_registered_invoice(market="eleven11", order_no="20260710X",
                                       send_ids={"dlv_no": "D1"},
                                       client=object()) == "91720092892"


class TestReadbackUnsupported:
    def test_unknown_market_returns_none(self):
        from lemouton.markets.invoice_send import read_registered_invoice
        assert read_registered_invoice(market="auction", order_no="1", client=object()) is None
