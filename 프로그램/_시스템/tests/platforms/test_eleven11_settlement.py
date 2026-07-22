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
    def test_keys_by_ordno_ordprdseq_and_skips_missing_stlamt(self):
        from shared.platforms.eleven11.settlement import parse_settlement
        out = parse_settlement(_XML)
        # ★라인 단위 키 (ordNo, ordPrdSeq) — 같은 ordNo 여러 라인이 합쳐지지 않는다(over-count 방지)
        assert out == {("20260601123456789", "1"): 10000,
                       ("20260601123456789", "2"): 5000,
                       ("20260602987654321", "1"): 7000}
        assert ("20260603111111111", "1") not in out   # stlAmt 없음 → 스킵(0 대체 금지)

    def test_settled_is_selprc_minus_deduct(self):
        """정산금액 = selPrcAmt − deductAmt. stlAmt 는 배송비 라인서 공제(서비스이용료) 미반영
        총액이라 배송비만 과다계상됨(라이브 실검증). selPrcAmt/deductAmt 있으면 그걸로 계산."""
        from shared.platforms.eleven11.settlement import parse_settlement
        xml = ('<?xml version="1.0" encoding="euc-kr"?><ns2:seStlDtlLists xmlns:ns2="http://x">'
               '<ns2:seStlDtl><ordNo>555</ordNo><ordPrdSeq>1</ordPrdSeq>'
               '<stlAmt>65032</stlAmt><selPrcAmt>73200</selPrcAmt><deductAmt>8168</deductAmt></ns2:seStlDtl>'
               '<ns2:seStlDtl><ordNo>555</ordNo><ordPrdSeq>2</ordPrdSeq>'
               '<stlAmt>4000</stlAmt><selPrcAmt>4000</selPrcAmt><deductAmt>212</deductAmt></ns2:seStlDtl>'
               '</ns2:seStlDtlLists>')
        out = parse_settlement(xml)
        assert out[("555", "1")] == 65032        # 73200 − 8168 (stlAmt 와 동일)
        assert out[("555", "2")] == 3788          # 4000 − 212 (stlAmt 4000 아님 — 배송비 공제 반영)

    def test_none_and_empty_root(self):
        from shared.platforms.eleven11.settlement import parse_settlement
        assert parse_settlement(None) == {}
        assert parse_settlement("") == {}

    def test_parses_when_lines_nested_under_wrapper(self):
        """실 응답이 <Response><seStlDtlList><seStlDtl>… 처럼 한 겹 더 감싸도 파싱돼야 한다.
        (라이브 전 실 구조 미확인 → root.iter() 견고성 회귀 방지. 평면 for el in root 면 {} 반환)."""
        from shared.platforms.eleven11.settlement import parse_settlement
        wrapped = """<?xml version="1.0" encoding="euc-kr"?>
<ns2:Response xmlns:ns2="http://www.11st.co.kr/Settlement">
  <ns2:totalCount>2</ns2:totalCount>
  <ns2:seStlDtlList>
    <ns2:seStlDtl>
      <ns2:ordNo>20260601123456789</ns2:ordNo>
      <ns2:ordPrdSeq>1</ns2:ordPrdSeq>
      <ns2:stlAmt>10000</ns2:stlAmt>
    </ns2:seStlDtl>
    <ns2:seStlDtl>
      <ns2:ordNo>20260602987654321</ns2:ordNo>
      <ns2:ordPrdSeq>1</ns2:ordPrdSeq>
      <ns2:stlAmt>7000</ns2:stlAmt>
    </ns2:seStlDtl>
  </ns2:seStlDtlList>
</ns2:Response>"""
        out = parse_settlement(wrapped)
        assert out == {("20260601123456789", "1"): 10000, ("20260602987654321", "1"): 7000}


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
        assert out[("20260601123456789", "1")] == 10000 * n_windows
        assert out[("20260601123456789", "2")] == 5000 * n_windows
        assert out[("20260602987654321", "1")] == 7000 * n_windows

    def test_single_window_short_range(self):
        from shared.platforms.eleven11.settlement import settlement_map
        since = _dt.datetime(2026, 7, 1, tzinfo=KST)
        until = _dt.datetime(2026, 7, 5, tzinfo=KST)   # 4일 → 윈도우 1개
        fake = _FakeClient(_XML)
        out = settlement_map(since, until, client=fake)
        assert len(fake.calls) == 1
        assert out[("20260601123456789", "1")] == 10000
        assert out[("20260601123456789", "2")] == 5000


class TestSettlementDetails:
    def test_옵션가도_함께_뽑는다(self):
        """정산 응답의 optAmt(옵션가) — 주문 목록 API 엔 이 필드가 없어(지도 전수조사)
        옵션추가금의 유일한 소스다(2026-07-21 사장님: 공란 채움 지시)."""
        from shared.platforms.eleven11.settlement import parse_settlement_details
        xml = _XML.replace(
            "<ns2:stlAmt>10000</ns2:stlAmt>",
            "<ns2:stlAmt>10000</ns2:stlAmt><ns2:optAmt>2000</ns2:optAmt>")
        out = parse_settlement_details(xml)
        assert out[("20260601123456789", "1")]["정산금액"] == 10000
        assert out[("20260601123456789", "1")]["옵션추가금"] == 2000
        # optAmt 없는 라인은 옵션추가금 없음(0 대체 금지)
        assert "옵션추가금" not in out[("20260602987654321", "1")]

    def test_기존_settlement_map_계약은_그대로(self):
        from shared.platforms.eleven11.settlement import settlement_map
        since = _dt.datetime(2026, 6, 1, tzinfo=KST)
        until = _dt.datetime(2026, 6, 5, tzinfo=KST)
        fake = _FakeClient(_XML)
        m = settlement_map(since, until, client=fake)
        assert m[("20260601123456789", "1")] == 10000


class TestDeliverySplit:
    def test_배송비는_정산에서_분리된다(self):
        """실측(2026-07-23 라이브 프로브): 정산 라인 한 줄에 dlvAmt(배송비)가 함께 온다.
        분리 안 하면 정산예정금액이 샵마인 M열보다 +배송비 과대(K/L 이중 가산)."""
        from shared.platforms.eleven11.settlement import parse_settlement_details
        xml = _XML.replace(
            "<ns2:stlAmt>10000</ns2:stlAmt>",
            "<ns2:stlAmt>13000</ns2:stlAmt><ns2:dlvAmt>3000</ns2:dlvAmt>")
        out = parse_settlement_details(xml)
        e = out[("20260601123456789", "1")]
        assert e["정산금액"] == 13000          # 총액(배송비 포함) 그대로
        assert e["배송비정산"] == 3000          # 분리 보관 → 조인이 빼서 M열 정합
