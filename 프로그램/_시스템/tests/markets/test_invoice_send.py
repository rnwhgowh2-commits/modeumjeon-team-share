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

    def test_smartstore_logen_is_kgb_measured_from_market(self):
        """스스 로젠택배 = KGB. LOGEN 은 오픈소스 근거의 추측이었고 **틀렸다**.

        근거(2026-07-10 라이브 실측): 판매자센터에 「로젠택배」로 뜨는 주문의
        API delivery.deliveryCompany 값이 KGB. 쿠팡과 우연히 같은 코드였을 뿐이다.
        """
        from lemouton.markets.invoice_send import resolve_courier_code
        assert resolve_courier_code("smartstore", "로젠택배") == "KGB"
        assert resolve_courier_code("coupang", "로젠택배") == "KGB"

    def test_smartstore_unknown_courier_still_raises(self):
        """확보한 이름만 매핑 — 모르는 택배사는 추측하지 않는다."""
        from lemouton.markets.invoice_send import resolve_courier_code, CourierCodeUnknown
        with pytest.raises(CourierCodeUnknown):
            resolve_courier_code("smartstore", "없는택배")

    @pytest.mark.parametrize("name", ["롯데택배", "우체국택배"])
    def test_smartstore_unproven_courier_blocked(self, name):
        """이름↔코드 교차확인 못 한 택배사는 전송하지 않는다.

        실측에서 HYUNDAI·JMNP 코드가 관측됐지만 어느 택배사인지 확인되지 않았다.
        기존 LOTTE·EPOST 는 관측조차 되지 않았다 → 추측 전송 금지.
        """
        from lemouton.markets.invoice_send import resolve_courier_code, CourierCodeUnknown
        with pytest.raises(CourierCodeUnknown):
            resolve_courier_code("smartstore", name)

    def test_smartstore_live_send_passes_naver_code(self, monkeypatch):
        import shared.platforms.smartstore.orders as ss
        got = {}

        def fake(ids, code, inv, client=None):
            got.update(ids=ids, code=code, inv=inv)
            return {"data": {"successProductOrderIds": ["P1"], "failProductOrderInfos": []}}

        monkeypatch.setattr(ss, "send_tracking", fake)
        from lemouton.markets.invoice_send import send_invoice
        r = send_invoice(market="smartstore", order_no="P1", courier_name="로젠택배",
                         invoice_no="777", client=object(), live=True)
        assert r.success is True
        assert got == {"ids": ["P1"], "code": "KGB", "inv": "777"}


