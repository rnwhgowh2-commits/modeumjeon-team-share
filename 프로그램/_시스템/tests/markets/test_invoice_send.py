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

    @pytest.mark.parametrize("name", ["롯데택배", "우체국택배", "CJ대한통운", "한진택배"])
    def test_smartstore_unproven_courier_blocked(self, name):
        """이름↔코드를 1:1 대조하지 못한 택배사는 전송하지 않는다(11번가와 같은 기준).

        CJGLS·HANJIN·HYUNDAI·JMNP 는 코드가 관측만 됐고, LOTTE·EPOST 는 관측조차 안 됐다.
        관측은 '그 코드가 존재한다'는 증거일 뿐 '그 이름이다'는 증거가 아니다.
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
    """택배사 코드는 **실계정 발송 이력으로 검증한 것만** 넣는다.

    라이브 실측(2026-07-10): 셀러오피스 배송관리 화면의 택배사 이름과 API 가 돌려준
    dlvEtprsCd 를 송장번호로 대조 — 로젠 92816272404→00002 / 롯데 317651308380→00012.
    검증 안 된 택배사(CJ·한진·우체국)는 표에 넣지 않는다(추측 전송 금지).
    """

    def test_verified_codes_only(self):
        from lemouton.markets.invoice_send import resolve_courier_code
        assert resolve_courier_code("eleven11", "로젠택배") == "00002"
        assert resolve_courier_code("eleven11", "롯데택배") == "00012"

    def test_same_courier_differs_across_markets(self):
        """로젠택배: 11번가 00002 / 쿠팡 KGB / 네이버 KGB / 롯데온 0005.

        네이버가 LOGEN 이라는 가정은 라이브 실측으로 반증됐다(2026-07-10).
        '마켓마다 다르다'는 원칙은 그대로다 — 네이버가 우연히 쿠팡과 같은 KGB 를 쓸 뿐.
        """
        from lemouton.markets.invoice_send import resolve_courier_code
        assert resolve_courier_code("eleven11", "로젠택배") == "00002"
        assert resolve_courier_code("coupang", "로젠택배") == "KGB"
        assert resolve_courier_code("smartstore", "로젠택배") == "KGB"
        assert resolve_courier_code("lotteon", "로젠택배") == "0005"

    def test_unverified_courier_is_not_guessed(self):
        """CJ·한진은 공개 출처 값만 있고 실계정으로 대조 못 함 → 보내지 않는다."""
        from lemouton.markets.invoice_send import resolve_courier_code, CourierCodeUnknown
        for name in ("CJ대한통운", "한진택배", "우체국택배"):
            with pytest.raises(CourierCodeUnknown):
                resolve_courier_code("eleven11", name)

    def test_missing_dlv_no_fails_not_guess(self):
        """dlvNo 는 주문번호로 대체 불가 — 없으면 보내지 않는다."""
        from lemouton.markets.invoice_send import send_invoice
        r = send_invoice(market="eleven11", order_no="O1", courier_name="로젠택배",
                         invoice_no="777", send_ids={"ord_no": "O1"},
                         client=object(), live=True)
        assert r.success is False and "식별자" in (r.error or "")

    def test_live_send_uses_dlv_no(self, monkeypatch):
        import shared.platforms.eleven11.shipping as sh
        got = {}
        monkeypatch.setattr(sh, "send_tracking", lambda **kw: got.update(kw) or True)

        from lemouton.markets.invoice_send import send_invoice
        r = send_invoice(market="eleven11", order_no="O1", courier_name="로젠택배",
                         invoice_no="777", send_ids={"dlv_no": "D77", "ord_no": "O1",
                                                     "ord_prd_seq": "2"},
                         client=object(), live=True)
        assert r.success is True
        assert got["dlv_no"] == "D77" and got["delivery_company_code"] == "00002"
        assert got["invoice_number"] == "777"

    def test_dry_run_makes_no_call(self, monkeypatch):
        import shared.platforms.eleven11.shipping as sh
        called = []
        monkeypatch.setattr(sh, "send_tracking", lambda **kw: called.append(1))
        from lemouton.markets.invoice_send import send_invoice
        r = send_invoice(market="eleven11", order_no="O1", courier_name="로젠택배",
                         invoice_no="777", send_ids={"dlv_no": "D77"}, live=False)
        assert r.dry_run is True and called == []


class TestUnsupportedMarket:
    @pytest.mark.parametrize("market", ["wemakeprice", "interpark"])
    def test_unsupported_market_fails_loudly(self, market):
        """전송 함수 없는 마켓은 조용히 성공하지 않는다(거짓 성공 금지).
        (옥션·G마켓은 2026-07-21 ESM ShippingInfo 로 배선돼 이 목록에서 빠졌다.)"""
        from lemouton.markets.invoice_send import send_invoice
        r = send_invoice(market=market, order_no="1", courier_name="로젠택배",
                         invoice_no="1", live=True)
        assert r.success is False
        assert market in (r.error or "")

    @pytest.mark.parametrize("market", ["auction", "gmarket"])
    def test_esm_클라이언트_없으면_조용히_성공하지_않는다(self, market):
        """배선됐어도 client 없이 live 전송하면 정직한 실패여야 한다."""
        from lemouton.markets.invoice_send import send_invoice
        r = send_invoice(market=market, order_no="1", courier_name="로젠택배",
                         invoice_no="1", live=True)   # client=None
        assert r.success is False and r.error


from lemouton.markets import invoice_send as inv


# ── 옥션·G마켓(ESM) 송장 전송 (2026-07-21 배선) ─────────────────────────────

class _EsmShipClient:
    def __init__(self, resp=None):
        self.calls = []
        self._resp = resp if resp is not None else {"ResultCode": 0}

    def post(self, path, body, **kw):
        self.calls.append((path, dict(body)))
        return self._resp


def test_esm_드라이런이_기본이다():
    r = inv.send_invoice(market="auction", order_no="2566434971",
                         courier_name="로젠택배", invoice_no="123456",
                         client=_EsmShipClient())
    assert r.success and r.dry_run          # live=False → 마켓 호출 없음


def test_esm_택배사코드는_마켓_원본표에서_푼다():
    assert inv.resolve_courier_code("auction", "로젠택배") == 10003
    assert inv.resolve_courier_code("gmarket", "롯데택배") == 10008
    import pytest as _pt
    with _pt.raises(inv.CourierCodeUnknown):
        inv.resolve_courier_code("auction", "없는택배사")


def test_esm_실전송은_규격대로_보낸다():
    cli = _EsmShipClient()
    r = inv.send_invoice(market="gmarket", order_no="4470838482",
                         courier_name="로젠택배", invoice_no="98765",
                         client=cli, live=True)
    assert r.success and not r.dry_run
    path, body = cli.calls[0]
    assert path == "/shipping/v1/Delivery/ShippingInfo"
    assert body["OrderNo"] == 4470838482 and body["DeliveryCompanyCode"] == 10003
    assert body["InvoiceNo"] == "98765"
    assert "T" in body["ShippingDate"]      # YYYY-MM-DDThh:mm:ss


def test_esm_마켓거부는_사유와_함께_실패한다():
    """HTTP 200 이어도 ResultCode 가 0이 아니면 실패 — 거짓 성공 금지."""
    cli = _EsmShipClient({"ResultCode": 2000, "Message": "주문 상태가 발송처리 불가"})
    r = inv.send_invoice(market="auction", order_no="1", courier_name="로젠택배",
                         invoice_no="9", client=cli, live=True)
    assert not r.success
    assert "발송처리 불가" in (r.error or "")


def test_esm_이미발송_주문은_덮어쓰지_않는다():
    r = inv.send_invoice(market="auction", order_no="1", courier_name="로젠택배",
                         invoice_no="9", client=_EsmShipClient(), live=True,
                         order_status="배송중")
    assert not r.success and "덮어쓰기 금지" in r.error


def test_esm_되읽기는_NoSongjang_을_읽는다(monkeypatch):
    monkeypatch.setattr("shared.platforms.esm.orders.fetch_by_order_no",
                        lambda m, no, *, client, since=None, until=None:
                        ({"OrderNo": 1, "NoSongjang": "555"}, None))
    got = inv.read_registered_invoice(market="auction", order_no="1", client=object())
    assert got == "555"
