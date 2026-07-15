# -*- coding: utf-8 -*-
"""[TEST] 11번가 정산금액(settlementList, 구매확정분) — XML 파싱·윈도우 분할·병합.

키 없이 검증(Fake client). 근거 스펙: 공개문서 openapi.11st.co.kr
(GET /rest/settlement/settlementList/{start}/{end}, YYYYMMDD, XML euc-kr).
"""
import datetime as _dt

KST = _dt.timezone(_dt.timedelta(hours=9))

# 2 라인 같은 ordNo(ordPrdSeq 다름, 합산) + 1 다른 ordNo + 1 stlAmt 없는 라인(스킵).
_XML = """<?xml version="1.0" encoding="euc-kr" standalone="yes"?>
<ns2:seStlDtlList xmlns:ns2="http://www.11st.co.kr/Settlement">
  <ns2:seStlDtl>
    <ns2:ordNo>20260601123456789</ns2:ordNo>
    <ns2:ordPrdSeq>1</ns2:ordPrdSeq>
    <ns2:stlAmt>10000</ns2:stlAmt>
    <ns2:selFee>500</ns2:selFee>
    <ns2:pocnfrmDt>2026-06-01 10:00:00</ns2:pocnfrmDt>
  </ns2:seStlDtl>
  <ns2:seStlDtl>
    <ns2:ordNo>20260601123456789</ns2:ordNo>
    <ns2:ordPrdSeq>2</ns2:ordPrdSeq>
    <ns2:stlAmt>5000</ns2:stlAmt>
  </ns2:seStlDtl>
  <ns2:seStlDtl>
    <ns2:ordNo>20260602987654321</ns2:ordNo>
    <ns2:ordPrdSeq>1</ns2:ordPrdSeq>
    <ns2:stlAmt>7000</ns2:stlAmt>
  </ns2:seStlDtl>
  <ns2:seStlDtl>
    <ns2:ordNo>20260603111111111</ns2:ordNo>
    <ns2:ordPrdSeq>1</ns2:ordPrdSeq>
  </ns2:seStlDtl>
</ns2:seStlDtlList>"""


class _FakeClient:
    def __init__(self, xml):
        self.xml = xml
        self.calls = []

    def request(self, method, path, body=None):
        self.calls.append((method, path))
        return self.xml


class TestParseSettlement:
    def test_sums_by_ordno_and_skips_missing_stlamt(self):
        from shared.platforms.eleven11.settlement import parse_settlement
        out = parse_settlement(_XML)
        assert out == {"20260601123456789": 15000, "20260602987654321": 7000}
        assert "20260603111111111" not in out   # stlAmt 없음 → 스킵(0 대체 금지)

    def test_none_and_empty_root(self):
        from shared.platforms.eleven11.settlement import parse_settlement
        assert parse_settlement(None) == {}
        assert parse_settlement("") == {}


class TestSettlementMap:
    def test_windows_31day_and_path_format(self):
        from shared.platforms.eleven11.settlement import settlement_map
        since = _dt.datetime(2026, 5, 1, tzinfo=KST)
        until = _dt.datetime(2026, 7, 10, tzinfo=KST)   # 70일 → 31일 윈도우 3개
        fake = _FakeClient(_XML)
        settlement_map(since, until, client=fake)
        assert len(fake.calls) == 3
        m, path = fake.calls[0]
        assert m == "GET"
        # YYYYMMDD(일 단위) — orders.py 의 분단위 포맷과 다름
        assert path == "/rest/settlement/settlementList/20260501/20260601"

    def test_merges_across_windows(self):
        from shared.platforms.eleven11.settlement import settlement_map
        since = _dt.datetime(2026, 5, 1, tzinfo=KST)
        until = _dt.datetime(2026, 7, 10, tzinfo=KST)
        fake = _FakeClient(_XML)
        out = settlement_map(since, until, client=fake)
        n_windows = len(fake.calls)
        # 매 윈도우 같은 XML(테스트 편의) → ordNo 별 합계가 윈도우 수만큼 배가돼야 병합 확인 가능
        assert out["20260601123456789"] == 15000 * n_windows
        assert out["20260602987654321"] == 7000 * n_windows

    def test_single_window_short_range(self):
        from shared.platforms.eleven11.settlement import settlement_map
        since = _dt.datetime(2026, 7, 1, tzinfo=KST)
        until = _dt.datetime(2026, 7, 5, tzinfo=KST)   # 4일 → 윈도우 1개
        fake = _FakeClient(_XML)
        out = settlement_map(since, until, client=fake)
        assert len(fake.calls) == 1
        assert out["20260601123456789"] == 15000
