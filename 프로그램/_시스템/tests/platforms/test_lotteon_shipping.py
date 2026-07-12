# -*- coding: utf-8 -*-
"""[TEST] 롯데온 발송처리(배송상태 통보) 요청 본문.

근거: 롯데ON API 센터 「배송상태 통보」 apiNo=137 공식 문서·요청 샘플 직접 판독(2026-07-10).
  POST https://openapi.lotteon.com/v1/openapi/delivery/v1/SellerDeliveryProgressStateInform
  body: {"deliveryProgressStateList":[{dvRtrvDvsCd:"DV", odNo, odSeq, procSeq,
          odPrgsStepCd:"13"(발송완료), dvTrcStatDttm:"yyyymmddhhmmss",
          invcNbr, dvCoCd, invcNo, spdNo, sitmNo, slQty, ...}]}
  성공: returnCode "0000"
  택배사코드(dvCoCd): 로젠택배 = 0005  (쿠팡 KGB · 네이버 LOGEN 과 전부 다름)

⚠️ 라이브 미검증 — 실계정 1건 전송으로 최종 확인.
"""
import pytest


class FakeLo:
    def __init__(self, resp=None):
        self.method = self.path = self.body = None
        self.resp = resp or {"returnCode": "0000", "data": {"rsltCd": "0000"}}

    def request(self, method, path, body=None):
        self.method, self.path, self.body = method, path, body
        return self.resp


def _item(fake):
    return fake.body["deliveryProgressStateList"][0]


def _send(fake, **kw):
    from shared.platforms.lotteon.shipping import send_tracking
    args = dict(od_no="OD1", od_seq="3", proc_seq="1", spd_no="LO#100",
                sitm_no="LO#10010", qty="2", delivery_company_code="0005",
                invoice_number="1234567890", client=fake)
    args.update(kw)
    return send_tracking(**args)


class TestCourierCodes:
    def test_logen_is_0005(self):
        from shared.platforms.lotteon.shipping import DELIVERY_COMPANY_CODES
        assert DELIVERY_COMPANY_CODES["로젠택배"] == "0005"
        assert DELIVERY_COMPANY_CODES["CJ대한통운"] == "0002"
        assert DELIVERY_COMPANY_CODES["롯데택배"] == "0001"


class TestSendTracking:
    def test_posts_to_delivery_progress_endpoint(self):
        fake = FakeLo()
        _send(fake)
        assert fake.method == "POST"
        assert fake.path == "/v1/openapi/delivery/v1/SellerDeliveryProgressStateInform"

    def test_marks_shipped_step_13_with_delivery_type(self):
        fake = FakeLo()
        _send(fake)
        it = _item(fake)
        assert it["odPrgsStepCd"] == "13"     # 발송완료
        assert it["dvRtrvDvsCd"] == "DV"      # 배송(회수 아님)

    def test_carries_all_required_ids(self):
        fake = FakeLo()
        _send(fake)
        it = _item(fake)
        assert it["odNo"] == "OD1" and it["odSeq"] == "3" and it["procSeq"] == "1"
        assert it["spdNo"] == "LO#100" and it["sitmNo"] == "LO#10010"
        assert it["slQty"] == "2"

    def test_carries_courier_and_invoice(self):
        fake = FakeLo()
        _send(fake)
        it = _item(fake)
        assert it["dvCoCd"] == "0005"
        assert it["invcNo"] == "1234567890"
        assert it["invcNbr"] == "1"            # 송장 1개

    def test_timestamp_is_14_digits(self):
        fake = FakeLo()
        _send(fake)
        dt = _item(fake)["dvTrcStatDttm"]
        assert len(dt) == 14 and dt.isdigit()  # yyyymmddhhmmss

    def test_success_on_return_code_0000(self):
        assert _send(FakeLo()) is True

    def test_failure_surfaces(self):
        fake = FakeLo(resp={"returnCode": "3024", "message": "주문진행단계 코드가 유효하지 않습니다."})
        assert _send(fake) is False

    def test_empty_invoice_raises(self):
        with pytest.raises(ValueError):
            _send(FakeLo(), invoice_number="")
