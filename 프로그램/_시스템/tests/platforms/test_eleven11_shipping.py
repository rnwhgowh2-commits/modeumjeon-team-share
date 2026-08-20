# -*- coding: utf-8 -*-
"""[TEST] 11번가 발송처리(reqdelivery) — GET 경로 조립 · result_code 판정.

근거: 오픈소스 구현 3건 교차 확인(2026-07-10)
  · ctrlv290/Dyflux  _CLASS/API_11st.php  (공식문서 URL 스펙 주석 포함)
  · sbk0674-web/samba-wave  proxy/elevenst.py (운영 중 · 에러코드 의미 기록)
  · yoolk/elevenstreet  api/order.rb

핵심 안전 규칙:
  · result_code 0 = 성공. -3308(합포장으로 이미 발송)·-3309(이미 배송완료)도 목표상태 도달 → 성공.
  · **-3313 은 성공 아님** — "발송처리할 목록 없음". 성공 처리하면 송장 없이 「전송완료」로 뜨는 거짓 성공.
"""
import datetime as _dt

import pytest


def _xml(code, text="msg"):
    return ('<?xml version="1.0" encoding="euc-kr"?>'
            f"<ClientResponse><result_code>{code}</result_code>"
            f"<result_text>{text}</result_text></ClientResponse>")


class FakeClient:
    def __init__(self, xml):
        self._xml = xml
        self.calls = []

    def request(self, method, path, body=None):
        self.calls.append((method, path))
        return self._xml


WHEN = _dt.datetime(2026, 7, 10, 14, 5)


# ── 경로 조립 ────────────────────────────────────────────────
class TestRequestPath:
    def test_get_path_is_reqdelivery_with_five_segments(self):
        """GET /rest/ordservices/reqdelivery/{sendDt}/{dlvMthdCd}/{dlvEtprsCd}/{invcNo}/{dlvNo}"""
        from shared.platforms.eleven11 import shipping as sh
        c = FakeClient(_xml("0"))
        sh.send_tracking(dlv_no="D100", invoice_number="9988776655",
                         delivery_company_code="00002", client=c, occurred_at=WHEN)
        method, path = c.calls[0]
        assert method == "GET"
        assert path == "/rest/ordservices/reqdelivery/202607101405/01/00002/9988776655/D100"

    def test_send_dt_is_yyyymmddhhmm(self):
        """발송일시 = YYYYMMDDhhmm (분 단위). ddmmyyyy 아님."""
        from shared.platforms.eleven11 import shipping as sh
        c = FakeClient(_xml("0"))
        sh.send_tracking(dlv_no="D1", invoice_number="1", delivery_company_code="00002",
                         client=c, occurred_at=_dt.datetime(2026, 1, 2, 3, 4))
        assert "/202601020304/" in c.calls[0][1]


# ── 결과 판정 ────────────────────────────────────────────────
class TestResultCode:
    def test_zero_is_success(self):
        from shared.platforms.eleven11 import shipping as sh
        assert sh.send_tracking(dlv_no="D1", invoice_number="1",
                                delivery_company_code="00002",
                                client=FakeClient(_xml("0")), occurred_at=WHEN) is True

    @pytest.mark.parametrize("code", ["-3308", "-3309"])
    def test_already_shipped_codes_are_success(self, code):
        """합포장(같은 배송번호 다른 주문이 먼저 처리)·이미 배송완료 = 목표상태 도달 → 성공."""
        from shared.platforms.eleven11 import shipping as sh
        assert sh.send_tracking(dlv_no="D1", invoice_number="1",
                                delivery_company_code="00002",
                                client=FakeClient(_xml(code)), occurred_at=WHEN) is True

    def test_3313_is_failure_not_silent_success(self):
        """-3313 = 발송처리할 목록 없음 → 송장이 등록되지 않는다. 거짓 성공 금지."""
        from shared.platforms.eleven11 import shipping as sh
        with pytest.raises(sh.Eleven11ShipError) as e:
            sh.send_tracking(dlv_no="D1", invoice_number="1", delivery_company_code="00002",
                             client=FakeClient(_xml("-3313", "발송처리할 목록이 없습니다")),
                             occurred_at=WHEN)
        assert "-3313" in str(e.value)

    def test_other_error_raises_with_code_and_text(self):
        from shared.platforms.eleven11 import shipping as sh
        with pytest.raises(sh.Eleven11ShipError) as e:
            sh.send_tracking(dlv_no="D1", invoice_number="1", delivery_company_code="00002",
                             client=FakeClient(_xml("-3306", "잘못된 택배사")), occurred_at=WHEN)
        assert "-3306" in str(e.value) and "잘못된 택배사" in str(e.value)


# ── 입력 검증(추측 전송 금지) ────────────────────────────────
class TestGuards:
    @pytest.mark.parametrize("kw", [
        {"dlv_no": "", "invoice_number": "1", "delivery_company_code": "00002"},
        {"dlv_no": "D1", "invoice_number": "", "delivery_company_code": "00002"},
        {"dlv_no": "D1", "invoice_number": "1", "delivery_company_code": ""},
    ])
    def test_empty_required_value_raises_before_any_call(self, kw):
        from shared.platforms.eleven11 import shipping as sh
        c = FakeClient(_xml("0"))
        with pytest.raises(ValueError):
            sh.send_tracking(client=c, occurred_at=WHEN, **kw)
        assert c.calls == []          # 호출 자체가 없어야 한다
