# -*- coding: utf-8 -*-
"""[TEST] 송장 빈칸의 두 의미 구분 — '송장미입력'(발송 전) vs '확인 불가'(발송됨·번호 미제공).

2026-07-10: 11번가는 구매확정(거래완료) 주문의 invcNo 를 API로 제공하지 않는다.
그 주문에 '송장미입력'이라 표기하면 '발송 안 함'으로 오해된다 — 실제론 발송 완료.
발송 단계의 빈 송장은 '확인 불가'로, 발송 전 빈 송장만 '송장미입력'으로.
"""
from lemouton.markets.order_export import _finalize_rows


def _row(status, invoice=""):
    return {"판매처": "11번가", "주문상태": status, "송장입력": invoice,
            "오픈마켓주문번호": "O1"}


class TestHonestInvoiceLabel:
    def test_confirmed_order_empty_invoice_is_unconfirmable(self):
        """구매확정 + 송장 없음 → '확인 불가'(발송은 됨)."""
        out = _finalize_rows([_row("구매확정")])
        assert out[0]["송장입력"] == "확인 불가"

    def test_pre_shipment_empty_invoice_is_missing(self):
        """결제완료(발송 전) + 송장 없음 → '송장미입력'(넣어야 함)."""
        out = _finalize_rows([_row("결제완료")])
        assert out[0]["송장입력"] == "송장미입력"

    def test_delivered_empty_invoice_is_unconfirmable(self):
        out = _finalize_rows([_row("배송완료")])
        assert out[0]["송장입력"] == "확인 불가"

    def test_real_invoice_is_kept_verbatim(self):
        """실제 송장이 있으면 그대로 둔다(상태와 무관)."""
        out = _finalize_rows([_row("구매확정", "91720549351")])
        assert out[0]["송장입력"] == "91720549351"

    def test_cancelled_order_empty_invoice_stays_missing(self):
        """취소완료는 발송 단계가 아니므로 '확인 불가' 아님."""
        out = _finalize_rows([_row("취소완료")])
        assert out[0]["송장입력"] == "송장미입력"