# ── 거짓 성공 차단 — HTTP 200 이어도 본문이 실패를 담는다 ──────────
class TestNoFalseSuccess:
    """★ 2026-07-10 첫 실전송에서 드러난 결함.

    네이버 dispatch·쿠팡 invoices 는 HTTP 200 을 주면서 본문에 개별 실패를 담는다.
    클라이언트가 2xx 만 보고 성공을 반환해, 마켓에 반영되지 않은 송장이 「✓ 전송」으로 표시됐다.
    """

    def test_smartstore_fail_info_in_200_body_is_failure(self, monkeypatch):
        import shared.platforms.smartstore.orders as ss
        monkeypatch.setattr(ss, "send_tracking", lambda *a, **k: {
            "data": {"successProductOrderIds": [],
                     "failProductOrderInfos": [
                         {"productOrderId": "P1", "code": "ALREADY_DISPATCHED",
                          "message": "이미 발송처리된 주문입니다"}]}})
        from lemouton.markets.invoice_send import send_invoice
        r = send_invoice(market="smartstore", order_no="P1", courier_name="로젠택배",
                         invoice_no="777", client=object(), live=True)
        assert r.success is False
        assert "이미 발송처리된 주문입니다" in (r.error or "")

    def test_smartstore_order_absent_from_success_list_is_failure(self, monkeypatch):
        """실패 목록이 비어 있어도, 성공 목록에 내 주문이 없으면 성공이 아니다."""
        import shared.platforms.smartstore.orders as ss
        monkeypatch.setattr(ss, "send_tracking", lambda *a, **k: {
            "data": {"successProductOrderIds": ["OTHER"], "failProductOrderInfos": []}})
        from lemouton.markets.invoice_send import send_invoice
        r = send_invoice(market="smartstore", order_no="P1", courier_name="로젠택배",
                         invoice_no="777", client=object(), live=True)
        assert r.success is False

    def test_smartstore_unreadable_response_is_not_success(self, monkeypatch):
        """응답에서 성공을 확인하지 못하면 '전송됨'이라 말하지 않는다(확인 불가=실패)."""
        import shared.platforms.smartstore.orders as ss
        monkeypatch.setattr(ss, "send_tracking", lambda *a, **k: {})
        from lemouton.markets.invoice_send import send_invoice
        r = send_invoice(market="smartstore", order_no="P1", courier_name="로젠택배",
                         invoice_no="777", client=object(), live=True)
        assert r.success is False
        assert "확인" in (r.error or "")

    def test_coupang_nonzero_code_in_200_body_is_failure(self, monkeypatch):
        import shared.platforms.coupang.orders as cp
        monkeypatch.setattr(cp, "send_tracking", lambda *a, **k: {
            "code": 400, "message": "이미 송장이 등록된 주문"})
        from lemouton.markets.invoice_send import send_invoice
        r = send_invoice(market="coupang", order_no="100", courier_name="로젠택배",
                         invoice_no="1234567890",
                         send_ids={"shipment_box_id": "SB1", "order_sheet_id": "100"},
                         client=object(), live=True)
        assert r.success is False
        assert "이미 송장이 등록된 주문" in (r.error or "")

    def test_coupang_per_item_failure_is_failure(self, monkeypatch):
        import shared.platforms.coupang.orders as cp
        monkeypatch.setattr(cp, "send_tracking", lambda *a, **k: {
            "code": 200, "data": [{"shipmentBoxId": "SB1", "succeed": False,
                                   "resultMessage": "운송장번호 형식 오류"}]})
        from lemouton.markets.invoice_send import send_invoice
        r = send_invoice(market="coupang", order_no="100", courier_name="로젠택배",
                         invoice_no="1234567890",
                         send_ids={"shipment_box_id": "SB1", "order_sheet_id": "100"},
                         client=object(), live=True)
        assert r.success is False
        assert "운송장번호 형식 오류" in (r.error or "")


# ── 이미 발송된 주문 보호 ────────────────────────────────────
class TestAlreadyShippedGuard:
    @pytest.mark.parametrize("status", ["배송중", "배송완료", "구매확정"])
    def test_shipped_order_is_not_overwritten(self, status, monkeypatch):
        """이미 송장이 붙은 주문에 다른 번호를 덮어쓰면 고객 배송조회가 오염된다."""
        import shared.platforms.smartstore.orders as ss
        called = []
        monkeypatch.setattr(ss, "send_tracking", lambda *a, **k: called.append(1))
        from lemouton.markets.invoice_send import send_invoice
        r = send_invoice(market="smartstore", order_no="P1", courier_name="로젠택배",
                         invoice_no="777", client=object(), live=True,
                         order_status=status)
        assert r.success is False
        assert "이미 발송" in (r.error or "")
        assert called == []                      # 마켓 호출조차 하지 않는다

    def test_pre_shipment_order_still_sends(self, monkeypatch):
        import shared.platforms.smartstore.orders as ss
        monkeypatch.setattr(ss, "send_tracking", lambda *a, **k: {
            "data": {"successProductOrderIds": ["P1"], "failProductOrderInfos": []}})
        from lemouton.markets.invoice_send import send_invoice
        r = send_invoice(market="smartstore", order_no="P1", courier_name="로젠택배",
                         invoice_no="777", client=object(), live=True,
                         order_status="결제완료")
        assert r.success is True


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
    def test_logen_code_differs_per_market(self):
        """로젠택배: 롯데온 0005 / 쿠팡 KGB / 네이버 KGB.

        롯데온 0005 는 진행단계 API 의 dvCoCd 로, 네이버 KGB 는 delivery.deliveryCompany 로
        각각 라이브 실측(2026-07-10). 네이버가 LOGEN 이라는 옛 가정은 틀렸다.
        """
        from lemouton.markets.invoice_send import resolve_courier_code
        assert resolve_courier_code("lotteon", "로젠택배") == "0005"
        assert resolve_courier_code("coupang", "로젠택배") == "KGB"
        assert resolve_courier_code("smartstore", "로젠택배") == "KGB"

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
