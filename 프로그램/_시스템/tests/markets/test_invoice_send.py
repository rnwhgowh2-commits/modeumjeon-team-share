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

    def test_smartstore_logen_is_logen_not_kgb(self):
        """같은 로젠택배라도 마켓마다 코드가 다르다 — 스스=LOGEN, 쿠팡=KGB. 섞으면 오등록."""
        from lemouton.markets.invoice_send import resolve_courier_code
        assert resolve_courier_code("smartstore", "로젠택배") == "LOGEN"
        assert resolve_courier_code("coupang", "로젠택배") == "KGB"

    def test_smartstore_unknown_courier_still_raises(self):
        """확보한 이름만 매핑 — 모르는 택배사는 추측하지 않는다."""
        from lemouton.markets.invoice_send import resolve_courier_code, CourierCodeUnknown
        with pytest.raises(CourierCodeUnknown):
            resolve_courier_code("smartstore", "없는택배")

    def test_smartstore_live_send_passes_naver_code(self, monkeypatch):
        import shared.platforms.smartstore.orders as ss
        got = {}
        monkeypatch.setattr(ss, "send_tracking",
                            lambda ids, code, inv, client=None: got.update(ids=ids, code=code, inv=inv))
        from lemouton.markets.invoice_send import send_invoice
        r = send_invoice(market="smartstore", order_no="P1", courier_name="로젠택배",
                         invoice_no="777", client=object(), live=True)
        assert r.success is True
        assert got == {"ids": ["P1"], "code": "LOGEN", "inv": "777"}


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
class TestLotteonSend:
    def test_logen_code_is_0005_not_kgb_nor_logen(self):
        """로젠택배: 롯데온 0005 / 쿠팡 KGB / 네이버 LOGEN — 세 마켓 전부 다르다."""
        from lemouton.markets.invoice_send import resolve_courier_code
        assert resolve_courier_code("lotteon", "로젠택배") == "0005"
        assert resolve_courier_code("coupang", "로젠택배") == "KGB"
        assert resolve_courier_code("smartstore", "로젠택배") == "LOGEN"

    def test_missing_ids_fail_not_guess(self):
        from lemouton.markets.invoice_send import send_invoice
        r = send_invoice(market="lotteon", order_no="OD1", courier_name="로젠택배",
                         invoice_no="1", send_ids={"od_no": "OD1"}, client=object(), live=True)
        assert r.success is False and "식별자" in (r.error or "")

    def test_live_send_passes_all_ids(self, monkeypatch):
        import shared.platforms.lotteon.shipping as lo
        got = {}

        def fake(**kw):
            got.update(kw)
            return True

        monkeypatch.setattr(lo, "send_tracking", fake)
        from lemouton.markets.invoice_send import send_invoice
        ids = {"od_no": "OD1", "od_seq": "3", "proc_seq": "1",
               "spd_no": "LO#100", "sitm_no": "LO#10010", "qty": "2"}
        r = send_invoice(market="lotteon", order_no="OD1", courier_name="로젠택배",
                         invoice_no="777", send_ids=ids, client=object(), live=True)
        assert r.success is True
        assert got["delivery_company_code"] == "0005"
        assert got["od_no"] == "OD1" and got["sitm_no"] == "LO#10010" and got["qty"] == "2"

    def test_rejected_by_market_is_failure(self, monkeypatch):
        import shared.platforms.lotteon.shipping as lo
        monkeypatch.setattr(lo, "send_tracking", lambda **kw: False)
        from lemouton.markets.invoice_send import send_invoice
        ids = {"od_no": "OD1", "od_seq": "3", "spd_no": "S", "sitm_no": "I", "qty": "1"}
        r = send_invoice(market="lotteon", order_no="OD1", courier_name="로젠택배",
                         invoice_no="777", send_ids=ids, client=object(), live=True)
        assert r.success is False and "거부" in (r.error or "")


class TestEleven11Send:
    """전송 경로(reqdelivery)는 구현됐지만 **택배사 코드표가 미확보** — 추측해서 보내지 않는다.

    출처가 서로 다른 값을 주장한다(로젠: 5자리 00002 vs 2자리 05). 틀린 코드로 보내면
    고객 배송조회에 엉뚱한 택배사가 뜬다 → 확정 전까지 전송 차단.
    """

    def test_courier_code_is_not_guessed(self):
        from lemouton.markets.invoice_send import resolve_courier_code, CourierCodeUnknown
        with pytest.raises(CourierCodeUnknown):
            resolve_courier_code("eleven11", "로젠택배")

    def test_send_blocked_until_code_confirmed(self):
        from lemouton.markets.invoice_send import send_invoice
        r = send_invoice(market="eleven11", order_no="O1", courier_name="로젠택배",
                         invoice_no="777", send_ids={"dlv_no": "D1", "ord_no": "O1",
                                                     "ord_prd_seq": "1"},
                         client=object(), live=True)
        assert r.success is False
        assert "택배사 코드" in (r.error or "")

    def test_missing_dlv_no_fails_not_guess(self, monkeypatch):
        """dlvNo 는 주문번호로 대체 불가 — 없으면 보내지 않는다."""
        import lemouton.markets.invoice_send as m
        monkeypatch.setattr(m, "_ELEVEN11_COURIER", {"로젠택배": "00002"})
        r = m.send_invoice(market="eleven11", order_no="O1", courier_name="로젠택배",
                           invoice_no="777", send_ids={"ord_no": "O1"},
                           client=object(), live=True)
        assert r.success is False and "식별자" in (r.error or "")

    def test_live_send_uses_dlv_no_once_code_known(self, monkeypatch):
        import lemouton.markets.invoice_send as m
        import shared.platforms.eleven11.shipping as sh
        got = {}
        monkeypatch.setattr(m, "_ELEVEN11_COURIER", {"로젠택배": "00002"})
        monkeypatch.setattr(sh, "send_tracking", lambda **kw: got.update(kw) or True)

        r = m.send_invoice(market="eleven11", order_no="O1", courier_name="로젠택배",
                           invoice_no="777", send_ids={"dlv_no": "D77", "ord_no": "O1",
                                                       "ord_prd_seq": "2"},
                           client=object(), live=True)
        assert r.success is True
        assert got["dlv_no"] == "D77" and got["delivery_company_code"] == "00002"
        assert got["invoice_number"] == "777"


class TestUnsupportedMarket:
    @pytest.mark.parametrize("market", ["auction", "gmarket"])
    def test_unsupported_market_fails_loudly(self, market):
        """전송 함수 없는 마켓은 조용히 성공하지 않는다(거짓 성공 금지)."""
        from lemouton.markets.invoice_send import send_invoice
        r = send_invoice(market=market, order_no="1", courier_name="로젠택배",
                         invoice_no="1", live=True)
        assert r.success is False
        assert market in (r.error or "")
