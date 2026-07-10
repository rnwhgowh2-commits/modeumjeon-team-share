# -*- coding: utf-8 -*-
"""[TEST] 송장 전송 모듈 — 마켓 라우팅·택배사 코드·드라이런 게이트.

원칙(CLAUDE.md):
  · 실전송은 기본 잠금(드라이런). live=True 일 때만 마켓 API 호출.
  · 택배사 코드는 마켓마다 다름 — 확보 못 한 마켓은 추측 전송 금지, 명시 실패.
  · 전송 함수 없는 마켓(롯데온·11번가·옥션·G마켓)은 조용히 성공 금지, 명시 실패.
"""
import pytest


# ── 택배사 코드 ──────────────────────────────────────────────
class TestCourierCode:
    def test_coupang_logen_is_kgb(self):
        """로젠택배의 쿠팡 코드는 KGB (LOGEN 아님 — 추측하면 틀림)."""
        from lemouton.markets.invoice_send import resolve_courier_code
        assert resolve_courier_code("coupang", "로젠택배") == "KGB"

    def test_coupang_unknown_courier_raises(self):
        from lemouton.markets.invoice_send import resolve_courier_code, CourierCodeUnknown
        with pytest.raises(CourierCodeUnknown):
            resolve_courier_code("coupang", "없는택배")

    def test_smartstore_code_not_guessed(self):
        """스마트스토어 택배사 코드 미확보 — 추측 대신 명시 실패."""
        from lemouton.markets.invoice_send import resolve_courier_code, CourierCodeUnknown
        with pytest.raises(CourierCodeUnknown):
            resolve_courier_code("smartstore", "로젠택배")


# ── 드라이런 게이트 ──────────────────────────────────────────
class TestDryRun:
    def test_dry_run_makes_no_external_call(self, monkeypatch):
        """live=False 면 마켓 API 를 호출하지 않고 성공(미전송) 표시."""
        import shared.platforms.coupang.orders as cp
        called = []
        monkeypatch.setattr(cp, "send_tracking", lambda *a, **k: called.append(1))

        from lemouton.markets.invoice_send import send_invoice
        r = send_invoice(market="coupang", order_no="100", courier_name="로젠택배",
                         invoice_no="1234567890",
                         send_ids={"shipment_box_id": "SB1", "order_sheet_id": "100"},
                         live=False)
        assert r.success is True and r.dry_run is True
        assert called == []                       # 외부 호출 없음


# ── 쿠팡 실전송 ──────────────────────────────────────────────
class TestCoupangSend:
    def test_live_send_uses_shipment_box_and_kgb(self, monkeypatch):
        import shared.platforms.coupang.orders as cp
        got = {}

        def fake(shipment_box_id, order_sheet_id, delivery_company_code, invoice_number, client=None):
            got.update(sb=shipment_box_id, os=order_sheet_id,
                       code=delivery_company_code, inv=invoice_number)
            return {"code": 200}

        monkeypatch.setattr(cp, "send_tracking", fake)
        from lemouton.markets.invoice_send import send_invoice
        r = send_invoice(market="coupang", order_no="100", courier_name="로젠택배",
                         invoice_no="1234567890",
                         send_ids={"shipment_box_id": "SB1", "order_sheet_id": "100"},
                         client=object(), live=True)
        assert r.success is True and r.dry_run is False
        assert got == {"sb": "SB1", "os": "100", "code": "KGB", "inv": "1234567890"}

    def test_missing_shipment_box_fails_not_guesses(self):
        """shipmentBoxId 없으면 추측해서 보내지 않고 실패."""
        from lemouton.markets.invoice_send import send_invoice
        r = send_invoice(market="coupang", order_no="100", courier_name="로젠택배",
                         invoice_no="1", send_ids=None, client=object(), live=True)
        assert r.success is False
        assert "shipment" in (r.error or "").lower() or "식별자" in (r.error or "")


# ── 미지원 마켓 ──────────────────────────────────────────────
class TestUnsupportedMarket:
    @pytest.mark.parametrize("market", ["lotteon", "eleven11", "auction", "gmarket"])
    def test_unsupported_market_fails_loudly(self, market):
        """전송 함수 없는 마켓은 조용히 성공하지 않는다(거짓 성공 금지)."""
        from lemouton.markets.invoice_send import send_invoice
        r = send_invoice(market=market, order_no="1", courier_name="로젠택배",
                         invoice_no="1", live=True)
        assert r.success is False
        assert market in (r.error or "")
