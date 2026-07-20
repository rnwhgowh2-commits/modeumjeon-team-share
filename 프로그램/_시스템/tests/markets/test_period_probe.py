"""조회기간 프로브 판정 로직 — 라이브 호출 없이 fake client 로 검증.

핵심 위험: '거부(rejected)' 와 '오류(error)' 를 섞으면 상한을 잘못 확정한다.
  - 인증·IP 실패를 rejected 로 읽으면 → 있지도 않은 상한을 만들어낸다
  - 0건 응답을 rejected 로 읽으면 → 실제보다 짧은 상한을 확정한다(조용한 데이터 누락)
그래서 이 두 경계를 테스트로 못 박는다.
"""
from __future__ import annotations

import datetime as _dt

import pytest

from lemouton.markets import period_probe as P

NOW = _dt.datetime(2026, 7, 20, 12, 0, tzinfo=P.KST)


class _FakeCoupang:
    _cfg = {"vendor_id": "A00000000"}

    def __init__(self, resp=None, exc=None):
        self.resp, self.exc, self.calls = resp, exc, []

    def request(self, method, path, query=None, **kw):
        self.calls.append((method, path, query))
        if self.exc:
            raise self.exc
        return self.resp


def test_구간이_now_기준으로_계산된다():
    c = _FakeCoupang({"code": 200, "data": []})
    r = P.probe("coupang", "orders", window_days=31, back_days=90, client=c, now=NOW)
    assert r["end"] == "2026-04-21 12:00"      # now - 90일
    assert r["start"] == "2026-03-21 12:00"    # 그로부터 다시 31일 전


def test_영건_응답은_accepted_다():
    """데이터 없음 ≠ 마켓 거부. 여기서 rejected 로 읽으면 상한이 짧게 확정된다."""
    c = _FakeCoupang({"code": 200, "data": []})
    r = P.probe("coupang", "orders", window_days=31, back_days=0, client=c, now=NOW)
    assert r["verdict"] == "accepted"
    assert r["count"] == 0


def test_기간초과_에러는_rejected():
    c = _FakeCoupang(exc=RuntimeError("endTime-startTime range should less than31."))
    r = P.probe("coupang", "orders", window_days=32, back_days=0, client=c, now=NOW)
    assert r["verdict"] == "rejected"


@pytest.mark.parametrize("msg", [
    "403 Forbidden — 출발지 IP 미등록",
    "401 Unauthorized",
    "Connection timed out",
])
def test_인증IP네트워크_실패는_error_지_rejected_가_아니다(msg):
    """이걸 rejected 로 읽으면 없는 상한을 날조하게 된다."""
    c = _FakeCoupang(exc=RuntimeError(msg))
    r = P.probe("coupang", "orders", window_days=365, back_days=0, client=c, now=NOW)
    assert r["verdict"] == "error"


def test_클라이언트_없으면_error_지_rejected_아니다():
    r = P.probe("coupang", "orders", window_days=31, back_days=0, client=None, now=NOW)
    assert r["verdict"] == "error"
    assert "키 미등록" in r["message"]


def test_지원하지_않는_마켓과_kind_는_명확히_거절():
    with pytest.raises(ValueError, match="지원하지 않는 마켓"):
        P.probe("shopmine", "orders", window_days=1, back_days=0, client=object())
    with pytest.raises(ValueError, match="미지원"):
        P.probe("smartstore", "claims_return", window_days=1, back_days=0, client=object())


class _FakeEleven:
    def __init__(self, xml):
        self.xml = xml

    def request(self, method, path, body=None):
        return self.xml


def test_11번가_음수코드는_기간사유일때만_rejected():
    ok = _FakeEleven("<ns:orders><ns:resultCode>0</ns:resultCode></ns:orders>")
    assert P.probe("eleven11", "orders", window_days=7, back_days=0,
                   client=ok, now=NOW)["verdict"] == "accepted"

    over = _FakeEleven("<ns:orders><ns:resultCode>-3904</ns:resultCode>"
                       "<ns:resultMessage>최대 조회기간은 일주일입니다</ns:resultMessage></ns:orders>")
    assert P.probe("eleven11", "orders", window_days=8, back_days=0,
                   client=over, now=NOW)["verdict"] == "rejected"

    auth = _FakeEleven("<ns:orders><ns:resultCode>-101</ns:resultCode>"
                       "<ns:resultMessage>인증키가 유효하지 않습니다</ns:resultMessage></ns:orders>")
    assert P.probe("eleven11", "orders", window_days=8, back_days=0,
                   client=auth, now=NOW)["verdict"] == "error"


class _FakeLotteon:
    def __init__(self, resp):
        self.resp = resp

    def request(self, method, path, body=None, **kw):
        return self.resp


def test_롯데온_2003은_기간초과_rejected():
    r = P.probe("lotteon", "orders", window_days=2, back_days=0,
                client=_FakeLotteon({"returnCode": "2003",
                                     "returnMessage": "조회기간 오류"}), now=NOW)
    assert r["verdict"] == "rejected"


def test_롯데온_정상은_accepted():
    r = P.probe("lotteon", "orders", window_days=1, back_days=0,
                client=_FakeLotteon({"returnCode": "0", "data": [{"a": 1}]}), now=NOW)
    assert r["verdict"] == "accepted" and r["count"] == 1


class _FakeEsm:
    def __init__(self, resp):
        self.resp = resp

    def request_orders(self, body):
        return self.resp

    def post(self, path, body, **kw):
        return self.resp


def test_ESM_1100_데이터없음은_accepted():
    """ESM 은 '데이터 없음'을 ResultCode 1100 으로 준다. 거부로 읽으면 안 된다."""
    r = P.probe("auction", "orders", window_days=180, back_days=0,
                client=_FakeEsm({"ResultCode": 1100}), now=NOW)
    assert r["verdict"] == "accepted"


def test_ESM_기간초과는_rejected():
    r = P.probe("auction", "orders", window_days=181, back_days=0,
                client=_FakeEsm({"ResultCode": 9, "Message": "조회기간은 31일 이내"}), now=NOW)
    assert r["verdict"] == "rejected"


def test_모든_마켓_kind_조합이_등록되어_있다():
    """조사 대상 6마켓이 최소한 orders 프로브를 갖는다(누락 시 조용히 빠진다)."""
    for m in ("coupang", "smartstore", "eleven11", "lotteon", "auction", "gmarket"):
        assert "orders" in P.PROBES[m], m
    for m in ("coupang", "eleven11", "lotteon", "auction", "gmarket"):
        assert any(k.startswith("claims") for k in P.PROBES[m]), m
